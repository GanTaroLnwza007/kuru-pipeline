"""Idempotent database setup — Supabase tables + Neo4j constraints."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def setup_supabase() -> None:
    """Apply db/schema.sql to Supabase via direct PostgreSQL connection."""
    try:
        import psycopg2  # type: ignore
    except ImportError:
        print("psycopg2 not installed. Install with: uv add psycopg2-binary")
        print("Skipping Supabase schema setup.")
        return

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set in .env — skipping Supabase schema setup.")
        return

    schema_path = Path(__file__).parent.parent.parent.parent / "db" / "schema.sql"
    if not schema_path.exists():
        print(f"Schema file not found: {schema_path}")
        return

    sql = schema_path.read_text(encoding="utf-8")
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(sql)
        print("Supabase schema applied successfully.")
    finally:
        conn.close()


def setup_neo4j() -> None:
    """Create Neo4j constraints."""
    from kuru.db import neo4j_client as neo4j  # noqa: PLC0415
    neo4j.setup_schema()
    print("Neo4j constraints created.")


def main() -> None:
    print("Setting up databases …\n")
    setup_supabase()
    setup_neo4j()
    print("\nDatabase setup complete.")


if __name__ == "__main__":
    main()
