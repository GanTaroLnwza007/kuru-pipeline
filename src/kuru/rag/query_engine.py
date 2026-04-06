"""RAG query engine — local embed query → pgvector retrieval → Gemini generation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from dotenv import load_dotenv
from google import genai
from google.genai import types
from sentence_transformers import SentenceTransformer  # used by _get_embed_model return type
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from kuru.db import supabase_client as db

load_dotenv()

_genai_client: genai.Client | None = None

EMBED_MODEL_NAME = "intfloat/multilingual-e5-base"
GENERATION_MODEL = "gemini-2.5-flash-lite"
TOP_K = 5
MIN_SIMILARITY = 0.35   # chunks below this are too weak to be useful


def _get_genai_client() -> genai.Client:
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _genai_client


def _get_embed_model() -> SentenceTransformer:
    # Delegate to embedder's singleton so the model is loaded exactly once
    # regardless of whether demo_rag pre-loads it or the first query triggers it.
    from kuru.ingestion.embedder import _get_model
    return _get_model()


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (TypeError, ValueError, AttributeError, UnicodeError)):
        return False
    return any(c in str(exc) for c in ("429", "500", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE"))

# Thai + English keywords that signal a TCAS admission question
TCAS_KEYWORDS = re.compile(
    r"TCAS|GPAX|เกรด|รับ|สมัคร|คะแนน|รอบ|TGAT|TPAT|A-Level|quota|โควตา|วันรับ|ประกาศ|admission|score|portfolio"
    r"|enroll|apply|applying|application|qualify|qualification|requirement|สอบ|ข้อสอบ|เข้าเรียน|เข้าศึกษา|รับสมัคร|คุณสมบัติ",
    re.IGNORECASE,
)

# Keywords that signal a broad "list all programs" type question
LISTING_KEYWORDS = re.compile(
    r"what programs|what majors|what faculties|what courses|available programs|list.*program|programs.*available"
    r"|หลักสูตรอะไรบ้าง|มีหลักสูตรอะไร|สาขาวิชาอะไรบ้าง|คณะอะไรบ้าง|มีคณะอะไร|เรียนอะไรได้บ้าง"
    r"|มีสาขาอะไร|สาขาใดบ้าง|มีอะไรบ้าง",
    re.IGNORECASE,
)

def _resolve_program_from_query(question: str, programs: list[dict]) -> str | None:
    """Return program_id if the question mentions a program by its English name.

    Picks the longest matching English name to avoid false positives from short tokens.
    """
    q_lower = question.lower()
    best_len = 0
    best_id: str | None = None
    for p in programs:
        name_en = (p.get("name_en") or "").strip().lower()
        if len(name_en) < 8:
            continue
        if name_en in q_lower and len(name_en) > best_len:
            best_len = len(name_en)
            best_id = p["id"]
    return best_id


RAG_SYSTEM_PROMPT = """You are KUru, a warm and knowledgeable academic companion for Kasetsart University (KU) prospective students. Think of yourself as a helpful older student who genuinely cares about guiding juniors — enthusiastic, friendly, and honest.

PERSONALITY:
- Be conversational and natural, not robotic or overly formal.
- Show genuine interest in the student's goals. Acknowledge what they're looking for before diving in.
- When you find good info, present it warmly: "Great news — I found..." or "Here's what I know about..."
- When info is incomplete or missing, be upfront and helpful: "I don't have full details on that yet, but here's what I found..." — then suggest they check the KU website or official admission channels.
- Use "I" naturally. End with an offer to help further.

GROUNDING RULES (non-negotiable):
1. Every fact, number, score, and quota MUST come from the provided context. Never use outside knowledge about KU.
2. If the context is "No relevant context found": be honest and warm — don't just refuse. Say something like "I couldn't find that in my current documents — you might want to check [ku.ac.th] or ask the faculty directly. Want me to help with something related?"
3. If context is partial: share what you found and clearly say what's missing. Don't silently fill gaps.
4. TCAS admission data (scores, GPAX, quotas, exam requirements) come ONLY from [TCAS Admission Data] blocks. Course prerequisite codes (like 01219241) are for enrolled students — never cite them as admission requirements.
5. When answering about TCAS: structure by round (Round 1 / 2 / 3), include seats, GPAX minimum, exam requirements, portfolio, and deadlines.
6. When answering about curriculum: describe PLOs, courses, degree structure — not TCAS scores.
7. Never invent numbers, quotas, dates, or exam scores.
8. Cite sources naturally: "According to [filename]..." or "[Source: filename]" at the end.
9. Answer in the same language as the question (Thai or English).
10. CRITICAL — do NOT recommend or describe programs that appear only in [TCAS Admission Data] blocks as if curriculum details are available. Programs in [TCAS Admission Data] may only have admission data, not full curriculum details. If a student asks about a program that only appears in TCAS data (not in a curriculum context block), clearly say: "I only have admission data for this program, not the full curriculum details. For course lists, PLOs, and program structure, please check ku.ac.th directly." """

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
    debug_info: dict | None = None  # populated when debug=True


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
            f"\n--- Program: {r.get('program_name_raw', r.get('program_id', '?'))} ---"
        )
        lines.append(f"  Round: {r.get('round', 'N/A')}")
        lines.append(f"  Seats (quota): {r.get('quota', 'N/A')}")
        lines.append(f"  GPAX minimum: {r.get('gpax_min', 'N/A')}")
        exam = r.get("exam_criteria")
        if exam:
            lines.append(f"  Exam criteria: {exam}")
        portfolio = r.get("portfolio_requirements")
        if portfolio:
            lines.append(f"  Portfolio requirements: {portfolio}")
        deadlines = r.get("deadlines")
        if deadlines:
            lines.append(f"  Deadlines: {deadlines}")
        src = r.get("source_file")
        if src:
            lines.append(f"  Source: {src}")
    return "\n".join(lines)


# ─────────────────────────────────────────
# Main query function
# ─────────────────────────────────────────

def query(
    question: str,
    top_k: int = TOP_K,
    program_id: str | None = None,
    debug: bool = False,
) -> RAGResult:
    """Run RAG over มคอ.2 chunks, with TCAS structured data augmentation."""
    client = db.get_client()

    # 1. Embed the query
    q_embedding = _embed_query(question)

    # 2. Retrieve relevant chunks from pgvector (always unfiltered first)
    is_tcas_query = bool(TCAS_KEYWORDS.search(question))
    is_plo_query = bool(re.search(r"PLO|plo|ผลลัพธ์การเรียนรู้", question))
    is_listing_query = bool(LISTING_KEYWORDS.search(question))
    # Fetch a larger pool so re-ranking has enough material
    fetch_k = max(top_k * 3, 15)
    all_chunks = db.similarity_search(client, q_embedding, top_k=fetch_k, program_id=program_id)

    # English program name resolution: if the user names a specific program in English,
    # do a targeted search filtered to that program_id and merge it to the front.
    # This fixes the case where English queries fail to retrieve Thai-named documents.
    resolved_program_id: str | None = None
    if not is_listing_query and not program_id:
        all_programs_list = db.get_programs(client)
        resolved_program_id = _resolve_program_from_query(question, all_programs_list)
        if resolved_program_id:
            targeted = db.similarity_search(
                client, q_embedding, top_k=fetch_k, program_id=resolved_program_id
            )
            # Prepend targeted results, then fill with unfiltered (deduplicated by id)
            seen = {c.get("id") for c in targeted}
            all_chunks = targeted + [c for c in all_chunks if c.get("id") not in seen]

    # Drop chunks that are too weak to be useful
    above_threshold = [c for c in all_chunks if c.get("similarity", 0.0) >= MIN_SIMILARITY]

    debug_info: dict = {
        "is_tcas_query": is_tcas_query,
        "is_plo_query": is_plo_query,
        "is_listing_query": is_listing_query,
        "resolved_program_id": resolved_program_id,
        "fetched": len(all_chunks),
        "above_threshold": len(above_threshold),
        "threshold": MIN_SIMILARITY,
        "raw_chunks": [
            {
                "source_file": c.get("source_file", ""),
                "section_type": c.get("section_type", ""),
                "similarity": round(c.get("similarity", 0.0), 3),
                "content_preview": c.get("content", "")[:120],
            }
            for c in all_chunks
        ],
    }

    # 3. If TCAS query (but NOT a pure listing query), find matching TCAS records.
    # We suppress TCAS injection for listing queries because TCAS programs may not have
    # curriculum PDFs — mixing them in causes the model to recommend programs it can't
    # actually describe, leading to contradictory follow-up answers.
    tcas_records: list[dict] = []
    used_tcas = False
    if is_tcas_query and not is_listing_query:
        all_tcas = db.get_tcas_records(client, program_id=program_id)
        if all_tcas:
            q_words = [w for w in re.findall(r"[a-zA-Zก-๙]{4,}", question) if len(w) >= 4]
            matched: list[dict] = []
            # First try: match question words against TCAS program names
            if q_words:
                matched = [
                    r for r in all_tcas
                    if any(w.lower() in (r.get("program_name_raw") or "").lower() for w in q_words)
                    or any(w.lower() in (r.get("faculty") or "").lower() for w in q_words)
                ]
            # Second try: use Thai words from ALL retrieved chunk filenames
            # Use all_chunks (unfiltered) so CPE course chunks still contribute their filename
            if not matched and all_chunks:
                seen_sources: set[str] = set()
                for chunk in all_chunks:
                    src = chunk.get("source_file", "")
                    if src in seen_sources:
                        continue
                    seen_sources.add(src)
                    for tw in re.findall(r"[ก-๙]{5,}", src):
                        candidates = db.get_tcas_records(client, program_name_search=tw, limit=10)
                        matched.extend(candidates)
                        if candidates:
                            break
            tcas_records = matched[:30] if matched else all_tcas[:10]
            used_tcas = bool(tcas_records)
        debug_info["tcas_records_found"] = len(tcas_records)

    # Work with only above-threshold chunks from here; fall back to raw list only if
    # nothing at all passed (so TCAS filename fallback still has something to work with).
    chunks = above_threshold if above_threshold else []

    # Filter course chunks from context only for TCAS queries (prevent prerequisite hallucination)
    if is_tcas_query:
        chunks = [c for c in chunks if c.get("section_type") != "course"] or chunks

    # Re-rank: boost chunks whose source file matches program keywords in the query.
    # Thai words run together so we use pythainlp to tokenize before matching.
    try:
        from pythainlp.tokenize import word_tokenize as _th_tokenize
        q_thai_tokens = [
            t for t in _th_tokenize(question, engine="newmm")
            if re.match(r"[ก-๙]{3,}", t)
        ]
    except Exception:
        q_thai_tokens = re.findall(r"[ก-๙]{4,}", question)

    if q_thai_tokens or is_plo_query:
        def _rank_score(chunk: dict) -> int:
            src = chunk.get("source_file", "")
            section = chunk.get("section_type", "")
            score = 0
            for w in q_thai_tokens:
                if w in src:
                    score += 10  # strong boost: query word appears in source filename
            if is_plo_query and section == "plo":
                score += 5   # PLO section preferred for PLO queries
            return score

        chunks = sorted(chunks, key=_rank_score, reverse=True)
        # If top chunk strongly matches a specific program, keep only chunks from that program
        if chunks and _rank_score(chunks[0]) >= 10:
            top_src = chunks[0].get("source_file", "")
            program_chunks = [c for c in chunks if c.get("source_file") == top_src]
            other_chunks = [c for c in chunks if c.get("source_file") != top_src]
            # Use program chunks first, pad with others only if needed
            chunks = (program_chunks + other_chunks)[:top_k]
        else:
            chunks = chunks[:top_k]

    debug_info["chunks_used"] = [
        {
            "source_file": c.get("source_file", ""),
            "section_type": c.get("section_type", ""),
            "similarity": round(c.get("similarity", 0.0), 3),
        }
        for c in chunks
    ]

    # 4. Assemble context
    context_parts: list[str] = []

    # For broad "what programs exist" queries, prepend the programs registry
    if is_listing_query:
        programs = db.get_programs(client)
        if programs:
            prog_lines = ["[KU Programs Available in Database]"]
            current_faculty = None
            for p in programs:
                fac = p.get("faculty") or "Unknown Faculty"
                if fac != current_faculty:
                    prog_lines.append(f"\nFaculty: {fac}")
                    current_faculty = fac
                name_th = p.get("name_th") or ""
                name_en = p.get("name_en") or ""
                degree = p.get("degree_level") or ""
                prog_lines.append(f"  - {name_th} / {name_en} ({degree})")
            context_parts.append("\n".join(prog_lines))
            debug_info["programs_injected"] = len(programs)

    for c in chunks:
        sim = round(c.get("similarity", 0.0), 3)
        context_parts.append(
            f"[{c['source_file']} | {c.get('section_type', 'general')} | similarity: {sim}]\n{c['content']}"
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

    return RAGResult(
        answer=answer,
        sources=sources,
        used_tcas_data=used_tcas,
        debug_info=debug_info if debug else None,
    )
