"""Ingest มคอ.2 curriculum PDFs — extract, chunk, embed, store PLOs."""

from __future__ import annotations

import csv
import hashlib
import math
import os
import re
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows UTF-8 fix
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from rich.console import Console

from kuru.db import supabase_client as db
from kuru.ingestion.chunker import chunk_document
from kuru.ingestion.embedder import embed_and_store, _get_model
from kuru.ingestion.structured_extractor import StructuredProgram, extract_structured
from kuru.ingestion.text_extractor import PageText, extract_text_auto, full_text

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
    campus_dir = Path("data/native/curriculum") / campus
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


_CURRICULUM_MARKERS = re.compile(
    r"มคอ\.?\s*2|หลักสูตร|สาขาวิชา|ปริญญา|curriculum|programme|program",
    re.IGNORECASE,
)

# PDFs whose filename announces that the program was officially closed.
_CLOSED_RE = re.compile(r"ปิดหลักสูตร|สภาฯ.{0,10}อนุมัติปิด")

_DEGREE_YEAR_RE = re.compile(r"_\d{4}(?:_\d+)*$")

_EN_NAME_RE = re.compile(
    r"(?:Bachelor|Master|Doctor)\s+of\s+[\w\s,\-]+?Program\s+in\s+[^\n\r]{5,80}",
    re.IGNORECASE,
)

def _is_curriculum_doc(text: str) -> bool:
    """Return False if the extracted text doesn't look like a มคอ.2 curriculum document."""
    return bool(_CURRICULUM_MARKERS.search(text[:3000]))


def _program_name_from_stem(stem: str) -> str:
    """Human-readable Thai name from a PDF stem, e.g. 'วท.บ._วนศาสตร์_2567' → 'วท.บ. วนศาสตร์'."""
    return _DEGREE_YEAR_RE.sub("", stem).replace("_", " ").strip()


def _degree_level(stem: str) -> str:
    if "ปร.ด" in stem or "Ph.D" in stem:
        return "doctoral"
    if any(x in stem for x in ("วท.ม", "ศศ.ม", "บธ.ม", "วศ.ม", "ผ.ม", "M.S.", "M.B.A")):
        return "master"
    return "bachelor"


def _extract_name_en(doc_text: str) -> str | None:
    m = _EN_NAME_RE.search(doc_text[:5000])
    return m.group(0).strip()[:150] if m else None


def _load_name_mapping() -> dict[str, dict]:
    """Load data/program_name_mapping.csv → {program_id: {name_en, name_th_canonical}}."""
    csv_path = Path("data/program_name_mapping.csv")
    if not csv_path.exists():
        return {}
    result: dict[str, dict] = {}
    with open(csv_path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            result[row["program_id"]] = {
                "name_en": row.get("name_en") or None,
                "name_th_canonical": row.get("name_th_canonical") or None,
            }
    return result


def _build_coverage(
    pages: list[PageText],
    structured: StructuredProgram,
    name_en_source: str | None,
) -> dict:
    total_pages = len(pages)
    scanned_pages = sum(1 for p in pages if p.extraction_method == "scanned")
    typhoon_pages = sum(1 for p in pages if p.extraction_method == "typhoon_page")

    if scanned_pages == total_pages and total_pages > 0:
        method = "scanned"
    elif typhoon_pages > 0:
        method = "pymupdf+typhoon_pages"
    else:
        method = "pymupdf"

    return {
        "extraction_method": method,
        "has_overview": bool(structured.overview),
        "has_plos": len(structured.plos) > 0,
        "plo_count": len(structured.plos),
        "has_courses": len(structured.courses) > 0,
        "course_count": len(structured.courses),
        "has_timeline": len(structured.year_timeline) > 0,
        "has_curriculum_mapping": len(structured.curriculum_mapping) > 0,
        "scanned_pages": scanned_pages,
        "total_pages": total_pages,
        "name_en_source": name_en_source,
    }


def ingest_document(pdf_path: Path, campus: str, name_mapping: dict, verbose: bool = False) -> dict:
    """Full pipeline for one curriculum document (PDF or DOCX). Returns a status dict."""
    program_id = _program_id_from_path(pdf_path, campus)
    status = {
        "file": pdf_path.name,
        "campus": campus,
        "program_id": program_id,
        "chunks": 0,
        "skipped": False,
        "errors": [],
    }

    client = db.get_client()

    name_th = _program_name_from_stem(pdf_path.stem)

    # Resolve English name: CSV mapping first, auto-extract from text later
    mapping = name_mapping.get(program_id, {})
    name_en_from_csv = mapping.get("name_en")
    name_en_source: str | None = "csv_mapping" if name_en_from_csv else None

    db.upsert_program(client, {
        "id": program_id,
        "name_th": name_th,
        "name_en": name_en_from_csv,
        "faculty": campus,
        "degree_level": _degree_level(pdf_path.stem),
    })

    # ── Resume: skip if already fully ingested ──────────────────────────────
    existing = db.count_chunks(client, pdf_path.name)
    if existing > 0:
        status["chunks"] = existing
        status["skipped"] = True
        return status

    # ── Text extraction ─────────────────────────────────────────────────────
    try:
        pages = extract_text_auto(pdf_path, use_vision_fallback=True, verbose=verbose)
        doc_text = full_text(pages)
    except Exception as exc:
        status["errors"].append(f"text extraction ({type(exc).__name__}): {exc}")
        return status

    # Backfill English name from PDF text if CSV had nothing
    if not name_en_from_csv:
        name_en_auto = _extract_name_en(doc_text)
        if name_en_auto:
            db.upsert_program(client, {"id": program_id, "name_en": name_en_auto})
            name_en_source = "auto_extracted"

    # ── Scanned PDF — write partial record and stop ─────────────────────────
    all_scanned = all(p.extraction_method == "scanned" for p in pages)
    if all_scanned:
        coverage = _build_coverage(pages, StructuredProgram(), name_en_source)
        db.update_program_structured(client, program_id, {"coverage": coverage})
        status["errors"].append("scanned PDF — no native text, OCR disabled")
        return status

    # ── Curriculum check — skip MOUs, agreements, announcements ────────────
    if not _is_curriculum_doc(doc_text):
        status["skipped"] = True
        status["errors"].append("not a curriculum doc (no มคอ.2 markers) — skipped")
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

    # ── Structured extraction ───────────────────────────────────────────────
    structured = extract_structured(doc_text, verbose=verbose)
    coverage = _build_coverage(pages, structured, name_en_source)

    db.update_program_structured(client, program_id, {
        "overview": structured.overview or None,
        "plos": structured.plos,
        "courses": structured.courses,
        "year_timeline": structured.year_timeline,
        "curriculum_mapping": structured.curriculum_mapping,
        "coverage": coverage,
    })

    return status


_APPENDIX_RE = re.compile(r"ภาคผนวก", re.IGNORECASE)


def find_documents(base_dir: Path, campus: str) -> list[Path]:
    """Return all ingestable documents (.pdf, .docx) for the given campus."""
    all_docs = sorted(
        p for p in base_dir.rglob("*")
        if p.suffix.lower() in {".pdf", ".docx"}
    )
    # Drop officially-closed programs.
    closed = [p for p in all_docs if _CLOSED_RE.search(p.name)]
    if closed:
        console.print(f"[dim]Skipping {len(closed)} closed-program file(s) (ปิดหลักสูตร)[/dim]")
    all_docs = [p for p in all_docs if not _CLOSED_RE.search(p.name)]

    # Drop appendix folders (ภาคผนวก) — supporting docs, not curriculum programs.
    appendix = [p for p in all_docs if any(_APPENDIX_RE.search(part) for part in p.parts)]
    if appendix:
        console.print(f"[dim]Skipping {len(appendix)} appendix file(s) (ภาคผนวก)[/dim]")
    all_docs = [p for p in all_docs if not any(_APPENDIX_RE.search(part) for part in p.parts)]

    # When a folder has both PDF and DOCX with the same stem, keep only the PDF.
    pdf_stems = {p.parent / p.stem for p in all_docs if p.suffix.lower() == ".pdf"}
    docx_dupes = [p for p in all_docs if p.suffix.lower() == ".docx" and (p.parent / p.stem) in pdf_stems]
    if docx_dupes:
        console.print(f"[dim]Skipping {len(docx_dupes)} DOCX duplicate(s) (PDF version exists)[/dim]")
    all_docs = [p for p in all_docs if p not in docx_dupes]

    matches = [p for p in all_docs if campus in str(p)]
    if matches:
        return matches
    if all_docs:
        console.print(
            f"[yellow]Warning: no subfolder named '{campus}' found — "
            f"processing all {len(all_docs)} document(s).[/yellow]"
        )
    return all_docs


def sample_documents(docs: list[Path], n: int, campus_dir: Path) -> list[Path]:
    """Pick n files spread proportionally across faculty subfolders for variety."""
    by_faculty: defaultdict[str, list[Path]] = defaultdict(list)
    for p in docs:
        try:
            faculty = p.relative_to(campus_dir).parts[0]
        except (ValueError, IndexError):
            faculty = "_other"
        by_faculty[faculty].append(p)

    faculties = sorted(by_faculty)
    sampled: list[Path] = []
    remaining = n

    for i, faculty in enumerate(faculties):
        faculties_left = len(faculties) - i
        take = math.ceil(remaining / faculties_left)
        take = min(take, len(by_faculty[faculty]), remaining)
        sampled.extend(by_faculty[faculty][:take])
        remaining -= take
        if remaining <= 0:
            break

    console.print(f"[dim]Sample: {len(sampled)} files across {len(by_faculty)} faculties[/dim]")
    for faculty in faculties:
        taken = [p for p in sampled if faculty in str(p)]
        if taken:
            console.print(f"  [dim]{faculty}: {len(taken)} file(s)[/dim]")
    return sampled


def main(campus: str | None = None, sample: int | None = None) -> None:
    args = sys.argv[1:]
    if campus is None:
        campus = next((a for a in args if not a.startswith("--")), DEFAULT_CAMPUS)
    if sample is None:
        for a in args:
            if a.startswith("--sample="):
                sample = int(a.split("=", 1)[1])
            elif a == "--sample" and args.index(a) + 1 < len(args):
                sample = int(args[args.index(a) + 1])

    base_dir = Path("data/native/curriculum")
    if not base_dir.exists():
        console.print("[red]data/native/curriculum/ not found. Run kuru-download first.[/red]")
        sys.exit(1)

    name_mapping = _load_name_mapping()
    console.print(f"[dim]Loaded {len(name_mapping)} name mapping(s) from CSV[/dim]")

    docs = find_documents(base_dir, campus)
    if not docs:
        console.print(f"[yellow]No documents found for campus '{campus}' under {base_dir}[/yellow]")
        sys.exit(0)

    campus_dir = base_dir / campus
    if sample and sample < len(docs):
        docs = sample_documents(docs, sample, campus_dir)

    console.print(f"\n[bold]Campus:[/bold] [cyan]{campus}[/cyan]")
    console.print(f"[bold]Processing {len(docs)} document(s) — checking which need ingestion …[/bold]\n")

    # Pre-load embedding model once before threads start (avoids race condition).
    console.print("[dim]Loading embedding model …[/dim]")
    _get_model()

    results = []
    completed = 0
    console.print(f"[dim]Running {FILE_WORKERS} files in parallel …[/dim]\n")

    # Background heartbeat — prints every 30s so the terminal doesn't look frozen.
    _start = time.time()
    _stop_heartbeat = threading.Event()

    def _heartbeat():
        while not _stop_heartbeat.wait(30):
            elapsed = int(time.time() - _start)
            m, s = divmod(elapsed, 60)
            in_flight = min(FILE_WORKERS, len(docs) - completed)
            console.print(f"  [dim]... still running — {m:02d}:{s:02d} elapsed, {completed}/{len(docs)} done[/dim]")

    hb = threading.Thread(target=_heartbeat, daemon=True)
    hb.start()

    pool = ThreadPoolExecutor(max_workers=FILE_WORKERS)
    futures = {pool.submit(ingest_document, pdf, campus, name_mapping, False): pdf for pdf in docs}
    try:
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
    except KeyboardInterrupt:
        _stop_heartbeat.set()
        console.print("\n[yellow]Interrupted — cancelling queued files …[/yellow]")
        for f in futures:
            f.cancel()
        pool.shutdown(wait=False)
        console.print(f"[yellow]Stopped at {completed}/{len(docs)} files. Re-run to resume.[/yellow]")
        import os; os._exit(0)

    _stop_heartbeat.set()

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
            f"chunks={r['chunks']}"
        )
    for r in failed:
        console.print(f"  [red]✗[/red] {r['file']} → {r['program_id']}")
        for err in r["errors"]:
            console.print(f"      [red]{err}[/red]")

    console.print(
        f"\n[bold]Done.[/bold] {len(done)} ingested, "
        f"{len(skipped)} skipped, {len(failed)} failed."
    )

    # Refresh planner stats so pgvector queries use the index instead of seq-scanning.
    # Without this, queries time out after a bulk ingest until VACUUM runs.
    if done:
        _vacuum_chunks()


def _vacuum_chunks() -> None:
    """Run VACUUM ANALYZE chunks to refresh pgvector planner stats after bulk insert."""
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        console.print("[yellow]DATABASE_URL not set — skipping post-ingest VACUUM ANALYZE[/yellow]")
        return
    try:
        import psycopg2  # noqa: PLC0415
        console.print("\n[dim]Running VACUUM ANALYZE chunks …[/dim]")
        conn = psycopg2.connect(db_url)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute("SET statement_timeout = 0;")
            cur.execute("VACUUM ANALYZE chunks;")
        conn.close()
        console.print("[dim]VACUUM done.[/dim]")
    except Exception as exc:
        console.print(f"[yellow]VACUUM failed ({type(exc).__name__}): {exc}[/yellow]")


if __name__ == "__main__":
    main()
