"""Text extractor — PyMuPDF for born-digital PDFs, Gemini Files API for scanned."""

from __future__ import annotations

import os
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from dotenv import load_dotenv
from google import genai
from google.genai import types
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

load_dotenv()

_client: genai.Client | None = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    return _client


GEMINI_MODEL = "gemini-2.0-flash"

# If PyMuPDF extracts fewer than this many chars total, treat as scanned.
SCANNED_CHAR_THRESHOLD = 500


def _safe_print(msg: str) -> None:
    """Print safely on Windows regardless of console encoding."""
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="replace").decode())


@dataclass
class PageText:
    page_num: int
    text: str
    extraction_method: str  # 'pymupdf' | 'gemini_files' | 'failed'


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


def _is_transient(exc: BaseException) -> bool:
    """Only retry on API/network errors — not programming errors like TypeError."""
    if isinstance(exc, (TypeError, ValueError, AttributeError, UnicodeError)):
        return False
    msg = str(exc)
    return any(code in msg for code in ("429", "500", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE"))


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=15, max=120),
    retry=retry_if_exception(_is_transient),
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
            _safe_print(f"  Uploading {pdf_path.name} to Gemini Files API …")

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
        _safe_print("  File active — extracting text …")

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_uri(file_uri=file_ref.uri, mime_type="application/pdf"),
                types.Part.from_text(PDF_EXTRACT_PROMPT),
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
        _safe_print(f"  Low text yield ({total_chars} chars) — using Gemini Files API")

    try:
        text = _extract_with_gemini_files(pdf_path, verbose=verbose)
        return [PageText(page_num=0, text=text, extraction_method="gemini_files")]
    except Exception as exc:
        _safe_print(f"  Gemini Files extraction failed ({type(exc).__name__}): {exc}")
        return [PageText(page_num=0, text="", extraction_method="failed")]


def full_text(pages: list[PageText]) -> str:
    return "\n\n".join(p.text for p in pages if p.text.strip())
