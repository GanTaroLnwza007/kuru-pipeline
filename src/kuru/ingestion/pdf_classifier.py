"""PDF page classifier — born-digital vs scanned/image detection."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF


@dataclass
class PageClassification:
    page_num: int        # 0-indexed
    page_type: str       # 'born_digital' | 'scanned' | 'image_only'
    text_char_count: int
    total_chars_estimate: int


def classify_pdf(pdf_path: str | Path) -> list[PageClassification]:
    """Classify each page of a PDF as born-digital, scanned, or image-only.

    Strategy:
    - Extract text with PyMuPDF.
    - If a page yields >= 50 text characters, treat as born-digital.
    - Otherwise, check if the page contains any images; if yes → scanned/image.
    - Pages with neither text nor images → likely blank.
    """
    results: list[PageClassification] = []
    doc = fitz.open(str(pdf_path))
    for page_num, page in enumerate(doc):
        text = page.get_text("text")
        char_count = len(text.strip())
        # Count image objects on the page as a proxy for scanned content
        image_list = page.get_images(full=False)
        has_images = len(image_list) > 0

        if char_count >= 50:
            page_type = "born_digital"
        elif has_images:
            page_type = "scanned"
        else:
            page_type = "image_only"

        results.append(PageClassification(
            page_num=page_num,
            page_type=page_type,
            text_char_count=char_count,
            total_chars_estimate=char_count,
        ))
    doc.close()
    return results


def summary(classifications: list[PageClassification]) -> dict[str, int]:
    counts: dict[str, int] = {"born_digital": 0, "scanned": 0, "image_only": 0}
    for c in classifications:
        counts[c.page_type] = counts.get(c.page_type, 0) + 1
    return counts
