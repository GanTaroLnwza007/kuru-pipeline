"""Ingest มคอ.2 curriculum PDFs — extract, chunk, embed, store PLOs."""

from __future__ import annotations

import hashlib
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows UTF-8 fix
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from rich.console import Console

from kuru.db import supabase_client as db
from kuru.ingestion.chunker import chunk_document
from kuru.ingestion.embedder import embed_and_store, _get_model
from kuru.ingestion.text_extractor import extract_text_auto, full_text

load_dotenv()

console = Console(legacy_windows=False)

DEFAULT_CAMPUS = "บางเขน"
FILE_WORKERS = 3  # parallel file ingestion — 3 files × 3 OCR batch workers = 9 concurrent API calls


def _program_id_from_path(pdf_path: Path, campus: str) -> str:
    campus_slug = {
        "บางเขน": "bangkhen",
        "กำแพงแสน": "kamphaengsaen",
        "ศรีราชา": "sriracha",
    }.get(campus, re.sub(r"\s+", "_", campus).lower())

    # Use the faculty subfolder (e.g. "eng", "agri") as a stable prefix.
    # The scraper places files under data/raw/curriculum/<campus>/<faculty>/<file>.
    campus_dir = Path("data/raw/curriculum") / campus
    try:
        rel = pdf_path.relative_to(campus_dir)
        faculty_part = rel.parts[0] if len(rel.parts) > 1 else ""
        faculty_part = re.sub(r"[^a-zA-Z0-9]", "", faculty_part.encode("ascii", errors="ignore").decode()).lower()
    except ValueError:
        faculty_part = ""

    # Hash the stem to guarantee uniqueness even when Thai names strip to nothing.
    stem_hash = hashlib.md5(pdf_path.stem.encode()).hexdigest()[:8]
    name_part = f"{faculty_part}_{stem_hash}" if faculty_part else stem_hash
    return f"{campus_slug}_{name_part}"


def ingest_document(pdf_path: Path, campus: str, verbose: bool = False) -> dict:
    """Full pipeline for one curriculum document (PDF or DOCX). Returns a status dict."""
    program_id = _program_id_from_path(pdf_path, campus)
    status = {
        "file": pdf_path.name,
        "campus": campus,
        "program_id": program_id,
        "chunks": 0,
        "plos": 0,
        "skipped": False,
        "errors": [],
    }

    client = db.get_client()

    # ── Resume: skip if already fully ingested ──────────────────────────────
    existing = db.count_chunks(client, pdf_path.name)
    if existing > 0:
        status["chunks"] = existing
        status["skipped"] = True
        return status

    db.upsert_program(client, {"id": program_id, "name_th": program_id, "faculty": campus})

    # ── Text extraction ─────────────────────────────────────────────────────
    try:
        pages = extract_text_auto(pdf_path, use_vision_fallback=True, verbose=verbose)
        doc_text = full_text(pages)
    except Exception as exc:
        status["errors"].append(f"text extraction ({type(exc).__name__}): {exc}")
        return status

    # ── Chunking ────────────────────────────────────────────────────────────
    chunks = chunk_document(doc_text)
    if not chunks:
        status["errors"].append("no chunks produced — PDF may be image-only or empty")
        return status

    # ── Embedding + Supabase ────────────────────────────────────────────────
    try:
        stored = embed_and_store(
            chunks, program_id=program_id, source_file=pdf_path.name, verbose=verbose
        )
        status["chunks"] = stored
    except Exception as exc:
        status["errors"].append(f"embedding ({type(exc).__name__}): {exc}")

    # PLO extraction is run separately via a dedicated command (too slow per-file)

    return status


def find_documents(base_dir: Path, campus: str) -> list[Path]:
    """Return all ingestable documents (.pdf, .docx) for the given campus."""
    all_docs = sorted(
        p for p in base_dir.rglob("*")
        if p.suffix.lower() in {".pdf", ".docx"}
    )
    matches = [p for p in all_docs if campus in str(p)]
    if matches:
        return matches
    if all_docs:
        console.print(
            f"[yellow]Warning: no subfolder named '{campus}' found — "
            f"processing all {len(all_docs)} document(s).[/yellow]"
        )
    return all_docs


def main(campus: str | None = None) -> None:
    if campus is None:
        campus = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CAMPUS
    base_dir = Path("data/raw/curriculum")
    if not base_dir.exists():
        console.print("[red]data/raw/curriculum/ not found. Run kuru-download first.[/red]")
        sys.exit(1)

    docs = find_documents(base_dir, campus)
    if not docs:
        console.print(f"[yellow]No documents found for campus '{campus}' under {base_dir}[/yellow]")
        sys.exit(0)

    console.print(f"\n[bold]Campus:[/bold] [cyan]{campus}[/cyan]")
    console.print(f"[bold]Found {len(docs)} document(s) — checking which need ingestion …[/bold]\n")

    # Pre-load embedding model once before threads start (avoids race condition).
    console.print("[dim]Loading embedding model …[/dim]")
    _get_model()

    results = []
    completed = 0
    console.print(f"[dim]Running {FILE_WORKERS} files in parallel …[/dim]\n")

    with ThreadPoolExecutor(max_workers=FILE_WORKERS) as pool:
        futures = {pool.submit(ingest_document, pdf, campus, False): pdf for pdf in docs}
        for future in as_completed(futures):
            status = future.result()
            results.append(status)
            completed += 1
            tag = "[dim]skip[/dim]" if status["skipped"] else (
                "[red]FAIL[/red]" if status["errors"] else "[green]✓[/green]"
            )
            console.print(
                f"  {tag} [{completed}/{len(docs)}] {status['file'][:55]}"
                + (f" → chunks={status['chunks']}" if not status["skipped"] else "")
            )

    # ── Summary ─────────────────────────────────────────────────────────────
    console.print("\n[bold]Ingestion Summary[/bold]")
    skipped = [r for r in results if r["skipped"]]
    done    = [r for r in results if not r["skipped"] and not r["errors"]]
    failed  = [r for r in results if not r["skipped"] and r["errors"]]

    if skipped:
        console.print(f"  [dim]Skipped (already ingested): {len(skipped)} file(s)[/dim]")
    for r in done:
        console.print(
            f"  [green]✓[/green] {r['file']} → [green]{r['program_id']}[/green] "
            f"chunks={r['chunks']} PLOs={r['plos']}"
        )
    for r in failed:
        console.print(f"  [red]✗[/red] {r['file']} → {r['program_id']}")
        for err in r["errors"]:
            console.print(f"      [red]{err}[/red]")

    console.print(
        f"\n[bold]Done.[/bold] {len(done)} ingested, "
        f"{len(skipped)} skipped, {len(failed)} failed."
    )


if __name__ == "__main__":
    campus_arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CAMPUS
    main(campus=campus_arg)
