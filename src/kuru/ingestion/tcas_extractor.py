"""TCAS structured data extractor — Gemini → TCASRecord JSON → Supabase."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from kuru.db import supabase_client as db
from kuru.ingestion.text_extractor import extract_text, full_text

load_dotenv()
def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (TypeError, ValueError, AttributeError, UnicodeError)):
        return False
    return any(c in str(exc) for c in ("429", "500", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE"))


_client: genai.Client | None = None

def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client

GEMINI_MODEL = "gemini-2.0-flash"


# ─────────────────────────────────────────
# Schema
# ─────────────────────────────────────────

class TCASRecord(BaseModel):
    program_name_raw: str = Field(description="Program name as extracted from the PDF")
    faculty: str = Field(default="")
    round: str = Field(description="TCAS round: 'round1' | 'round2' | 'round3' | 'round4'")
    quota: int | None = Field(default=None)
    gpax_min: float | None = Field(default=None)
    exam_criteria: dict[str, Any] = Field(default_factory=dict)
    portfolio_requirements: dict[str, Any] = Field(default_factory=dict)
    deadlines: dict[str, Any] = Field(default_factory=dict)


EXTRACTION_PROMPT = """You are a structured data extractor for Thai university admission documents.

Extract ALL program admission records from the following TCAS document text.
Return a JSON array where each element is an admission record with these fields:
- program_name_raw: exact program name in Thai as written in the document
- faculty: faculty/department name
- round: "round1", "round2", "round3", or "round4"
- quota: number of available seats (integer, null if not found)
- gpax_min: minimum GPAX requirement (float, null if not found)
- exam_criteria: object with exam names as keys, e.g. {"TGAT": {"weight": 0.3}, "TPAT3": {"weight": 0.7}}
- portfolio_requirements: object describing portfolio items required
- deadlines: object with date keys, e.g. {"apply_start": "2025-10-01", "apply_end": "2025-10-10"}

Output ONLY valid JSON — no markdown fences, no commentary.

Document text:
{text}
"""


# ─────────────────────────────────────────
# Extraction
# ─────────────────────────────────────────

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=15, max=120), retry=retry_if_exception(_is_transient), reraise=True)
def _call_gemini(text: str) -> str:
    response = _get_client().models.generate_content(
        model=GEMINI_MODEL,
        contents=EXTRACTION_PROMPT.format(text=text[:40000]),
        config=types.GenerateContentConfig(
            temperature=0.0,
            response_mime_type="application/json",
        ),
    )
    return response.text or "[]"


def _parse_records(raw_json: str) -> list[dict[str, Any]]:
    # Strip markdown fences if Gemini ignores the mime_type instruction
    cleaned = re.sub(r"```(?:json)?|```", "", raw_json).strip()
    data = json.loads(cleaned)
    if isinstance(data, dict):
        # Sometimes Gemini wraps in {"records": [...]}
        data = data.get("records", data.get("data", [data]))
    return data if isinstance(data, list) else []


def extract_tcas_from_pdf(
    pdf_path: str | Path,
    verbose: bool = False,
) -> list[TCASRecord]:
    """Extract structured TCAS records from a PDF file."""
    pdf_path = Path(pdf_path)
    if verbose:
        print(f"Extracting text from {pdf_path.name} …")

    pages = extract_text(pdf_path, use_vision_fallback=True, verbose=verbose)
    doc_text = full_text(pages)

    if verbose:
        print(f"  Extracted {len(doc_text)} chars. Calling Gemini for structured extraction …")

    raw_json = _call_gemini(doc_text)
    raw_records = _parse_records(raw_json)

    records: list[TCASRecord] = []
    for r in raw_records:
        try:
            records.append(TCASRecord(**r))
        except Exception as exc:
            print(f"  Warning: skipping malformed record — {exc}: {r}")

    if verbose:
        print(f"  Extracted {len(records)} TCAS records.")

    return records


def store_tcas_records(
    records: list[TCASRecord],
    source_file: str,
) -> None:
    """Upsert TCASRecord objects to Supabase."""
    client = db.get_client()
    rows = [
        {**r.model_dump(), "source_file": source_file}
        for r in records
    ]
    db.upsert_tcas_records(client, rows)
