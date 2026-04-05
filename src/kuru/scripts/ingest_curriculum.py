"""Ingest มคอ.2 curriculum PDFs — extract, chunk, embed, store PLOs."""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from kuru.db import supabase_client as db
from kuru.ingestion.chunker import chunk_document
from kuru.ingestion.embedder import embed_and_store
from kuru.ingestion.plo_extractor import extract_plos_from_pdf, store_plos_to_neo4j
from kuru.ingestion.text_extractor import extract_text, full_text

load_dotenv()

console = Console()

DEFAULT_CAMPUS = "บางเขน"
INTER_FILE_SLEEP = 5   # seconds between files — Gemini 2.0-flash free tier: 15 RPM


def _program_id_from_path(pdf_path: Path, campus: str) -> str:
    campus_slug = {
        "บางเขน": "bangkhen",
        "กำแพงแสน": "kamphaengsaen",
        "ศรีราชา": "sriracha",
    }.get(campus, re.sub(r"\s+", "_", campus).lower())

    stem = pdf_path.stem
    ascii_part = re.sub(r"[^a-zA-Z0-9]", "", stem.encode("ascii", errors="ignore").decode()).lower()
    name_part = ascii_part[:24] if ascii_part else f"doc{abs(hash(stem)) % 9999}"
    return f"{campus_slug}_{name_part}"


def ingest_pdf(pdf_path: Path, campus: str, verbose: bool = False) -> dict:
    """Full pipeline for one curriculum PDF. Returns a status dict."""
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
        pages = extract_text(pdf_path, use_vision_fallback=True, verbose=verbose)
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

    # ── PLO extraction + Neo4j ──────────────────────────────────────────────
    try:
        result = extract_plos_from_pdf(pdf_path, program_id=program_id, verbose=verbose)
        if result:
            store_plos_to_neo4j(result)
            status["plos"] = len(result.plos)
            db.upsert_program(client, {
                "id": program_id,
                "name_th": result.faculty_name_th,
                "faculty": campus,
            })
    except Exception as exc:
        status["errors"].append(f"PLO extraction ({type(exc).__name__}): {exc}")

    return status


def find_pdfs(base_dir: Path, campus: str) -> list[Path]:
    matches = [p for p in base_dir.rglob("*.pdf") if campus in str(p)]
    if matches:
        return sorted(matches)
    all_pdfs = sorted(base_dir.rglob("*.pdf"))
    if all_pdfs:
        console.print(
            f"[yellow]Warning: no subfolder named '{campus}' found — "
            f"processing all {len(all_pdfs)} PDFs.[/yellow]"
        )
    return all_pdfs


def main(campus: str = DEFAULT_CAMPUS) -> None:
    base_dir = Path("data/raw/curriculum")
    if not base_dir.exists():
        console.print("[red]data/raw/curriculum/ not found. Run kuru-download first.[/red]")
        sys.exit(1)

    pdfs = find_pdfs(base_dir, campus)
    if not pdfs:
        console.print(f"[yellow]No PDFs found for campus '{campus}' under {base_dir}[/yellow]")
        sys.exit(0)

    console.print(f"\n[bold]Campus:[/bold] [cyan]{campus}[/cyan]")
    console.print(f"[bold]Found {len(pdfs)} PDF(s) — checking which need ingestion …[/bold]\n")

    results = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Processing …", total=len(pdfs))
        for pdf in pdfs:
            progress.update(task, description=f"[cyan]{pdf.name[:60]}[/cyan]")
            status = ingest_pdf(pdf, campus=campus, verbose=False)
            results.append(status)
            progress.advance(task)
            if not status["skipped"]:
                time.sleep(INTER_FILE_SLEEP)

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
