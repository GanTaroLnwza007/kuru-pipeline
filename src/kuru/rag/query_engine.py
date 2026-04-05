"""RAG query engine — embed query → pgvector retrieval → Gemini generation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv
from google import genai
from google.genai import types
from tenacity import retry, stop_after_attempt, wait_exponential

from kuru.db import supabase_client as db

load_dotenv()

_client: genai.Client | None = None

def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client

EMBEDDING_MODEL = "gemini-embedding-001"
GENERATION_MODEL = "gemini-2.0-flash"
TOP_K = 5

# Thai + English keywords that signal a TCAS admission question
TCAS_KEYWORDS = re.compile(
    r"GPAX|เกรด|รับ|สมัคร|คะแนน|รอบ|TGAT|TPAT|A-Level|quota|โควตา|วันรับ|ประกาศ|admission",
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

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
def _embed_query(query: str) -> list[float]:
    response = _get_client().models.embed_content(
        model=EMBEDDING_MODEL,
        contents=query,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_QUERY",
            output_dimensionality=768,
        ),
    )
    return response.embeddings[0].values


# ─────────────────────────────────────────
# Generation
# ─────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=30))
def _generate(context: str, question: str) -> str:
    prompt = RAG_USER_TEMPLATE.format(context=context, question=question)
    response = _get_client().models.generate_content(
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

    # 3. If TCAS keywords detected, also pull structured admission data
    tcas_records: list[dict] = []
    used_tcas = False
    if TCAS_KEYWORDS.search(question):
        tcas_records = db.get_tcas_records(client, program_id=program_id)
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
