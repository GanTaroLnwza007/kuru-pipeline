"""Batch embedder — local multilingual-e5-base → Supabase pgvector upsert.

Uses sentence-transformers (intfloat/multilingual-e5-base) which:
- Outputs 768-dim vectors (matches existing Supabase schema exactly)
- Supports Thai natively
- Runs offline — no API quota
"""

from __future__ import annotations

from typing import Any

from sentence_transformers import SentenceTransformer

from kuru.db import supabase_client as db
from kuru.ingestion.chunker import Chunk

# Model is downloaded once on first use (~1.1 GB) and cached in ~/.cache/huggingface/
EMBEDDING_MODEL = "intfloat/multilingual-e5-base"
BATCH_SIZE = 64  # local inference — larger batches are fine

_model: SentenceTransformer | None = None
_model_lock = __import__("threading").Lock()


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        with _model_lock:
            if _model is None:
                _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def _embed_batch(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts. multilingual-e5 wants a 'passage: ' prefix for documents."""
    prefixed = [f"passage: {t}" for t in texts]
    model = _get_model()
    vectors = model.encode(prefixed, normalize_embeddings=True, show_progress_bar=False)
    return [v.tolist() for v in vectors]


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

    return total
