"""Coverage report — shows which programs have structured data and which are missing."""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

from kuru.db import supabase_client as db

load_dotenv()

console = Console(legacy_windows=False)


def _classify(coverage: dict | None) -> str:
    if not coverage:
        return "no_data"
    method = coverage.get("extraction_method", "")
    if method == "scanned":
        return "scanned"
    has_overview = coverage.get("has_overview", False)
    has_plos = coverage.get("has_plos", False)
    has_courses = coverage.get("has_courses", False)
    has_timeline = coverage.get("has_timeline", False)
    if all([has_overview, has_plos, has_courses, has_timeline]):
        return "full"
    if has_plos and has_courses:
        return "partial"
    if has_courses and not has_plos:
        return "courses_only"
    if has_plos:
        return "partial"
    return "no_text"


def _populate_names(csv_path: str) -> None:
    """Upsert name_en values from a CSV into the programs table."""
    import csv as _csv  # noqa: PLC0415

    path = Path(csv_path)
    if not path.exists():
        console.print(f"[red]CSV not found: {csv_path}[/red]")
        return

    rows = []
    with path.open(encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        for row in reader:
            name_en = row.get("name_en", "").strip()
            if name_en:
                rows.append({"id": row["program_id"].strip(), "name_en": name_en})

    if not rows:
        console.print("[yellow]No name_en values to upload.[/yellow]")
        return

    client = db.get_client()
    updated = 0
    for row in rows:
        client.table("programs").update({"name_en": row["name_en"]}).eq("id", row["id"]).execute()
        updated += 1

    console.print(f"[green]Updated name_en for {updated} programs.[/green]")


def main() -> None:
    import sys as _sys  # noqa: PLC0415

    if "--populate-names" in _sys.argv:
        idx = _sys.argv.index("--populate-names")
        csv_path = _sys.argv[idx + 1] if idx + 1 < len(_sys.argv) else "data/program_name_mapping.csv"
        _populate_names(csv_path)
        return

    client = db.get_client()
    programs = (
        client.table("programs")
        .select("id, name_th, name_en, faculty, coverage")
        .order("faculty")
        .execute()
        .data or []
    )

    counts = {"full": 0, "partial": 0, "courses_only": 0, "scanned": 0, "no_text": 0, "no_data": 0}
    missing_name_en: list[tuple[str, str]] = []

    for p in programs:
        cov = p.get("coverage") or {}
        status = _classify(cov)
        counts[status] += 1
        if not p.get("name_en"):
            missing_name_en.append((p["id"], p.get("name_th") or "—"))

    campus = programs[0]["faculty"] if programs else "—"
    console.print(f"\n[bold]Program Coverage Report — {campus}[/bold]")
    console.print("─" * 60)

    summary = Table(show_header=True, header_style="bold")
    summary.add_column("Status", width=20)
    summary.add_column("Count", justify="right", width=8)
    summary.add_column("Details", width=40)

    summary.add_row("✓  Full",         str(counts["full"]),         "has overview + PLOs + courses + timeline")
    summary.add_row("◑  Partial",      str(counts["partial"]),      "has PLOs + courses, missing overview/timeline")
    summary.add_row("≡  Courses only", str(counts["courses_only"]), "courses extracted, no PLOs in source doc")
    summary.add_row("✗  No text", str(counts["no_text"]), "native text extracted but no structure")
    summary.add_row("⊘  Scanned", str(counts["scanned"]), "scanned PDF, no native text")
    summary.add_row("?  No data", str(counts["no_data"]), "not yet ingested")

    console.print(summary)
    console.print(f"\n[dim]Total programs: {len(programs)}[/dim]")
    console.print(f"[dim]name_en filled: {len(programs) - len(missing_name_en)} / {len(programs)}[/dim]")

    if missing_name_en:
        console.print("\n[yellow]Missing name_en (add to data/program_name_mapping.csv):[/yellow]")
        for pid, name_th in missing_name_en[:20]:
            console.print(f"  [dim]{pid}[/dim]  {name_th}")
        if len(missing_name_en) > 20:
            console.print(f"  [dim]... and {len(missing_name_en) - 20} more[/dim]")


if __name__ == "__main__":
    main()
