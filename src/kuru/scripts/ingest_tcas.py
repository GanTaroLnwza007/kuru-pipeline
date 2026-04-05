"""Ingest TCAS Round 1 PDFs — extract structured admission records → Supabase."""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from kuru.ingestion.tcas_extractor import extract_tcas_from_pdf, store_tcas_records

load_dotenv()

console = Console()


def main() -> None:
    tcas_dir = Path("data/raw/tcas1")
    if not tcas_dir.exists():
        console.print("[red]data/raw/tcas1/ not found. Run kuru-download first.[/red]")
        sys.exit(1)

    pdfs = list(tcas_dir.glob("*.pdf"))
    if not pdfs:
        console.print("[yellow]No PDF files found in data/raw/tcas1/[/yellow]")
        sys.exit(0)

    console.print(f"\n[bold]Ingesting {len(pdfs)} TCAS PDF(s) …[/bold]\n")

    total_records = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Processing …", total=len(pdfs))
        for pdf in pdfs:
            progress.update(task, description=f"[cyan]{pdf.name}[/cyan]")
            try:
                records = extract_tcas_from_pdf(pdf, verbose=False)
                if records:
                    store_tcas_records(records, source_file=pdf.name)
                console.print(
                    f"  [green]✓[/green] {pdf.name} → {len(records)} record(s) stored"
                )
                total_records += len(records)
            except Exception as exc:
                console.print(f"  [red]✗[/red] {pdf.name} — {exc}")
            progress.advance(task)

    console.print(f"\n[bold]Done.[/bold] Total TCAS records stored: [green]{total_records}[/green]")


if __name__ == "__main__":
    main()
