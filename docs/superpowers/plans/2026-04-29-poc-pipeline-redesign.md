# PoC Pipeline Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the ingest pipeline to use native PDFs from Google Drive with zero OCR cost, extract structured program data (PLOs, courses, timelines) into Supabase JSONB, and provide a coverage report so the frontend team can see what data is available.

**Architecture:** PyMuPDF extracts text from native PDFs for free; a new `structured_extractor.py` calls Gemini in text mode to produce typed JSONB (PLOs, courses, year timeline, curriculum mapping, overview) stored on the `programs` table. OCR code is moved to an isolated `ocr_extractor.py` — preserved but never called during normal ingest. Per-page Typhoon OCR fires only for low-yield pages (< 50 chars) inside otherwise-native PDFs.

**Tech Stack:** Python 3.11+, PyMuPDF (fitz), google-genai SDK, Supabase + psycopg2, gdown, openai (Typhoon), pytest

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `db/schema.sql` | Modify | Add 6 new JSONB/TEXT columns to `programs` table |
| `data/native/curriculum/` | Create (dirs) | Home for native PDFs from Google Drive |
| `data/native/tcas/` | Create (dirs) | Home for native TCAS PDFs |
| `data/program_name_mapping.csv` | Create | Manual Thai ↔ English name registry |
| `src/kuru/ingestion/utils.py` | Modify | Add `png_dimensions()` helper |
| `src/kuru/ingestion/ocr_extractor.py` | Create | All OCR functions (isolated, not called by default) |
| `src/kuru/ingestion/text_extractor.py` | Modify | Remove OCR fallback; add per-page Typhoon; import from ocr_extractor |
| `src/kuru/ingestion/structured_extractor.py` | Create | Gemini text-mode structured extraction |
| `src/kuru/scripts/download_data.py` | Modify | Add PDF-redirect detection (single file + folder) |
| `src/kuru/scripts/ingest_curriculum.py` | Modify | Point to `data/native/`, wire structured extractor, write coverage |
| `src/kuru/scripts/setup_db.py` | Modify | Apply updated schema.sql |
| `src/kuru/scripts/coverage_report.py` | Create | `kuru-coverage` CLI |
| `pyproject.toml` | Modify | Add `kuru-coverage` entrypoint |
| `tests/test_structured_extractor.py` | Create | Unit tests for structured extractor |
| `tests/test_text_extractor.py` | Create | Unit tests for per-page Typhoon routing + scanned detection |

---

## Task 1: Schema + Directories + Name Mapping

**Files:**
- Modify: `db/schema.sql`
- Create: `data/native/curriculum/.gitkeep`, `data/native/tcas/.gitkeep`
- Create: `data/program_name_mapping.csv`

- [ ] **Step 1.1: Add new columns to schema.sql**

Open `db/schema.sql`. After the closing `);` of the `create table if not exists programs` block (line 17), add the new columns inside the CREATE TABLE (replace the existing programs table definition):

```sql
create table if not exists programs (
  id                  text primary key,
  name_th             text,
  name_en             text,
  faculty             text,
  degree_level        text default 'bachelor',
  overview            text,
  plos                jsonb default '[]',
  courses             jsonb default '[]',
  year_timeline       jsonb default '[]',
  curriculum_mapping  jsonb default '[]',
  coverage            jsonb default '{}',
  created_at          timestamptz default now()
);
```

Also add these `ALTER TABLE` statements near the bottom of the file, before the `match_chunks` function, so re-running on an existing DB (non-empty) still works:

```sql
-- Idempotent column additions for upgrades
alter table programs add column if not exists overview            text;
alter table programs add column if not exists plos               jsonb default '[]';
alter table programs add column if not exists courses            jsonb default '[]';
alter table programs add column if not exists year_timeline      jsonb default '[]';
alter table programs add column if not exists curriculum_mapping jsonb default '[]';
alter table programs add column if not exists coverage           jsonb default '{}';
```

- [ ] **Step 1.2: Create native data directories**

```bash
mkdir -p data/native/curriculum data/native/tcas
touch data/native/curriculum/.gitkeep data/native/tcas/.gitkeep
```

- [ ] **Step 1.3: Create name mapping CSV**

Create `data/program_name_mapping.csv`:

```csv
program_id,name_th_canonical,name_en
```

(Headers only — fill rows incrementally as you find the data.)

- [ ] **Step 1.4: Run setup-db and verify columns exist**

```bash
uv run kuru-setup-db
```

Expected output contains: `Supabase schema applied successfully.`

Then verify in Supabase dashboard (Table Editor → programs) that columns `plos`, `courses`, `year_timeline`, `curriculum_mapping`, `coverage`, `overview` are present with JSONB type.

- [ ] **Step 1.5: Commit**

```bash
git add db/schema.sql data/native/ data/program_name_mapping.csv
git commit -m "feat: add structured program columns to schema and native data dirs"
```

---

## Task 2: OCR Isolation — Create ocr_extractor.py

**Files:**
- Modify: `src/kuru/ingestion/utils.py`
- Create: `src/kuru/ingestion/ocr_extractor.py`

- [ ] **Step 2.1: Add `png_dimensions` to utils.py**

Open `src/kuru/ingestion/utils.py` and append:

```python
import base64
import struct


def png_dimensions(b64: str) -> tuple[int, int]:
    """Extract width, height from a base64 PNG without full decode (reads 24 bytes)."""
    raw = base64.b64decode(b64[:64])
    w = struct.unpack(">I", raw[16:20])[0]
    h = struct.unpack(">I", raw[20:24])[0]
    return w, h
```

- [ ] **Step 2.2: Create ocr_extractor.py with all moved OCR code**

Create `src/kuru/ingestion/ocr_extractor.py`:

```python
"""Bulk OCR pipeline — Gemini vision and Tesseract fallback for scanned PDFs.

This module is intentionally isolated. It is NOT imported by the native PDF
pipeline. To re-enable scanned PDF support, import extract_with_ocr from here
and call it from text_extractor.extract_text().
"""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from kuru.ingestion.utils import is_transient_error, png_dimensions, safe_print
from kuru.llm import OCR_MODEL, get_gemini_client, get_ocr_client

_PDF_EXTRACT_PROMPT = (
    "Extract all text from these PDF page images. "
    "Preserve Thai text exactly as written. "
    "Output only the extracted text with no commentary."
)

_OCR_DPI = 96
_OCR_BATCH_SIZE = 1 if OCR_MODEL.startswith("typhoon") else 4
_OCR_WORKERS = 2


def _is_garbage_line(line: str) -> bool:
    """Return True for OCR hallucination lines — a single character repeated."""
    chars = [c for c in line if not c.isspace()]
    if len(chars) < 10:
        return False
    dominant = max(set(chars), key=chars.count)
    return chars.count(dominant) / len(chars) > 0.85


def _dedup_lines(text: str) -> str:
    """Remove consecutive duplicate lines and OCR hallucination lines."""
    lines = text.splitlines()
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and _is_garbage_line(stripped):
            continue
        if not result or stripped != result[-1].strip():
            result.append(line)
    return "\n".join(result)


@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=30, max=300),
    retry=retry_if_exception(is_transient_error),
    reraise=True,
)
def _ocr_batch(images_b64: list[str]) -> str:
    if OCR_MODEL.startswith("typhoon"):
        return _ocr_batch_typhoon(images_b64)
    return _ocr_batch_gemini(images_b64)


def _ocr_batch_gemini(images_b64: list[str]) -> str:
    from google import genai  # noqa: PLC0415
    from google.genai import types  # noqa: PLC0415

    parts = [
        types.Part.from_bytes(data=base64.b64decode(b64), mime_type="image/png")
        for b64 in images_b64
    ]
    parts.append(types.Part.from_text(text=_PDF_EXTRACT_PROMPT))
    response = get_gemini_client().models.generate_content(
        model=OCR_MODEL,
        contents=parts,
        config=types.GenerateContentConfig(
            temperature=0.0,
            thinking_config=types.ThinkingConfig(thinking_budget=0),
        ),
    )
    return response.text or ""


def _ocr_batch_typhoon(images_b64: list[str]) -> str:
    b64 = images_b64[0]
    w, h = png_dimensions(b64)
    prompt = (
        f"Below is an image of a document page along with its dimensions. "
        f"The image dimensions are {w}x{h} pixels. "
        "Extract all text from this page. Preserve Thai text exactly as written. "
        "Output only the extracted text with no commentary."
    )
    response = get_ocr_client().chat.completions.create(
        model=OCR_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
        ]}],
        temperature=0.1,
        max_tokens=16384,
        top_p=0.6,
        extra_body={"repetition_penalty": 1.2},
    )
    if not response.choices:
        return ""
    return response.choices[0].message.content or ""


def _extract_with_vision(pdf_path: Path, verbose: bool = False) -> str:
    import fitz  # noqa: PLC0415

    if verbose:
        safe_print(f"  Rendering {pdf_path.name} for vision OCR …")

    doc = fitz.open(str(pdf_path))
    pages_b64 = [
        base64.b64encode(page.get_pixmap(dpi=_OCR_DPI).tobytes("png")).decode()
        for page in doc
    ]
    doc.close()

    batches = [
        (i, pages_b64[i : i + _OCR_BATCH_SIZE])
        for i in range(0, len(pages_b64), _OCR_BATCH_SIZE)
    ]
    total_pages = len(pages_b64)

    results: dict[int, str] = {}
    with ThreadPoolExecutor(max_workers=_OCR_WORKERS) as pool:
        futures = {pool.submit(_ocr_batch, batch): idx for idx, batch in batches}
        for future in as_completed(futures):
            idx = futures[future]
            start_page = idx + 1
            end_page = min(idx + _OCR_BATCH_SIZE, total_pages)
            results[idx] = _dedup_lines(future.result())
            if verbose:
                safe_print(f"  ✓ pages {start_page}–{end_page}")

    seen_batch_texts: set[str] = set()
    for idx in sorted(results.keys()):
        normalized = results[idx].strip()
        if normalized in seen_batch_texts:
            results[idx] = ""
        elif normalized:
            seen_batch_texts.add(normalized)

    return "\n\n".join(results[i] for i, _ in batches if results.get(i, "").strip())


def _extract_with_tesseract(pdf_path: Path, verbose: bool = False) -> str:
    try:
        import pytesseract
        from PIL import Image  # noqa: PLC0415
    except ImportError:
        safe_print("  [tesseract] pytesseract not installed — skipping (uv add pytesseract)")
        return ""

    if verbose:
        safe_print(f"  [tesseract] Falling back to Tesseract for {pdf_path.name} …")

    try:
        import fitz  # noqa: PLC0415

        doc = fitz.open(str(pdf_path))
        parts: list[str] = []
        for i, page in enumerate(doc):
            pix = page.get_pixmap(dpi=_OCR_DPI)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
            text = pytesseract.image_to_string(img, lang="tha+eng", timeout=60)
            text = _dedup_lines(text)
            if text.strip():
                parts.append(text)
            if verbose:
                safe_print(f"  [tesseract] ✓ page {i + 1}/{len(doc)}")
        doc.close()
        return "\n\n".join(parts)
    except Exception as exc:
        safe_print(f"  [tesseract] failed ({type(exc).__name__}): {exc}")
        return ""


def extract_with_ocr(pdf_path: Path, verbose: bool = False) -> str:
    """Public entry point — full scanned-PDF OCR with Gemini vision + Tesseract fallback.

    To re-enable in text_extractor.py:
        from kuru.ingestion.ocr_extractor import extract_with_ocr
        # then call extract_with_ocr(pdf_path, verbose=verbose) in extract_text()
    """
    text = _extract_with_vision(pdf_path, verbose=verbose)
    if len(text.strip()) < 500:
        if verbose:
            safe_print(f"  Vision OCR yielded only {len(text.strip())} chars — trying Tesseract")
        text = _extract_with_tesseract(pdf_path, verbose=verbose)
    return text
```

- [ ] **Step 2.3: Verify the module is importable**

```bash
uv run python -c "from kuru.ingestion.ocr_extractor import extract_with_ocr; print('OK')"
```

Expected: `OK`

- [ ] **Step 2.4: Commit**

```bash
git add src/kuru/ingestion/utils.py src/kuru/ingestion/ocr_extractor.py
git commit -m "feat: isolate OCR code into ocr_extractor.py"
```

---

## Task 3: Refactor text_extractor.py

**Files:**
- Modify: `src/kuru/ingestion/text_extractor.py`
- Create: `tests/test_text_extractor.py`

- [ ] **Step 3.1: Write failing tests first**

Create `tests/__init__.py` (empty) and `tests/test_text_extractor.py`:

```python
"""Tests for text_extractor — scanned detection and per-page Typhoon routing."""
import base64
import struct
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kuru.ingestion.text_extractor import (
    SCANNED_CHAR_THRESHOLD,
    _build_page_texts,
    _should_ocr_page,
)


def _make_b64_png(width: int = 100, height: int = 100) -> str:
    """Minimal valid PNG header as base64 for testing."""
    header = b"\x89PNG\r\n\x1a\n"
    ihdr_data = struct.pack(">II", width, height) + b"\x08\x02\x00\x00\x00"
    chunk = b"\x00\x00\x00\rIHDR" + ihdr_data + b"\x00\x00\x00\x00"
    return base64.b64encode(header + chunk).decode()


def test_should_ocr_page_true_when_low_yield():
    assert _should_ocr_page("   ") is True
    assert _should_ocr_page("ab") is True


def test_should_ocr_page_false_when_sufficient():
    assert _should_ocr_page("x" * 50) is False
    assert _should_ocr_page("สวัสดี " * 10) is False


def test_scanned_char_threshold_is_500():
    assert SCANNED_CHAR_THRESHOLD == 500
```

- [ ] **Step 3.2: Run tests — expect failures**

```bash
uv run pytest tests/test_text_extractor.py -v
```

Expected: `ImportError` or `FAILED` — `_build_page_texts` and `_should_ocr_page` don't exist yet.

- [ ] **Step 3.3: Rewrite text_extractor.py**

Replace the entire content of `src/kuru/ingestion/text_extractor.py` with:

```python
"""Text extractor — PyMuPDF for born-digital PDFs, per-page Typhoon for image pages.

Bulk OCR (for fully scanned PDFs) lives in ocr_extractor.py and is NOT called here.
To re-enable scanned OCR:
    from kuru.ingestion.ocr_extractor import extract_with_ocr
"""

from __future__ import annotations

import base64
import os
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from kuru.ingestion.utils import png_dimensions, safe_print

# If PyMuPDF extracts fewer than this many chars total, the PDF is treated as scanned.
SCANNED_CHAR_THRESHOLD = 500

# Pages with fewer than this many chars get routed to per-page Typhoon OCR.
_PAGE_LOW_YIELD_CHARS = 50

_PAGE_OCR_DPI = 96


@dataclass
class PageText:
    page_num: int
    text: str
    extraction_method: str  # 'pymupdf' | 'typhoon_page' | 'scanned' | 'python-docx' | 'failed'


# ─────────────────────────────────────────
# Internal helpers (exported for testing)
# ─────────────────────────────────────────

def _should_ocr_page(text: str) -> bool:
    """True when a page's extracted text is too short to be useful."""
    return len(text.strip()) < _PAGE_LOW_YIELD_CHARS


def _extract_page_typhoon(page_b64: str) -> str:
    """Send a single low-yield page to Typhoon OCR. Returns '' if unavailable."""
    if not os.environ.get("TYPHOON_API_KEY"):
        return ""
    try:
        from kuru.llm import get_ocr_client  # noqa: PLC0415

        w, h = png_dimensions(page_b64)
        prompt = (
            f"Below is an image of a document page. The image dimensions are {w}x{h} pixels. "
            "Extract all text from this page. Preserve Thai text exactly as written. "
            "Output only the extracted text with no commentary."
        )
        response = get_ocr_client().chat.completions.create(
            model="typhoon-ocr",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{page_b64}"}},
            ]}],
            temperature=0.1,
            max_tokens=4096,
            top_p=0.6,
            extra_body={"repetition_penalty": 1.2},
        )
        if not response.choices:
            return ""
        return response.choices[0].message.content or ""
    except Exception:
        return ""


def _build_page_texts(pdf_path: Path, verbose: bool = False) -> list[PageText]:
    """Extract text page-by-page. Low-yield pages are sent to per-page Typhoon."""
    doc = fitz.open(str(pdf_path))
    pages: list[PageText] = []

    for i, page in enumerate(doc):
        text = page.get_text("text")
        method = "pymupdf"

        if _should_ocr_page(text):
            b64 = base64.b64encode(
                page.get_pixmap(dpi=_PAGE_OCR_DPI).tobytes("png")
            ).decode()
            ocr_text = _extract_page_typhoon(b64)
            if ocr_text.strip():
                text = ocr_text
                method = "typhoon_page"
                if verbose:
                    safe_print(f"  [typhoon] ✓ page {i + 1} ({len(text)} chars)")

        pages.append(PageText(page_num=i, text=text, extraction_method=method))

    doc.close()
    return pages


# ─────────────────────────────────────────
# Public API
# ─────────────────────────────────────────

def extract_text(
    pdf_path: str | Path,
    use_vision_fallback: bool = True,  # kept for call-site compatibility, ignored
    verbose: bool = False,
) -> list[PageText]:
    """Extract text from a PDF using PyMuPDF + optional per-page Typhoon for image pages.

    If total extracted chars < SCANNED_CHAR_THRESHOLD, all pages are marked 'scanned'
    and no OCR is attempted. Re-enable full OCR by importing extract_with_ocr from
    kuru.ingestion.ocr_extractor.
    """
    pdf_path = Path(pdf_path)
    pages = _build_page_texts(pdf_path, verbose=verbose)
    total_chars = sum(len(p.text.strip()) for p in pages)

    if total_chars < SCANNED_CHAR_THRESHOLD:
        if verbose:
            safe_print(
                f"  Low text yield ({total_chars} chars) — marking as scanned. "
                "OCR disabled; import ocr_extractor.extract_with_ocr to re-enable."
            )
        for p in pages:
            p.extraction_method = "scanned"

    return pages


def render_page_b64(pdf_path: Path, page_num: int, dpi: int = 150) -> str:
    """Render a single PDF page to a base64 PNG string."""
    doc = fitz.open(str(pdf_path))
    pix = doc[page_num].get_pixmap(dpi=dpi)
    doc.close()
    return base64.b64encode(pix.tobytes("png")).decode()


def extract_text_from_docx(docx_path: Path) -> list[PageText]:
    """Extract text from a DOCX file using python-docx."""
    try:
        import docx  # python-docx  # noqa: PLC0415

        doc = docx.Document(str(docx_path))
        parts: list[str] = [p.text for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                row_cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
                if row_cells:
                    parts.append("\t".join(row_cells))
        return [PageText(page_num=0, text="\n".join(parts), extraction_method="python-docx")]
    except Exception as exc:
        safe_print(f"  DOCX extraction failed ({type(exc).__name__}): {exc}")
        return [PageText(page_num=0, text="", extraction_method="failed")]


def extract_text_auto(
    path: str | Path,
    use_vision_fallback: bool = True,
    verbose: bool = False,
) -> list[PageText]:
    """Dispatch to the right extractor based on file extension (.pdf or .docx)."""
    path = Path(path)
    if path.suffix.lower() == ".docx":
        return extract_text_from_docx(path)
    return extract_text(path, use_vision_fallback=use_vision_fallback, verbose=verbose)


def full_text(pages: list[PageText]) -> str:
    return "\n\n".join(p.text for p in pages if p.text.strip())
```

- [ ] **Step 3.4: Run tests — expect pass**

```bash
uv run pytest tests/test_text_extractor.py -v
```

Expected:
```
PASSED tests/test_text_extractor.py::test_should_ocr_page_true_when_low_yield
PASSED tests/test_text_extractor.py::test_should_ocr_page_false_when_sufficient
PASSED tests/test_text_extractor.py::test_scanned_char_threshold_is_500
```

- [ ] **Step 3.5: Verify OCR extractor still importable independently**

```bash
uv run python -c "from kuru.ingestion.ocr_extractor import extract_with_ocr; print('OCR isolated OK')"
uv run python -c "from kuru.ingestion.text_extractor import extract_text; print('text_extractor OK')"
```

Expected: both print OK.

- [ ] **Step 3.6: Commit**

```bash
git add src/kuru/ingestion/text_extractor.py tests/
git commit -m "feat: refactor text_extractor — disable OCR fallback, add per-page Typhoon"
```

---

## Task 4: Structured Extractor

**Files:**
- Create: `src/kuru/ingestion/structured_extractor.py`
- Create: `tests/test_structured_extractor.py`

- [ ] **Step 4.1: Write failing tests**

Create `tests/test_structured_extractor.py`:

```python
"""Tests for structured_extractor — JSON parsing and fallback behaviour."""
import json
from unittest.mock import MagicMock, patch

import pytest

from kuru.ingestion.structured_extractor import StructuredProgram, _parse_response


def _make_response(data: dict) -> MagicMock:
    mock = MagicMock()
    mock.choices = [MagicMock()]
    mock.choices[0].message.content = json.dumps(data)
    return mock


def test_parse_response_full():
    data = {
        "overview": "หลักสูตรวิศวกรรมคอมพิวเตอร์",
        "plos": [{"id": "PLO1", "description": "ด้านความรู้", "category": "knowledge"}],
        "courses": [{"code": "01204111", "name_th": "แคลคูลัส", "credits": 3, "year": 1, "semester": 1}],
        "year_timeline": [{"year": 1, "narrative": "ปีแรก", "course_codes": ["01204111"]}],
        "curriculum_mapping": [{"course_code": "01204111", "plo_primary": ["PLO1"], "plo_secondary": []}],
    }
    result = _parse_response(json.dumps(data))
    assert result.overview == "หลักสูตรวิศวกรรมคอมพิวเตอร์"
    assert len(result.plos) == 1
    assert result.plos[0]["id"] == "PLO1"
    assert len(result.courses) == 1
    assert result.courses[0]["code"] == "01204111"
    assert len(result.year_timeline) == 1
    assert len(result.curriculum_mapping) == 1


def test_parse_response_empty_sections():
    data = {"overview": "", "plos": [], "courses": [], "year_timeline": [], "curriculum_mapping": []}
    result = _parse_response(json.dumps(data))
    assert result.overview == ""
    assert result.plos == []
    assert result.courses == []


def test_parse_response_invalid_json_returns_empty():
    result = _parse_response("not json at all")
    assert isinstance(result, StructuredProgram)
    assert result.plos == []
    assert result.courses == []
    assert result.overview == ""


def test_parse_response_partial_json():
    data = {"overview": "บางส่วน"}  # missing plos, courses, etc.
    result = _parse_response(json.dumps(data))
    assert result.overview == "บางส่วน"
    assert result.plos == []
    assert result.courses == []


def test_extract_structured_calls_gemini():
    sample_text = "หลักสูตรวิทยาศาสตรบัณฑิต สาขาวิชาวิทยาการคอมพิวเตอร์"
    mock_content = json.dumps({
        "overview": sample_text,
        "plos": [],
        "courses": [],
        "year_timeline": [],
        "curriculum_mapping": [],
    })
    mock_response = MagicMock()
    mock_response.choices = [MagicMock()]
    mock_response.choices[0].message.content = mock_content

    with patch("kuru.ingestion.structured_extractor.get_client") as mock_get:
        mock_client = MagicMock()
        mock_get.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_response

        from kuru.ingestion.structured_extractor import extract_structured
        result = extract_structured(sample_text)

    assert result.overview == sample_text
    mock_client.chat.completions.create.assert_called_once()
```

- [ ] **Step 4.2: Run tests — expect failure**

```bash
uv run pytest tests/test_structured_extractor.py -v
```

Expected: `ImportError` — module doesn't exist yet.

- [ ] **Step 4.3: Create structured_extractor.py**

Create `src/kuru/ingestion/structured_extractor.py`:

```python
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
```

- [ ] **Step 4.4: Run tests — expect pass**

```bash
uv run pytest tests/test_structured_extractor.py -v
```

Expected:
```
PASSED tests/test_structured_extractor.py::test_parse_response_full
PASSED tests/test_structured_extractor.py::test_parse_response_empty_sections
PASSED tests/test_structured_extractor.py::test_parse_response_invalid_json_returns_empty
PASSED tests/test_structured_extractor.py::test_parse_response_partial_json
PASSED tests/test_structured_extractor.py::test_extract_structured_calls_gemini
```

- [ ] **Step 4.5: Commit**

```bash
git add src/kuru/ingestion/structured_extractor.py tests/test_structured_extractor.py
git commit -m "feat: add structured_extractor — Gemini text-mode PLO/course/timeline extraction"
```

---

## Task 5: PDF-Redirect Detection in download_data.py

**Files:**
- Modify: `src/kuru/scripts/download_data.py`

- [ ] **Step 5.1: Add imports and regex at top of download_data.py**

After the existing `_DRIVE_FOLDER_RE` line (line 22), add:

```python
_DRIVE_FILE_RE = re.compile(
    r"https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)"
)
_PDF_REDIRECT_MAX_CHARS = 200
```

- [ ] **Step 5.2: Add `_is_pdf_redirect` helper**

Add this function after `_retry_manual()`:

```python
def _is_pdf_redirect(pdf_path: Path) -> str | None:
    """Return the Drive URL if this PDF is a redirect notice, else None.

    A redirect PDF has < 200 chars of text and contains a drive.google.com URL.
    """
    try:
        import fitz  # noqa: PLC0415

        doc = fitz.open(str(pdf_path))
        text = "".join(page.get_text() for page in doc)
        doc.close()
        if len(text.strip()) > _PDF_REDIRECT_MAX_CHARS:
            return None
        m = _DRIVE_FOLDER_RE.search(text) or _DRIVE_FILE_RE.search(text)
        return m.group(0) if m else None
    except Exception:
        return None
```

- [ ] **Step 5.3: Add `_follow_pdf_redirects` function**

Add after `_is_pdf_redirect()`:

```python
def _follow_pdf_redirects(base_dir: str) -> None:
    """Scan all PDFs under base_dir for redirect notices and follow their Drive URLs.

    Handles two cases:
    - drive.google.com/file/d/<id>  → download single file into same directory
    - drive.google.com/drive/folders/<id> → download entire folder into same directory
    """
    base_path = Path(base_dir)
    pdfs = list(base_path.rglob("*.pdf"))
    if not pdfs:
        return

    redirects = [
        (p, url)
        for p in pdfs
        if (url := _is_pdf_redirect(p)) is not None
    ]
    if not redirects:
        return

    print(f"\nFound {len(redirects)} PDF redirect(s) — following Drive URLs …")
    for pdf_path, drive_url in redirects:
        output_dir = str(pdf_path.parent)
        print(f"  {pdf_path.name} → {drive_url}")
        folder_m = _DRIVE_FOLDER_RE.search(drive_url)
        file_m = _DRIVE_FILE_RE.search(drive_url)
        try:
            if folder_m:
                gdown.download_folder(
                    id=folder_m.group(1),
                    output=output_dir,
                    quiet=False,
                    use_cookies=False,
                )
            elif file_m:
                gdown.download(
                    id=file_m.group(1),
                    output=output_dir + "/",
                    quiet=False,
                    fuzzy=True,
                )
        except Exception as exc:
            print(f"  WARNING: redirect follow failed — {exc}")
```

- [ ] **Step 5.4: Update `main()` to download to native dirs and call redirect detection**

Replace the existing `main()` function with:

```python
def main() -> None:
    _download_folder(TCAS1_FOLDER_ID,      "data/native/tcas",      "TCAS PDFs + data")
    _download_folder(CURRICULUM_FOLDER_ID, "data/native/curriculum", "Curriculum (มคอ.2) — บางเขน + กพส")
    for output_dir, folder_id in EXTRA_CAMPUS_FOLDERS.items():
        campus = Path(output_dir).name
        _download_folder(folder_id, output_dir, f"Curriculum — {campus}")
    _retry_manual(MANUAL_RETRY)
    _follow_txt_redirects("data/native/curriculum")
    _follow_pdf_redirects("data/native/curriculum")

    tcas_count  = len(list(Path("data/native/tcas").rglob("*.pdf")))
    xlsx_count  = len(list(Path("data/native/tcas").rglob("*.xlsx")))
    curr_pdf    = len(list(Path("data/native/curriculum").rglob("*.pdf")))
    curr_docx   = len(list(Path("data/native/curriculum").rglob("*.docx")))
    print(
        f"\nDone.  TCAS: {tcas_count} PDF(s), {xlsx_count} xlsx   "
        f"Curriculum: {curr_pdf} PDF(s), {curr_docx} docx"
    )
```

Also update `EXTRA_CAMPUS_FOLDERS` comment to point to `data/native/curriculum/<campus>`:

```python
EXTRA_CAMPUS_FOLDERS: dict[str, str] = {
    # "data/native/curriculum/กำแพงแสน": "<KAMPHAENGSAEN_FOLDER_ID>",
    # "data/native/curriculum/ศรีราชา":   "<SRIRACHA_FOLDER_ID>",
}
```

And update `MANUAL_RETRY` to point to native dirs:

```python
MANUAL_RETRY: dict[str, str] = {
    "data/native/curriculum/บางเขน/วิศวฯ":  "1zy2vAAhxHd9qdFYZMYbxxCxAg2uIohlh",
    "data/native/curriculum/กพส/วิศว กพส":  "1Niev92NFiNylLFaa6XL3Mvu-aZJCmpcE",
    "data/native/tcas":                      "1cRaZi1XcPlq2BXuN9UGdgJfHqymJGV8h",
}
```

- [ ] **Step 5.5: Verify module imports cleanly**

```bash
uv run python -c "from kuru.scripts.download_data import _is_pdf_redirect, _follow_pdf_redirects; print('OK')"
```

Expected: `OK`

- [ ] **Step 5.6: Commit**

```bash
git add src/kuru/scripts/download_data.py
git commit -m "feat: add PDF-redirect detection (single file + folder) to download_data"
```

---

## Task 6: Wire Structured Extractor into ingest_curriculum.py

**Files:**
- Modify: `src/kuru/scripts/ingest_curriculum.py`
- Modify: `src/kuru/db/supabase_client.py`

- [ ] **Step 6.1: Add `update_program_structured` to supabase_client.py**

Open `src/kuru/db/supabase_client.py` and add after `upsert_program()`:

```python
def update_program_structured(client: Client, program_id: str, data: dict[str, Any]) -> None:
    """Update structured JSONB fields on an existing program record."""
    client.table("programs").update(data).eq("id", program_id).execute()
```

- [ ] **Step 6.2: Update imports in ingest_curriculum.py**

Replace the existing imports block at the top of `src/kuru/scripts/ingest_curriculum.py`:

```python
import csv
import hashlib
import math
import os
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from rich.console import Console

from kuru.db import supabase_client as db
from kuru.ingestion.chunker import chunk_document
from kuru.ingestion.embedder import embed_and_store, _get_model
from kuru.ingestion.structured_extractor import StructuredProgram, extract_structured
from kuru.ingestion.text_extractor import PageText, extract_text_auto, full_text

load_dotenv()
```

- [ ] **Step 6.3: Add name mapping loader and coverage builder**

Add these two functions after `_extract_name_en()` (around line 92 in the original):

```python
def _load_name_mapping() -> dict[str, dict]:
    """Load data/program_name_mapping.csv → {program_id: {name_en, name_th_canonical}}."""
    csv_path = Path("data/program_name_mapping.csv")
    if not csv_path.exists():
        return {}
    result: dict[str, dict] = {}
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[row["program_id"]] = {
                "name_en": row.get("name_en") or None,
                "name_th_canonical": row.get("name_th_canonical") or None,
            }
    return result


def _build_coverage(
    pages: list[PageText],
    structured: StructuredProgram,
    name_en_source: str | None,
) -> dict:
    total_pages = len(pages)
    scanned_pages = sum(1 for p in pages if p.extraction_method == "scanned")
    typhoon_pages = sum(1 for p in pages if p.extraction_method == "typhoon_page")

    if scanned_pages == total_pages and total_pages > 0:
        method = "scanned"
    elif typhoon_pages > 0:
        method = "pymupdf+typhoon_pages"
    else:
        method = "pymupdf"

    return {
        "extraction_method": method,
        "has_overview": bool(structured.overview),
        "has_plos": len(structured.plos) > 0,
        "plo_count": len(structured.plos),
        "has_courses": len(structured.courses) > 0,
        "course_count": len(structured.courses),
        "has_timeline": len(structured.year_timeline) > 0,
        "has_curriculum_mapping": len(structured.curriculum_mapping) > 0,
        "scanned_pages": scanned_pages,
        "total_pages": total_pages,
        "name_en_source": name_en_source,
    }
```

- [ ] **Step 6.4: Update ingest_document() to call structured extractor and write coverage**

Replace the `ingest_document()` function body. Find the section after the chunking/embedding block and add the structured extraction and coverage logic:

```python
def ingest_document(pdf_path: Path, campus: str, name_mapping: dict, verbose: bool = False) -> dict:
    """Full pipeline for one curriculum document (PDF or DOCX). Returns a status dict."""
    program_id = _program_id_from_path(pdf_path, campus)
    status = {
        "file": pdf_path.name,
        "campus": campus,
        "program_id": program_id,
        "chunks": 0,
        "skipped": False,
        "errors": [],
    }

    client = db.get_client()

    name_th = _program_name_from_stem(pdf_path.stem)

    # Resolve English name: CSV mapping first, then auto-extract later
    mapping = name_mapping.get(program_id, {})
    name_en_from_csv = mapping.get("name_en")
    name_en_source: str | None = "csv_mapping" if name_en_from_csv else None

    db.upsert_program(client, {
        "id": program_id,
        "name_th": name_th,
        "name_en": name_en_from_csv,
        "faculty": campus,
        "degree_level": _degree_level(pdf_path.stem),
    })

    existing = db.count_chunks(client, pdf_path.name)
    if existing > 0:
        status["chunks"] = existing
        status["skipped"] = True
        return status

    # ── Text extraction ─────────────────────────────────────────────────────
    try:
        pages = extract_text_auto(pdf_path, use_vision_fallback=True, verbose=verbose)
        doc_text = full_text(pages)
    except Exception as exc:
        status["errors"].append(f"text extraction ({type(exc).__name__}): {exc}")
        return status

    # Backfill English name from PDF text if CSV had nothing
    if not name_en_from_csv:
        name_en_auto = _extract_name_en(doc_text)
        if name_en_auto:
            db.upsert_program(client, {"id": program_id, "name_en": name_en_auto})
            name_en_source = "auto_extracted"

    # ── Scanned PDF — write partial record and stop ─────────────────────────
    all_scanned = all(p.extraction_method == "scanned" for p in pages)
    if all_scanned:
        coverage = _build_coverage(pages, StructuredProgram(), name_en_source)
        db.update_program_structured(client, program_id, {"coverage": coverage})
        status["errors"].append("scanned PDF — no native text, OCR disabled")
        return status

    # ── Curriculum check ────────────────────────────────────────────────────
    if not _is_curriculum_doc(doc_text):
        status["skipped"] = True
        status["errors"].append("not a curriculum doc (no มคอ.2 markers) — skipped")
        return status

    # ── Chunking + Embedding ────────────────────────────────────────────────
    chunks = chunk_document(doc_text)
    if not chunks:
        status["errors"].append("no chunks produced — PDF may be image-only or empty")
        return status

    try:
        stored = embed_and_store(
            chunks, program_id=program_id, source_file=pdf_path.name, verbose=verbose
        )
        status["chunks"] = stored
    except Exception as exc:
        status["errors"].append(f"embedding ({type(exc).__name__}): {exc}")

    # ── Structured extraction ───────────────────────────────────────────────
    structured = extract_structured(doc_text, verbose=verbose)
    coverage = _build_coverage(pages, structured, name_en_source)

    db.update_program_structured(client, program_id, {
        "overview": structured.overview or None,
        "plos": structured.plos,
        "courses": structured.courses,
        "year_timeline": structured.year_timeline,
        "curriculum_mapping": structured.curriculum_mapping,
        "coverage": coverage,
    })

    return status
```

- [ ] **Step 6.5: Update main() to load name mapping and pass it + point to native dir**

In `main()`, update the `base_dir` and pass `name_mapping` to threads:

```python
def main(campus: str | None = None, sample: int | None = None) -> None:
    args = sys.argv[1:]
    if campus is None:
        campus = next((a for a in args if not a.startswith("--")), DEFAULT_CAMPUS)
    if sample is None:
        for a in args:
            if a.startswith("--sample="):
                sample = int(a.split("=", 1)[1])
            elif a == "--sample" and args.index(a) + 1 < len(args):
                sample = int(args[args.index(a) + 1])

    base_dir = Path("data/native/curriculum")      # ← changed from data/raw/curriculum
    if not base_dir.exists():
        console.print("[red]data/native/curriculum/ not found. Run kuru-download first.[/red]")
        sys.exit(1)

    name_mapping = _load_name_mapping()
    console.print(f"[dim]Loaded {len(name_mapping)} name mapping(s) from CSV[/dim]")

    docs = find_documents(base_dir, campus)
    if not docs:
        console.print(f"[yellow]No documents found for campus '{campus}' under {base_dir}[/yellow]")
        sys.exit(0)

    campus_dir = base_dir / campus
    if sample and sample < len(docs):
        docs = sample_documents(docs, sample, campus_dir)

    console.print(f"\n[bold]Campus:[/bold] [cyan]{campus}[/cyan]")
    console.print(f"[bold]Processing {len(docs)} document(s) …[/bold]\n")

    console.print("[dim]Loading embedding model …[/dim]")
    _get_model()

    results = []
    completed = 0
    console.print(f"[dim]Running {FILE_WORKERS} files in parallel …[/dim]\n")

    _start = time.time()
    _stop_heartbeat = threading.Event()

    def _heartbeat():
        while not _stop_heartbeat.wait(30):
            elapsed = int(time.time() - _start)
            m, s = divmod(elapsed, 60)
            console.print(f"  [dim]... {m:02d}:{s:02d} elapsed, {completed}/{len(docs)} done[/dim]")

    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()

    pool = ThreadPoolExecutor(max_workers=FILE_WORKERS)
    futures = {pool.submit(ingest_document, pdf, campus, name_mapping, False): pdf for pdf in docs}
    try:
        for future in as_completed(futures):
            status = future.result()
            results.append(status)
            completed += 1
            tag = "[dim]skip[/dim]" if status["skipped"] else (
                "[red]FAIL[/red]" if status["errors"] else "[green]✓[/green]"
            )
            console.print(
                f"  {tag} [{completed}/{len(docs)}] {status['file'][:55]}"
                + (f" → chunks={status['chunks']}" if not status["skipped"] else "")
            )
    except KeyboardInterrupt:
        _stop_heartbeat.set()
        console.print("\n[yellow]Interrupted — cancelling queued files …[/yellow]")
        for f in futures:
            f.cancel()
        pool.shutdown(wait=False)
        console.print(f"[yellow]Stopped at {completed}/{len(docs)} files.[/yellow]")
        import os; os._exit(0)

    _stop_heartbeat.set()

    skipped = [r for r in results if r["skipped"]]
    done    = [r for r in results if not r["skipped"] and not r["errors"]]
    failed  = [r for r in results if not r["skipped"] and r["errors"]]

    console.print("\n[bold]Ingestion Summary[/bold]")
    if skipped:
        console.print(f"  [dim]Skipped (already ingested): {len(skipped)}[/dim]")
    for r in done:
        console.print(f"  [green]✓[/green] {r['file']} → chunks={r['chunks']}")
    for r in failed:
        console.print(f"  [red]✗[/red] {r['file']}")
        for err in r["errors"]:
            console.print(f"      [red]{err}[/red]")

    console.print(f"\n[bold]Done.[/bold] {len(done)} ingested, {len(skipped)} skipped, {len(failed)} failed.")

    if done:
        _vacuum_chunks()
```

- [ ] **Step 6.6: Verify ingest_curriculum imports cleanly**

```bash
uv run python -c "from kuru.scripts.ingest_curriculum import ingest_document; print('OK')"
```

Expected: `OK`

- [ ] **Step 6.7: Commit**

```bash
git add src/kuru/scripts/ingest_curriculum.py src/kuru/db/supabase_client.py
git commit -m "feat: wire structured extractor and coverage tracking into ingest_curriculum"
```

---

## Task 7: Coverage Report CLI

**Files:**
- Create: `src/kuru/scripts/coverage_report.py`
- Modify: `pyproject.toml`

- [ ] **Step 7.1: Create coverage_report.py**

Create `src/kuru/scripts/coverage_report.py`:

```python
"""Coverage report — shows which programs have structured data and which are missing."""

from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from kuru.db import supabase_client as db

load_dotenv()

console = Console(legacy_windows=False)


def _classify(coverage: dict | None) -> str:
    if not coverage:
        return "no_data"
    method = coverage.get("extraction_method", "")
    if method == "scanned":
        return "scanned"
    has_overview = coverage.get("has_overview", False)
    has_plos = coverage.get("has_plos", False)
    has_courses = coverage.get("has_courses", False)
    has_timeline = coverage.get("has_timeline", False)
    full = all([has_overview, has_plos, has_courses, has_timeline])
    if full:
        return "full"
    if has_plos or has_courses:
        return "partial"
    return "no_text"


def main() -> None:
    client = db.get_client()
    programs = (
        client.table("programs")
        .select("id, name_th, name_en, faculty, coverage")
        .order("faculty")
        .execute()
        .data or []
    )

    counts = {"full": 0, "partial": 0, "scanned": 0, "no_text": 0, "no_data": 0}
    missing_name_en: list[tuple[str, str]] = []

    for p in programs:
        cov = p.get("coverage") or {}
        status = _classify(cov)
        counts[status] += 1
        if not p.get("name_en"):
            missing_name_en.append((p["id"], p.get("name_th") or "—"))

    campus = programs[0]["faculty"] if programs else "—"
    console.print(f"\n[bold]Program Coverage Report — {campus}[/bold]")
    console.print("─" * 60)

    summary = Table(show_header=True, header_style="bold")
    summary.add_column("Status", width=20)
    summary.add_column("Count", justify="right", width=8)
    summary.add_column("Details", width=40)

    summary.add_row("✓  Full",    str(counts["full"]),    "has overview + PLOs + courses + timeline")
    summary.add_row("◑  Partial", str(counts["partial"]), "missing 1–2 structured fields")
    summary.add_row("✗  No text", str(counts["no_text"]), "native text extracted but no structure")
    summary.add_row("⊘  Scanned", str(counts["scanned"]), "scanned PDF, no native text")
    summary.add_row("?  No data", str(counts["no_data"]), "not yet ingested")

    console.print(summary)
    console.print(f"\n[dim]Total programs: {len(programs)}[/dim]")
    console.print(f"[dim]name_en filled: {len(programs) - len(missing_name_en)} / {len(programs)}[/dim]")

    if missing_name_en:
        console.print("\n[yellow]Missing name_en (add to data/program_name_mapping.csv):[/yellow]")
        for pid, name_th in missing_name_en[:20]:
            console.print(f"  [dim]{pid}[/dim]  {name_th}")
        if len(missing_name_en) > 20:
            console.print(f"  [dim]... and {len(missing_name_en) - 20} more[/dim]")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7.2: Add kuru-coverage entrypoint to pyproject.toml**

Open `pyproject.toml`. In the `[project.scripts]` section, add:

```toml
kuru-coverage   = "kuru.scripts.coverage_report:main"
```

So the full section reads:

```toml
[project.scripts]
kuru-download              = "kuru.scripts.download_data:main"
kuru-setup-db              = "kuru.scripts.setup_db:main"
kuru-ingest-mko            = "kuru.scripts.ingest_curriculum:main"
kuru-ingest-tcas           = "kuru.scripts.ingest_tcas:main"
kuru-demo                  = "kuru.scripts.demo_rag:main"
kuru-scrape-curriculum     = "kuru.scripts.scrape_curriculum:main"
kuru-coverage              = "kuru.scripts.coverage_report:main"
```

- [ ] **Step 7.3: Reinstall package and verify command is available**

```bash
uv pip install -e .
uv run kuru-coverage --help
```

Expected: the command runs without error (will show empty report if DB has no programs — that's fine).

- [ ] **Step 7.4: Commit**

```bash
git add src/kuru/scripts/coverage_report.py pyproject.toml
git commit -m "feat: add kuru-coverage CLI for program data coverage report"
```

---

## Task 8: Smoke Test with 3 Native PDFs

This task validates the full pipeline end-to-end before any large-scale ingest.

- [ ] **Step 8.1: Run setup-db to apply the new schema**

```bash
uv run kuru-setup-db
```

Expected: `Supabase schema applied successfully.`

- [ ] **Step 8.2: Place 3 native test PDFs in the native directory**

Manually copy 3 native curriculum PDFs into `data/native/curriculum/บางเขน/`:

```
data/native/curriculum/บางเขน/<faculty1>/<program1>.pdf
data/native/curriculum/บางเขน/<faculty2>/<program2>.pdf
data/native/curriculum/บางเขน/<faculty3>/<program3>.pdf
```

Choose PDFs that are born-digital (open in a PDF reader and text is selectable), not scanned. 

- [ ] **Step 8.3: Run ingest on the 3 test files**

```bash
$env:PYTHONUTF8=1
uv run kuru-ingest-mko บางเขน --sample=3
```

Expected: all 3 show `✓` with chunk counts > 0. No `choices=None` errors, no API cost spike.

- [ ] **Step 8.4: Verify structured data in Supabase**

Run this Python snippet to inspect the programs table:

```bash
uv run python -c "
from dotenv import load_dotenv; load_dotenv()
from kuru.db import supabase_client as db
client = db.get_client()
rows = client.table('programs').select('id,name_th,plos,courses,coverage').limit(5).execute().data
for r in rows:
    cov = r.get('coverage') or {}
    print(r['id'], r.get('name_th','')[:30])
    print('  PLOs:', len(r.get('plos') or []))
    print('  Courses:', len(r.get('courses') or []))
    print('  Coverage:', cov.get('extraction_method'), '| has_plos:', cov.get('has_plos'))
"
```

Expected: each program shows PLO count ≥ 0, course count ≥ 0, `extraction_method` is `"pymupdf"` (not `"scanned"`).

- [ ] **Step 8.5: Run coverage report**

```bash
uv run kuru-coverage
```

Expected: table prints with at least some programs in Full or Partial status.

- [ ] **Step 8.6: Verify OCR extractor is never called during ingest**

Check that no Gemini vision API calls were made (no cost in Google Cloud console, or check logs for `[structured]` lines only — no `Rendering … for vision OCR` lines).

- [ ] **Step 8.7: Commit final smoke test confirmation**

```bash
git add .
git commit -m "chore: smoke test passed — native PDF pipeline operational"
```

---

## Verification Checklist (from spec)

- [ ] `uv run kuru-setup-db` creates programs table with all JSONB columns
- [ ] `uv run kuru-download` downloads native PDFs to `data/native/`
- [ ] Drive redirect PDFs (single file + folder) resolve correctly
- [ ] `uv run kuru-ingest-mko` on 3 test files produces structured JSONB in programs table
- [ ] Scanned PDFs produce a partial record with `coverage.extraction_method = "scanned"` and no API cost
- [ ] `uv run kuru-coverage` prints a readable report
- [ ] Frontend can query `programs` table via Supabase JS client and get `plos`, `courses`, `year_timeline`
- [ ] OCR code in `ocr_extractor.py` is importable but not called during normal ingest
