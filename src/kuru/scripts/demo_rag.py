"""Interactive CLI demo of the KUru RAG chatbot."""

from __future__ import annotations

import argparse
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows UTF-8 fix
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from kuru.rag.query_engine import query

load_dotenv()

console = Console(legacy_windows=False)

SAMPLE_QUESTIONS = [
    # TCAS / Admission
    "Tell me about TCAS of Computer Engineering",
    "What are the TCAS requirements for Software and Knowledge Engineering?",
    "How can I apply to Computer Engineering and what qualifications do I need?",
    "วิศวกรรมคอมพิวเตอร์ต้องใช้คะแนนอะไรบ้างในการสมัคร",
    # Curriculum
    "What courses will I take in Computer Engineering?",
    "What is Software and Knowledge Engineering about?",
    # PLO — works for programs whose PDFs had detectable PLO sections
    "หลักสูตรวิศวกรรมโยธา-ชลประทาน มี PLO อะไรบ้าง",
    "เล่มหลักสูตรพยาบาลสัตว์มี PLO อะไรบ้าง",
]

BANNER = """
[bold cyan]╔══════════════════════════════════════╗[/bold cyan]
[bold cyan]║      KUru Advisor — PoC Demo         ║[/bold cyan]
[bold cyan]╚══════════════════════════════════════╝[/bold cyan]

Ask questions about KU programs in Thai or English.
Type [bold]q[/bold] or [bold]exit[/bold] to quit, [bold]samples[/bold] to see example questions.
"""


def show_sources(sources: list[dict], used_tcas: bool) -> None:
    if not sources and not used_tcas:
        return
    table = Table(title="Sources", show_header=True, header_style="dim")
    table.add_column("File", style="cyan")
    table.add_column("Section")
    table.add_column("Similarity", justify="right")
    for s in sources[:5]:
        sim = s.get("similarity", 0.0)
        sim_str = f"{sim:.3f}"
        # colour-code by quality
        if sim >= 0.5:
            sim_str = f"[green]{sim_str}[/green]"
        elif sim >= 0.35:
            sim_str = f"[yellow]{sim_str}[/yellow]"
        else:
            sim_str = f"[red]{sim_str}[/red]"
        table.add_row(s.get("source_file", ""), s.get("section_type", ""), sim_str)
    if used_tcas:
        table.add_row("[yellow]TCAS structured data[/yellow]", "tcas_records", "–")
    console.print(table)


def show_debug(debug_info: dict) -> None:
    console.print("\n[bold dim]── DEBUG ──────────────────────────────[/bold dim]")
    flags = (
        f"TCAS={debug_info['is_tcas_query']}  "
        f"PLO={debug_info['is_plo_query']}  "
        f"listing={debug_info.get('is_listing_query', False)}  "
        f"resolved_program={debug_info.get('resolved_program_id') or '–'}"
    )
    console.print(
        f"[dim]Fetched {debug_info['fetched']} chunks, "
        f"{debug_info['above_threshold']} above threshold ({debug_info['threshold']})  |  {flags}[/dim]"
    )
    if debug_info.get("tcas_records_found") is not None:
        console.print(f"[dim]TCAS records matched: {debug_info['tcas_records_found']}[/dim]")
    if debug_info.get("programs_injected") is not None:
        console.print(f"[dim]Programs table injected: {debug_info['programs_injected']} rows[/dim]")

    table = Table(title="All retrieved chunks (pre-filter)", show_header=True, header_style="dim", show_lines=False)
    table.add_column("Similarity", justify="right", width=10)
    table.add_column("Section", width=10)
    table.add_column("File", width=35)
    table.add_column("Preview")
    for c in debug_info.get("raw_chunks", []):
        sim = c["similarity"]
        sim_str = f"{sim:.3f}"
        if sim >= 0.5:
            sim_str = f"[green]{sim_str}[/green]"
        elif sim >= 0.35:
            sim_str = f"[yellow]{sim_str}[/yellow]"
        else:
            sim_str = f"[red]{sim_str}[/red]"
        table.add_row(sim_str, c["section_type"], c["source_file"], c["content_preview"])
    console.print(table)
    console.print("[bold dim]───────────────────────────────────────[/bold dim]\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="KUru RAG chatbot demo")
    parser.add_argument(
        "--debug", "-d", action="store_true",
        help="Show retrieval debug info (similarity scores, all candidate chunks)"
    )
    args = parser.parse_args()

    console.print(BANNER)
    if args.debug:
        console.print("[bold yellow]Debug mode ON — retrieval details will be shown.[/bold yellow]\n")

    # Pre-load the embedding model so first query doesn't appear frozen
    console.print("[dim]Loading embedding model …[/dim]", end=" ")
    from kuru.ingestion.embedder import _get_model
    _get_model()
    console.print("[dim]ready.[/dim]\n")

    while True:
        try:
            user_input = Prompt.ask("\n[bold green]You[/bold green]").strip()
        except (KeyboardInterrupt, EOFError):
            console.print("\nGoodbye!")
            sys.exit(0)

        if not user_input:
            continue
        if user_input.lower() in ("q", "exit", "quit"):
            console.print("Goodbye!")
            sys.exit(0)
        if user_input.lower() == "samples":
            console.print("\n[bold]Example questions:[/bold]")
            for i, q_text in enumerate(SAMPLE_QUESTIONS, 1):
                console.print(f"  {i}. {q_text}")
            continue

        with console.status("[bold yellow]Thinking …[/bold yellow]"):
            result = query(user_input, debug=args.debug)

        if args.debug and result.debug_info:
            show_debug(result.debug_info)

        console.print(Panel(
            Markdown(result.answer),
            title="[bold blue]KUru Advisor[/bold blue]",
            border_style="blue",
        ))
        show_sources(result.sources, result.used_tcas_data)


if __name__ == "__main__":
    main()
