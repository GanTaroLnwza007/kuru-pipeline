"""PLO extractor — Gemini structured extraction → Neo4j graph population."""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import fitz
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from kuru.db import neo4j_client as neo4j
from kuru.ingestion.text_extractor import extract_text_auto, full_text, render_page_b64
from kuru.ingestion.utils import is_transient_error, safe_print
from kuru.llm import LLM_MODEL, get_client


# ─────────────────────────────────────────
# RIASEC → SkillCluster taxonomy (PoC hardcoded map)
# Each dimension maps to representative skill cluster names.
# ─────────────────────────────────────────

RIASEC_SKILLS: dict[str, list[str]] = {
    "R": ["Engineering & Technology", "Hands-on Technical Skills", "Physical Sciences"],
    "I": ["Research & Analysis", "Mathematics & Statistics", "Scientific Reasoning"],
    "A": ["Creative Design", "Communication & Expression", "Arts & Culture"],
    "S": ["Teaching & Education", "Social Services", "Human Relations"],
    "E": ["Leadership & Management", "Business & Entrepreneurship", "Project Management"],
    "C": ["Data & Information Management", "Accounting & Finance", "Process & Systems"],
}

# Keywords in PLO text → RIASEC dimension
PLO_RIASEC_KEYWORDS: list[tuple[str, str]] = [
    ("วิศวกรรม|เทคโนโลยี|ออกแบบระบบ|สร้าง|ผลิต|ทดสอบ", "R"),
    ("วิจัย|วิเคราะห์|คณิตศาสตร์|วิทยาศาสตร์|ทฤษฎี|สืบค้น", "I"),
    ("สร้างสรรค์|ออกแบบ|ศิลปะ|สื่อสาร|นำเสนอ|เขียน", "A"),
    ("สังคม|ช่วยเหลือ|บริการ|ทีม|ความร่วมมือ|สอน|พัฒนาชุมชน", "S"),
    ("บริหาร|จัดการ|ผู้นำ|ธุรกิจ|ริเริ่ม|ตัดสินใจ", "E"),
    ("ข้อมูล|บัญชี|การเงิน|ระบบ|ขั้นตอน|มาตรฐาน|จัดระเบียบ", "C"),
]


def _infer_riasec(plo_text: str) -> str:
    """Infer dominant RIASEC dimension from PLO text keywords."""
    for pattern, dim in PLO_RIASEC_KEYWORDS:
        if re.search(pattern, plo_text, re.IGNORECASE):
            return dim
    return "I"  # default: Investigative


def _riasec_to_skill_clusters(dim: str) -> list[dict[str, str]]:
    skills = RIASEC_SKILLS.get(dim, RIASEC_SKILLS["I"])
    return [{"name": s, "riasec_dim": dim} for s in skills[:2]]  # top 2 per PLO


# ─────────────────────────────────────────
# Pydantic schema
# ─────────────────────────────────────────

class PLOItem(BaseModel):
    plo_id: str = Field(description="PLO identifier, e.g. 'PLO1'")
    plo_text: str = Field(description="Full PLO text in Thai")
    skill_clusters: list[dict[str, str]] = Field(default_factory=list)


class PLOExtractionResult(BaseModel):
    faculty_id: str
    faculty_name_th: str
    plos: list[PLOItem]


class CoursePLOMapping(BaseModel):
    course_code: str
    course_name: str
    plo_mapping: list[dict[str, str]]  # [{"plo_id": "PLO1", "level": "X" | "X*"}]


EXTRACTION_PROMPT = """You are extracting Program Learning Outcomes (PLOs) from a Thai university curriculum document (มคอ.2).

Extract ALL PLOs listed in the document. For each PLO provide:
- plo_id: identifier like "PLO1", "PLO2", or the Thai numbering used
- plo_text: the complete PLO statement in Thai exactly as written

Also extract:
- faculty_name_th: the program/faculty name in Thai

Return a JSON object with keys:
  "faculty_name_th": string,
  "plos": array of {{ "plo_id": string, "plo_text": string }}

Output ONLY valid JSON.

Document text (first 30,000 characters):
{text}
"""


# ─────────────────────────────────────────
# Image-based table extraction
# ─────────────────────────────────────────

_TABLE_EXTRACT_PROMPT = """Look at this Thai university curriculum document page (มคอ.2).

If this page contains a table called "ตารางผลลัพธ์การเรียนรู้ระดับรายวิชา"
(a matrix mapping courses/รายวิชา to program learning outcomes/PLOs),
extract ALL visible rows as JSON:

{
  "has_table": true,
  "rows": [
    {
      "course_code": "01004653",
      "course_name": "จริยธรรมการวิจัย",
      "plo_mapping": [
        {"plo_id": "PLO1", "level": "X"},
        {"plo_id": "PLO2", "level": "X*"}
      ]
    }
  ]
}

Rules:
- "X" = the course addresses this PLO
- "X*" = this PLO is a primary/emphasized outcome (asterisk variant — preserve the distinction)
- Only include PLO entries where the cell contains X or X*
- If the table continues from a previous page, extract only what is visible on this page

If this page does NOT contain this table, return exactly: {"has_table": false}
Output ONLY valid JSON, no explanation."""

_TABLE_SCAN_WORKERS = 4  # parallel page scans


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=15, max=120), retry=retry_if_exception(is_transient_error), reraise=True)
def _extract_table_from_page(page_b64: str) -> dict:
    """Send a single page image to the vision model and extract table JSON."""
    response = get_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{page_b64}"}},
            {"type": "text", "text": _TABLE_EXTRACT_PROMPT},
        ]}],
        temperature=0.0,
    )
    raw = response.choices[0].message.content or '{"has_table": false}'
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {"has_table": False}


def extract_plo_course_table(
    pdf_path: str | Path,
    program_id: str,
    verbose: bool = False,
) -> list[CoursePLOMapping]:
    """Scan every PDF page for ตารางผลลัพธ์การเรียนรู้ระดับรายวิชา and extract as structured data.

    Sends each page image to the vision model. Pages without the table return quickly.
    Runs page scans in parallel for speed.
    """
    pdf_path = Path(pdf_path)
    doc = fitz.open(str(pdf_path))
    n_pages = len(doc)
    doc.close()

    if verbose:
        safe_print(f"  Scanning {n_pages} pages for CLO table …")

    def scan_page(page_num: int) -> tuple[int, dict]:
        b64 = render_page_b64(pdf_path, page_num, dpi=150)
        result = _extract_table_from_page(b64)
        return page_num, result

    all_rows: list[CoursePLOMapping] = []
    with ThreadPoolExecutor(max_workers=_TABLE_SCAN_WORKERS) as pool:
        futures = {pool.submit(scan_page, i): i for i in range(n_pages)}
        for future in as_completed(futures):
            page_num, data = future.result()
            if not data.get("has_table"):
                continue
            if verbose:
                safe_print(f"  ✓ CLO table found on page {page_num + 1}")
            for row in data.get("rows", []):
                try:
                    all_rows.append(CoursePLOMapping(
                        course_code=row.get("course_code", ""),
                        course_name=row.get("course_name", ""),
                        plo_mapping=row.get("plo_mapping", []),
                    ))
                except Exception:
                    pass

    if verbose:
        safe_print(f"  Extracted {len(all_rows)} course–PLO mappings.")
    return all_rows


def store_plo_course_mappings(program_id: str, mappings: list[CoursePLOMapping]) -> None:
    """Write course–PLO mapping edges to Neo4j."""
    neo4j.ingest_plo_course_mappings(
        faculty_id=program_id,
        mappings=[m.model_dump() for m in mappings],
    )


# ─────────────────────────────────────────
# Text-based PLO extraction (existing)
# ─────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=15, max=120), retry=retry_if_exception(is_transient_error), reraise=True)
def _call_llm(text: str) -> str:
    response = get_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT.replace("{text}", text[:200000])}],
        temperature=0.0,
    )
    return response.choices[0].message.content or "{}"


def extract_plos_from_pdf(
    pdf_path: str | Path,
    program_id: str,
    verbose: bool = False,
) -> PLOExtractionResult | None:
    """Extract PLOs from a มคอ.2 PDF and return a structured result."""
    pdf_path = Path(pdf_path)
    if verbose:
        safe_print(f"Extracting PLOs from {pdf_path.name} …")

    pages = extract_text_auto(pdf_path, use_vision_fallback=True, verbose=verbose)
    doc_text = full_text(pages)

    raw_json = _call_llm(doc_text)
    cleaned = re.sub(r"```(?:json)?|```", "", raw_json).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        safe_print(f"  Failed to parse PLO JSON: {exc}")
        return None

    plos_raw = data.get("plos", [])
    plos: list[PLOItem] = []
    for p in plos_raw:
        dim = _infer_riasec(p.get("plo_text", ""))
        skill_clusters = _riasec_to_skill_clusters(dim)
        plos.append(PLOItem(
            plo_id=f"{program_id}_{p.get('plo_id', 'PLO?')}",
            plo_text=p.get("plo_text", ""),
            skill_clusters=skill_clusters,
        ))

    if verbose:
        print(f"  Found {len(plos)} PLOs.")

    return PLOExtractionResult(
        faculty_id=program_id,
        faculty_name_th=data.get("faculty_name_th", program_id),
        plos=plos,
    )


def store_plos_to_neo4j(result: PLOExtractionResult) -> None:
    """Write PLO extraction result to Neo4j graph."""
    neo4j.ingest_program_plos(
        faculty_id=result.faculty_id,
        faculty_name_th=result.faculty_name_th,
        plos=[p.model_dump() for p in result.plos],
    )
