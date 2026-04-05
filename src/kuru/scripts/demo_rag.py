"""Interactive CLI demo of the KUru RAG chatbot."""

from __future__ import annotations

import sys

from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt
from rich.table import Table

from kuru.rag.query_engine import query

load_dotenv()

console = Console()

SAMPLE_QUESTIONS = [
    "วิศวกรรมคอมพิวเตอร์มี PLO อะไรบ้าง?",
    "รอบ 1 คณะวิศวกรรมศาสตร์ต้องการ GPAX เท่าไหร่?",
    "What skills will I develop studying Computer Science?",
    "หลักสูตรนี้เรียนอะไรบ้างในปีที่ 1?",
    "portfolio ต้องมีอะไรบ้างสำหรับการสมัคร round 1?",
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
        table.add_row(
            s.get("source_file", ""),
            s.get("section_type", ""),
            str(s.get("similarity", "")),
        )
    if used_tcas:
        table.add_row("[yellow]TCAS structured data[/yellow]", "tcas_records", "–")
    console.print(table)


def main() -> None:
    console.print(BANNER)

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
            result = query(user_input)

        console.print(Panel(
            Markdown(result.answer),
            title="[bold blue]KUru Advisor[/bold blue]",
            border_style="blue",
        ))
        show_sources(result.sources, result.used_tcas_data)


if __name__ == "__main__":
    main()
