"""Batch embedder — Gemini text-embedding-004 → Supabase pgvector upsert."""

from __future__ import annotations

import os
import time
from typing import Any

from dotenv import load_dotenv
from google import genai
from google.genai import types
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from kuru.db import supabase_client as db
from kuru.ingestion.chunker import Chunk

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


EMBEDDING_MODEL = "gemini-embedding-001"
BATCH_SIZE = 20    # Reduced from 100 — safer for free tier per-request limits
RATE_LIMIT_SLEEP = 4.0  # seconds between batches (free tier: 100 RPM embedding)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=15, max=120), retry=retry_if_exception(_is_transient), reraise=True)
def _embed_batch(texts: list[str]) -> list[list[float]]:
    response = _get_client().models.embed_content(
        model=EMBEDDING_MODEL,
        contents=texts,
        config=types.EmbedContentConfig(
            task_type="RETRIEVAL_DOCUMENT",
            output_dimensionality=768,
        ),
    )
    return [e.values for e in response.embeddings]


def embed_and_store(
    chunks: list[Chunk],
    program_id: str,
    source_file: str,
    verbose: bool = False,
) -> int:
    """Embed chunks in batches and upsert to Supabase. Returns count stored."""
    client = db.get_client()
    total = 0

    for batch_start in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[batch_start : batch_start + BATCH_SIZE]
        texts = [c.content for c in batch]

        if verbose:
            print(f"  Embedding batch {batch_start}–{batch_start + len(batch) - 1} …")

        embeddings = _embed_batch(texts)

        rows: list[dict[str, Any]] = []
        for chunk, embedding in zip(batch, embeddings):
            rows.append({
                "program_id":   program_id,
                "source_file":  source_file,
                "section_type": chunk.section_type,
                "content":      chunk.content,
                "embedding":    embedding,
                "metadata": {
                    "chunk_index": chunk.chunk_index,
                    "token_count": chunk.token_count,
                    **chunk.metadata,
                },
            })

        db.upsert_chunks(client, rows)
        total += len(rows)
        time.sleep(RATE_LIMIT_SLEEP)

    return total
