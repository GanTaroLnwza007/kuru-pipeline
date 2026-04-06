"""Supabase client — pgvector upsert and similarity search."""

from __future__ import annotations

import os
from typing import Any

from dotenv import load_dotenv
from supabase import Client, create_client

load_dotenv()


def get_client() -> Client:
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_KEY"]
    return create_client(url, key)


def upsert_program(client: Client, program: dict[str, Any]) -> None:
    """Insert or update a program record. Conflict key: id."""
    client.table("programs").upsert(program).execute()


def upsert_chunks(client: Client, chunks: list[dict[str, Any]]) -> None:
    """Batch-upsert chunk rows (with embeddings) into the chunks table."""
    if not chunks:
        return
    client.table("chunks").upsert(chunks).execute()


def upsert_tcas_records(client: Client, records: list[dict[str, Any]]) -> None:
    """Batch-upsert TCAS structured records."""
    if not records:
        return
    client.table("tcas_records").upsert(records).execute()


def similarity_search(
    client: Client,
    query_embedding: list[float],
    top_k: int = 5,
    section_type: str | None = None,
    program_id: str | None = None,
) -> list[dict[str, Any]]:
    """Cosine similarity search over the chunks table via Supabase RPC.

    Requires the following SQL function to be created in Supabase:

        create or replace function match_chunks(
          query_embedding vector(768),
          match_count      int     default 5,
          filter_section   text    default null,
          filter_program   text    default null
        )
        returns table (
          id           uuid,
          program_id   text,
          source_file  text,
          section_type text,
          content      text,
          metadata     jsonb,
          similarity   float
        )
        language sql stable as $$
          select
            id, program_id, source_file, section_type, content, metadata,
            1 - (embedding <=> query_embedding) as similarity
          from chunks
          where
            (filter_section is null or section_type = filter_section)
            and (filter_program is null or program_id = filter_program)
          order by embedding <=> query_embedding
          limit match_count;
        $$;
    """
    result = client.rpc(
        "match_chunks",
        {
            "query_embedding": query_embedding,
            "match_count": top_k,
            "filter_section": section_type,
            "filter_program": program_id,
        },
    ).execute()
    return result.data or []


def count_chunks(client: Client, source_file: str) -> int:
    """Return the number of chunks already stored for a given source file."""
    result = (
        client.table("chunks")
        .select("id", count="exact")
        .eq("source_file", source_file)
        .execute()
    )
    return result.count or 0


def get_tcas_records(
    client: Client,
    program_id: str | None = None,
    round_: str | None = None,
    program_name_search: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Fetch TCAS records with optional filters."""
    query = client.table("tcas_records").select("*")
    if program_id:
        query = query.eq("program_id", program_id)
    if round_:
        query = query.eq("round", round_)
    if program_name_search:
        query = query.ilike("program_name_raw", f"%{program_name_search}%")
    return query.limit(limit).execute().data or []
