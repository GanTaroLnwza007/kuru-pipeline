"""Ingest TCAS Round 1 PDFs — extract structured admission records → Supabase."""

from __future__ import annotations

import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows UTF-8 fix
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from kuru.ingestion.tcas_extractor import (
    extract_tcas_from_pdf,
    extract_tcas_from_xlsx,
    store_tcas_records,
)

load_dotenv()

console = Console(legacy_windows=False)


def main() -> None:
    tcas_dir = Path("data/raw/tcas1")
    if not tcas_dir.exists():
        console.print("[red]data/raw/tcas1/ not found. Run kuru-download first.[/red]")
        sys.exit(1)

    files = sorted(
        p for p in tcas_dir.iterdir()
        if p.suffix.lower() in {".pdf", ".xlsx"}
    )
    if not files:
        console.print("[yellow]No PDF or xlsx files found in data/raw/tcas1/[/yellow]")
        sys.exit(0)

    console.print(f"\n[bold]Ingesting {len(files)} TCAS file(s) …[/bold]\n")

    total_records = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Processing …", total=len(files))
        for f in files:
            progress.update(task, description=f"[cyan]{f.name}[/cyan]")
            try:
                if f.suffix.lower() == ".xlsx":
                    records = extract_tcas_from_xlsx(f, verbose=False)
                else:
                    records = extract_tcas_from_pdf(f, verbose=False)
                if records:
                    store_tcas_records(records, source_file=f.name)
                console.print(
                    f"  [green]✓[/green] {f.name} → {len(records)} record(s) stored"
                )
                total_records += len(records)
            except Exception as exc:
                safe_msg = str(exc).encode("ascii", errors="replace").decode()
                console.print(f"  [red]✗[/red] {f.name} — {safe_msg}")
            progress.advance(task)

    console.print(f"\n[bold]Done.[/bold] Total TCAS records stored: [green]{total_records}[/green]")


if __name__ == "__main__":
    main()
