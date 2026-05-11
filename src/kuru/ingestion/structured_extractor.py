"""Gemini text-mode structured extraction — PLOs, courses, timeline, overview.

One cheap LLM call per document (~$0.002 at flash-lite pricing). No vision, no OCR.
Input: plain text from PyMuPDF. Output: typed StructuredProgram dataclass.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from kuru.ingestion.utils import safe_print
from kuru.llm import LLM_MODEL, get_client

# Truncate input text to this many chars to stay within context limits.
_MAX_TEXT_CHARS = 60_000

_EXTRACTION_PROMPT = """\
You are extracting structured data from a Thai university curriculum document (มคอ.2).
Return ONLY valid JSON — no markdown fences, no commentary, nothing else.

Extract these fields:
{{
  "overview": "<program overview paragraph in Thai, empty string if not found>",
  "plos": [
    {{"id": "PLO1", "description": "<Thai description>", "category": "<ethics|knowledge|intellectual|interpersonal|technology|other>"}}
  ],
  "courses": [
    {{"code": "<course code e.g. 01204111>", "name_th": "<Thai course name>", "credits": <integer>, "year": <integer 1-6>, "semester": <integer 1-3>}}
  ],
  "year_timeline": [
    {{"year": <integer>, "narrative": "<what students experience this year, in Thai>", "course_codes": ["<code>", ...]}}
  ],
  "curriculum_mapping": [
    {{"course_code": "<code>", "plo_primary": ["PLO1", ...], "plo_secondary": ["PLO2", ...]}}
  ]
}}

Rules:
- Return [] for missing arrays, "" for missing strings. Never return null.
- curriculum_mapping: filled bullet ● = plo_primary; open bullet ○ = plo_secondary.
- Extract ALL items — do not truncate lists.
- credits, year, semester must be integers.
- If year/semester for a course cannot be determined, use 0.

Document text (may be truncated):
{text}
"""


@dataclass
class StructuredProgram:
    overview: str = ""
    plos: list[dict] = field(default_factory=list)
    courses: list[dict] = field(default_factory=list)
    year_timeline: list[dict] = field(default_factory=list)
    curriculum_mapping: list[dict] = field(default_factory=list)


def _parse_response(content: str) -> StructuredProgram:
    """Parse Gemini JSON response into StructuredProgram. Returns empty on failure."""
    try:
        # Strip markdown fences if the model added them despite instructions
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.MULTILINE)
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return StructuredProgram()

    return StructuredProgram(
        overview=str(data.get("overview") or ""),
        plos=list(data.get("plos") or []),
        courses=list(data.get("courses") or []),
        year_timeline=list(data.get("year_timeline") or []),
        curriculum_mapping=list(data.get("curriculum_mapping") or []),
    )


def extract_structured(doc_text: str, verbose: bool = False) -> StructuredProgram:
    """Call Gemini in text mode and return structured program data.

    Args:
        doc_text: Full plain text extracted from the PDF.
        verbose: Print token/cost info if True.

    Returns:
        StructuredProgram with all fields populated or empty defaults.
    """
    text = doc_text[:_MAX_TEXT_CHARS]
    prompt = _EXTRACTION_PROMPT.format(text=text)

    try:
        client = get_client()
        response = client.chat.completions.create(
            model=LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        if not response.choices:
            safe_print("  [structured] Gemini returned no choices")
            return StructuredProgram()

        content = response.choices[0].message.content or ""
        result = _parse_response(content)

        if verbose:
            safe_print(
                f"  [structured] PLOs={len(result.plos)} courses={len(result.courses)} "
                f"timeline={len(result.year_timeline)} mapping={len(result.curriculum_mapping)}"
            )
        return result

    except Exception as exc:
        safe_print(f"  [structured] extraction failed ({type(exc).__name__}): {exc}")
        return StructuredProgram()
