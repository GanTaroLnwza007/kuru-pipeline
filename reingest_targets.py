"""Re-ingest specific PDFs that had garbled OCR on the first pass."""
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console

load_dotenv()

from kuru.ingestion.embedder import _get_model
from kuru.scripts.ingest_curriculum import ingest_document, FILE_WORKERS

console = Console(legacy_windows=False)

CAMPUS = "บางเขน"
TARGET_FILES = [
    "ปร.ด._นิเทศศาสตร์ดิจิทัล_2568.pdf",
    "วท.บ._วนศาสตร์_2567.pdf",
    "ปร.ด._นวัตกรรมสิ่งแวดล้อมสรรค์สร้าง_2565.pdf",
    "บธ.บ._การตลาด_(นานาชาติ)_2568.pdf",
    "ปร.ด._วิศวกรรมคอมพิวเตอร์_2566.pdf",
    "ปร.ด._วิทยาศาสตร์สิ่งแวดล้อม_2564.pdf",
    "ปร.ด._วนศาสตร์_(นานาชาติ)_2569.pdf",
    "ปร.ด._วิศวกรรมทรัพยากรน้ำ_2564.pdf",
    "ปร.ด._วิศวกรรมวัสดุ_2569.pdf",
    "ปร.ด._การท่องเที่ยวและการบริการร่วมสมัยอย่างยั่งยืน_2569.pdf",
    "พ.บ._2567.pdf",
    "ภ.บ._2569.pdf",
    "(เดิม_วท.ม._ศาสตร์แห่งแผ่นดินเพื่อการพัฒนาที่ยั่งยืน)_2564.pdf",
    "วท.ม._บูรณาการศาสตร์เพื่อการพัฒนาที่ยั่งยืน_2569.pdf",
]

base_dir = Path("data/raw/curriculum")
docs: list[Path] = []
for fname in TARGET_FILES:
    matches = list(base_dir.rglob(fname))
    if matches:
        docs.append(matches[0])
    else:
        console.print(f"[yellow]Not found: {fname}[/yellow]")

console.print(f"\n[bold]Re-ingesting {len(docs)} files with fixed OCR …[/bold]\n")
console.print("[dim]Loading embedding model …[/dim]")
_get_model()

completed = 0
_start = time.time()
_stop = threading.Event()

def _heartbeat():
    while not _stop.wait(30):
        elapsed = int(time.time() - _start)
        m, s = divmod(elapsed, 60)
        console.print(f"  [dim]... {m:02d}:{s:02d} elapsed, {completed}/{len(docs)} done[/dim]")

threading.Thread(target=_heartbeat, daemon=True).start()

pool = ThreadPoolExecutor(max_workers=FILE_WORKERS)
futures = {pool.submit(ingest_document, p, CAMPUS, False): p for p in docs}
try:
    for future in as_completed(futures):
        status = future.result()
        completed += 1
        tag = "[dim]skip[/dim]" if status["skipped"] else (
            "[red]FAIL[/red]" if status["errors"] else "[green]✓[/green]"
        )
        console.print(
            f"  {tag} [{completed}/{len(docs)}] {status['file'][:55]}"
            + (f" → chunks={status['chunks']}" if not status["skipped"] else "")
            + (f" err={status['errors']}" if status["errors"] else "")
        )
except KeyboardInterrupt:
    _stop.set()
    import os; os._exit(0)

_stop.set()
console.print("\n[bold]Done.[/bold]")
