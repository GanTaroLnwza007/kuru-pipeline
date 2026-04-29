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
