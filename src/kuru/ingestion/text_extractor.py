"""Text extractor — PyMuPDF for born-digital PDFs, vision API for scanned."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from kuru.ingestion.utils import is_transient_error, safe_print
from kuru.llm import LLM_MODEL, get_client

# If PyMuPDF extracts fewer than this many chars total, treat as scanned.
SCANNED_CHAR_THRESHOLD = 500


@dataclass
class PageText:
    page_num: int
    text: str
    extraction_method: str  # 'pymupdf' | 'vision' | 'python-docx' | 'failed'


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
# Vision OCR fallback (scanned / image-only PDFs)
# ─────────────────────────────────────────

_PDF_EXTRACT_PROMPT = (
    "Extract all text from these PDF page images. "
    "Preserve Thai text exactly as written. "
    "Output only the extracted text with no commentary."
)

_OCR_DPI = 100        # 100 dpi — smaller images, faster upload, still readable Thai text
_OCR_BATCH_SIZE = 8   # pages per API call — large batches cause Gemini to hallucinate/loop
_OCR_WORKERS = 3      # parallel batch calls


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=15, max=120),
    retry=retry_if_exception(is_transient_error),
    reraise=True,
)
def _ocr_batch(images_b64: list[str]) -> str:
    """Send a batch of base64 PNG pages to the vision model and return extracted text."""
    content: list[dict] = [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}}
        for b64 in images_b64
    ]
    content.append({"type": "text", "text": _PDF_EXTRACT_PROMPT})
    response = get_client().chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": content}],
        temperature=0.0,
    )
    return response.choices[0].message.content or ""


def _dedup_lines(text: str) -> str:
    """Remove consecutive duplicate lines produced by repeated page stamps in scanned PDFs."""
    lines = text.splitlines()
    result: list[str] = []
    for line in lines:
        if not result or line.strip() != result[-1].strip():
            result.append(line)
    return "\n".join(result)


def _extract_with_vision(pdf_path: Path, verbose: bool = False) -> str:
    """Render PDF pages in parallel batches to avoid hallucination and reduce total time."""
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

    if verbose:
        safe_print(f"  {len(batches)} batches × {_OCR_BATCH_SIZE} pages, {_OCR_WORKERS} workers …")

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

    return "\n\n".join(results[i] for i, _ in batches)


def render_page_b64(pdf_path: Path, page_num: int, dpi: int = 150) -> str:
    """Render a single PDF page to a base64 PNG string."""
    doc = fitz.open(str(pdf_path))
    pix = doc[page_num].get_pixmap(dpi=dpi)
    doc.close()
    return base64.b64encode(pix.tobytes("png")).decode()


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
        text = _extract_with_vision(pdf_path, verbose=verbose)
        return [PageText(page_num=0, text=text, extraction_method="vision")]
    except Exception as exc:
        safe_print(f"  Vision OCR failed ({type(exc).__name__}): {exc}")
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
