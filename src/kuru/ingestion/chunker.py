"""Section-aware text chunker for มคอ.2 curriculum documents.

Uses character-based chunking (4 chars ≈ 1 token) to avoid MemoryError
on large scanned PDFs while keeping reasonable chunk sizes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ─────────────────────────────────────────
# Constants
# ─────────────────────────────────────────

CHUNK_SIZE = 500     # target tokens
OVERLAP    = 50      # overlap tokens

# 1 token ≈ 4 characters (conservative for mixed Thai/English)
CHARS_PER_TOKEN = 4
CHUNK_CHARS   = CHUNK_SIZE * CHARS_PER_TOKEN   # 2000 chars
OVERLAP_CHARS = OVERLAP    * CHARS_PER_TOKEN   # 200 chars


def _token_estimate(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


# ─────────────────────────────────────────
# Section detection patterns (มคอ.2 structure)
# ─────────────────────────────────────────

SECTION_PATTERNS: list[tuple[str, str]] = [
    ("plo",       r"ผลการเรียนรู้ที่คาดหวัง|ผลลัพธ์การเรียนรู้|PLO|Program Learning Outcome"),
    ("course",    r"โครงสร้างหลักสูตร|รายวิชา|Course|หมวดวิชา"),
    ("admission", r"การรับเข้าศึกษา|เกณฑ์การรับ|คุณสมบัติผู้สมัคร|admission|GPAX|TCAS"),
    ("general",   r"ปรัชญา|วัตถุประสงค์|ความสำคัญ|Introduction|หลักสูตร"),
]


def _detect_section(text: str) -> str:
    for section_type, pattern in SECTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return section_type
    return "general"


# ─────────────────────────────────────────
# Chunk dataclass
# ─────────────────────────────────────────

@dataclass
class Chunk:
    content: str
    section_type: str
    chunk_index: int
    token_count: int
    metadata: dict = field(default_factory=dict)


# ─────────────────────────────────────────
# Chunking
# ─────────────────────────────────────────

def _char_chunks(text: str, section_type: str, start_index: int) -> list[Chunk]:
    """Split text into CHUNK_CHARS-sized pieces with OVERLAP_CHARS overlap."""
    chunks: list[Chunk] = []
    pos = 0
    idx = start_index

    while pos < len(text):
        end = min(pos + CHUNK_CHARS, len(text))
        piece = text[pos:end]

        # Avoid splitting mid-word: walk back to last whitespace
        if end < len(text) and not text[end].isspace():
            last_space = piece.rfind(" ")
            if last_space > CHUNK_CHARS // 2:
                end = pos + last_space
                piece = text[pos:end]

        piece = piece.strip()
        if piece:
            chunks.append(Chunk(
                content=piece,
                section_type=section_type,
                chunk_index=idx,
                token_count=_token_estimate(piece),
            ))
            idx += 1

        # Once we've reached the end of the text, stop.
        # Only apply overlap when there is more text ahead.
        if end >= len(text):
            break
        pos = end - OVERLAP_CHARS

    return chunks


def chunk_document(full_text: str) -> list[Chunk]:
    """Chunk a full document text with section-type tagging.

    Works on arbitrarily large documents without memory issues.
    """
    if not full_text.strip():
        return []

    # Split on section headers and numbered lines
    header_re = re.compile(
        r"(?m)^(?=" + "|".join(pat for _, pat in SECTION_PATTERNS) + r")",
        re.IGNORECASE,
    )
    numbered_re = re.compile(r"(?m)^(?=[\dก-ฮ๑-๙]+[.\)]\s+\S)", re.UNICODE)

    blocks: list[str] = []
    for block in header_re.split(full_text):
        blocks.extend(numbered_re.split(block))

    all_chunks: list[Chunk] = []
    chunk_index = 0

    for block in blocks:
        block = block.strip()
        if not block or len(block) < 40:   # skip very short fragments
            continue
        section_type = _detect_section(block[:300])
        new_chunks = _char_chunks(block, section_type, chunk_index)
        all_chunks.extend(new_chunks)
        chunk_index += len(new_chunks)

    return all_chunks
