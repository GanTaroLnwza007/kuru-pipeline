"""RAG query engine — local embed query → pgvector retrieval → Gemini generation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv
from google import genai
from google.genai import types
from sentence_transformers import SentenceTransformer
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from kuru.db import supabase_client as db

load_dotenv()

_genai_client: genai.Client | None = None
_embed_model: SentenceTransformer | None = None

EMBED_MODEL_NAME = "intfloat/multilingual-e5-base"
GENERATION_MODEL = "gemini-2.5-flash-lite"
TOP_K = 5


def _get_genai_client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _genai_client


def _get_embed_model() -> SentenceTransformer:
    global _embed_model
    if _embed_model is None:
        _embed_model = SentenceTransformer(EMBED_MODEL_NAME)
    return _embed_model


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (TypeError, ValueError, AttributeError, UnicodeError)):
        return False
    return any(c in str(exc) for c in ("429", "500", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE"))

# Thai + English keywords that signal a TCAS admission question
TCAS_KEYWORDS = re.compile(
    r"TCAS|GPAX|เกรด|รับ|สมัคร|คะแนน|รอบ|TGAT|TPAT|A-Level|quota|โควตา|วันรับ|ประกาศ|admission|score|portfolio|enroll|สอบ|ข้อสอบ",
    re.IGNORECASE,
)

RAG_SYSTEM_PROMPT = """You are KUru Advisor, an AI assistant for Kasetsart University (KU) students and prospective applicants.
Answer questions accurately in the same language as the question (Thai or English).
Base your answer ONLY on the provided context passages.
At the end of your answer, cite the source documents used as: [Source: <filename>, section: <section_type>]
If the answer is not found in the context, say so clearly — do not guess."""

RAG_USER_TEMPLATE = """Context passages:
{context}

---
Question: {question}

Answer:"""


@dataclass
class RAGResult:
    answer: str
    sources: list[dict]   # [{source_file, section_type, similarity}]
    used_tcas_data: bool


# ─────────────────────────────────────────
# Embedding
# ─────────────────────────────────────────

def _embed_query(query: str) -> list[float]:
    """Embed a query using the local multilingual-e5 model (query: prefix)."""
    vector = _get_embed_model().encode(
        f"query: {query}", normalize_embeddings=True, show_progress_bar=False
    )
    return vector.tolist()


# ─────────────────────────────────────────
# Generation
# ─────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30), retry=retry_if_exception(_is_transient), reraise=True)
def _generate(context: str, question: str) -> str:
    prompt = RAG_USER_TEMPLATE.format(context=context, question=question)
    response = _get_genai_client().models.generate_content(
        model=GENERATION_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            system_instruction=RAG_SYSTEM_PROMPT,
            temperature=0.2,
        ),
    )
    return response.text or "(No response generated)"


# ─────────────────────────────────────────
# TCAS structured data retrieval
# ─────────────────────────────────────────

def _format_tcas_records(records: list[dict]) -> str:
    if not records:
        return ""
    lines = ["[TCAS Admission Data]"]
    for r in records:
        lines.append(
            f"Program: {r.get('program_name_raw', r.get('program_id', '?'))} | "
            f"Round: {r.get('round', '?')} | "
            f"Quota: {r.get('quota', '?')} | "
            f"GPAX min: {r.get('gpax_min', '?')} | "
            f"Exam criteria: {r.get('exam_criteria', {})} | "
            f"Portfolio: {r.get('portfolio_requirements', {})}"
        )
    return "\n".join(lines)


# ─────────────────────────────────────────
# Main query function
# ─────────────────────────────────────────

def query(
    question: str,
    top_k: int = TOP_K,
    program_id: str | None = None,
) -> RAGResult:
    """Run RAG over มคอ.2 chunks, with TCAS structured data augmentation."""
    client = db.get_client()

    # 1. Embed the query
    q_embedding = _embed_query(question)

    # 2. Retrieve relevant chunks from pgvector
    chunks = db.similarity_search(client, q_embedding, top_k=top_k, program_id=program_id)

    # 3. If TCAS keywords detected, pull relevant TCAS records
    tcas_records: list[dict] = []
    used_tcas = False
    if TCAS_KEYWORDS.search(question):
        all_tcas = db.get_tcas_records(client, program_id=program_id)
        if all_tcas:
            # Try to filter by keywords from the question to avoid dumping all 300+ records
            # Extract meaningful words (4+ chars) from question for matching
            q_words = [w for w in re.findall(r"[a-zA-Zก-๙]{4,}", question) if len(w) >= 4]
            # Try keyword match against Thai program names in memory
            matched: list[dict] = []
            if q_words:
                matched = [
                    r for r in all_tcas
                    if any(w.lower() in (r.get("program_name_raw") or "").lower() for w in q_words)
                    or any(w.lower() in (r.get("faculty") or "").lower() for w in q_words)
                ]
            # If no match, search TCAS using Thai words from ALL retrieved chunk filenames
            # This handles queries asking about multiple programs simultaneously
            if not matched and chunks:
                seen_sources: set[str] = set()
                for chunk in chunks:
                    src = chunk.get("source_file", "")
                    if src in seen_sources:
                        continue
                    seen_sources.add(src)
                    thai_words_in_filename = re.findall(r"[ก-๙]{5,}", src)
                    for tw in thai_words_in_filename:
                        candidates = db.get_tcas_records(client, program_name_search=tw, limit=10)
                        matched.extend(candidates)
                        if candidates:
                            break  # one search term per file is enough
            tcas_records = matched[:30] if matched else all_tcas[:10]
            used_tcas = bool(tcas_records)

    # 4. Assemble context
    context_parts: list[str] = []
    for c in chunks:
        context_parts.append(
            f"[{c['source_file']} | {c.get('section_type', 'general')}]\n{c['content']}"
        )
    if tcas_records:
        context_parts.append(_format_tcas_records(tcas_records))

    context = "\n\n---\n\n".join(context_parts) if context_parts else "No relevant context found."

    # 5. Generate answer
    answer = _generate(context, question)

    # 6. Build sources list
    sources = [
        {
            "source_file": c.get("source_file", ""),
            "section_type": c.get("section_type", ""),
            "similarity": round(c.get("similarity", 0.0), 3),
        }
        for c in chunks
    ]

    return RAGResult(answer=answer, sources=sources, used_tcas_data=used_tcas)
