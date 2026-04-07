"""Text extractor — PyMuPDF for born-digital PDFs, Gemini Files API for scanned."""

from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from dotenv import load_dotenv
from google import genai
from google.genai import types
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from kuru.ingestion.utils import is_transient_error, safe_print

load_dotenv()

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


GEMINI_MODEL = "gemini-2.5-flash-lite"

# If PyMuPDF extracts fewer than this many chars total, treat as scanned.
SCANNED_CHAR_THRESHOLD = 500


@dataclass
class PageText:
    page_num: int
    text: str
    extraction_method: str  # 'pymupdf' | 'gemini_files' | 'python-docx' | 'failed'


# ─────────────────────────────────────────
# PyMuPDF extraction (born-digital)
# ─────────────────────────────────────────

def _extract_pymupdf(pdf_path: Path) -> list[PageText]:
    doc = fitz.open(str(pdf_path))
    pages = [
        PageText(
            page_num=i,
            text=page.get_text("text"),
            extraction_method="pymupdf",
        )
        for i, page in enumerate(doc)
    ]
    doc.close()
    return pages


# ─────────────────────────────────────────
# Gemini Files API extraction (scanned / whole-PDF)
# ─────────────────────────────────────────

PDF_EXTRACT_PROMPT = (
    "Extract all text from this PDF document. "
    "Preserve Thai text exactly as written. "
    "Output only the extracted text with no commentary."
)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=15, max=120),
    retry=retry_if_exception(is_transient_error),
    reraise=True,
)
def _extract_with_gemini_files(pdf_path: Path, verbose: bool = False) -> str:
    """Upload the entire PDF to Gemini Files API and extract text in one call."""
    client = _get_client()

    # Write to a temp file with ASCII path — avoids Windows SDK encoding bugs
    # with Thai characters in file paths.
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".pdf")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(pdf_path.read_bytes())

        if verbose:
            safe_print(f"  Uploading {pdf_path.name} to Gemini Files API …")

        uploaded = client.files.upload(
            file=tmp_path,
            config=types.UploadFileConfig(mime_type="application/pdf"),
        )
    finally:
        tmp_path.unlink(missing_ok=True)

    # Wait until the file is ACTIVE (usually immediate)
    file_ref = uploaded
    for _ in range(15):
        if file_ref.state and file_ref.state.name == "ACTIVE":
            break
        time.sleep(2)
        file_ref = client.files.get(name=uploaded.name)

    if verbose:
        safe_print("  File active — extracting text …")

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_uri(file_uri=file_ref.uri, mime_type="application/pdf"),
                types.Part.from_text(text=PDF_EXTRACT_PROMPT),
            ],
        )
    finally:
        # Always clean up uploaded file
        try:
            client.files.delete(name=uploaded.name)
        except Exception:
            pass

    return response.text or ""


# ─────────────────────────────────────────
# Public API
# ─────────────────────────────────────────

def extract_text(
    pdf_path: str | Path,
    use_vision_fallback: bool = True,
    verbose: bool = False,
) -> list[PageText]:
    """Extract text from a PDF.

    1. PyMuPDF (free, instant).
    2. If total chars < threshold AND fallback enabled → Gemini Files API (1 API call).
    """
    pdf_path = Path(pdf_path)
    pages = _extract_pymupdf(pdf_path)
    total_chars = sum(len(p.text.strip()) for p in pages)

    if total_chars >= SCANNED_CHAR_THRESHOLD or not use_vision_fallback:
        return pages

    if verbose:
        safe_print(f"  Low text yield ({total_chars} chars) — using Gemini Files API")

    try:
        text = _extract_with_gemini_files(pdf_path, verbose=verbose)
        return [PageText(page_num=0, text=text, extraction_method="gemini_files")]
    except Exception as exc:
        safe_print(f"  Gemini Files extraction failed ({type(exc).__name__}): {exc}")
        return [PageText(page_num=0, text="", extraction_method="failed")]


def extract_text_from_docx(docx_path: Path) -> list[PageText]:
    """Extract text from a DOCX file using python-docx.

    Includes body paragraphs and table cell text.
    """
    try:
        import docx  # python-docx

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
