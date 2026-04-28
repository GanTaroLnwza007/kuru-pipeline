"""Sample chunks per program and score quality — decides which programs to keep vs re-ingest.

Usage:
    $env:PYTHONUTF8=1; uv run python audit_chunks.py
"""
from __future__ import annotations

import random
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
from rich.console import Console
from rich.table import Table

load_dotenv()

from kuru.db import supabase_client as db
from kuru.ingestion.text_extractor import _is_garbage_line

console = Console(legacy_windows=False)

SAMPLES_PER_PROGRAM = 8
SUSPECT_RATIO_THRESHOLD = 0.30      # >30% suspect chunks → program is SUSPECT
FAIL_RATIO_THRESHOLD = 0.60         # >60% suspect chunks → program is FAIL


def _score_chunk(content: str) -> dict:
    """Return per-chunk quality metrics."""
    lines = [ln for ln in content.splitlines() if ln.strip()]
    total = len(lines) or 1
    garbage = sum(1 for ln in lines if _is_garbage_line(ln.strip()))

    chars = content.strip()
    n = len(chars)
    if n == 0:
        return {"empty": True, "garbage_ratio": 0.0, "alnum_ratio": 0.0, "suspect": True}

    # Fraction of alphanumeric / Thai chars vs noise (punctuation/whitespace)
    meaningful = sum(1 for c in chars if c.isalnum() or "฀" <= c <= "๿")
    alnum_ratio = meaningful / n

    garbage_ratio = garbage / total
    suspect = (
        garbage_ratio > 0.4         # too many garbage lines
        or alnum_ratio < 0.4        # mostly punctuation/whitespace
        or n < 100                  # implausibly short for a curriculum chunk
    )
    return {
        "empty": False,
        "garbage_ratio": garbage_ratio,
        "alnum_ratio": alnum_ratio,
        "char_count": n,
        "suspect": suspect,
    }


def _classify(suspect_ratio: float) -> str:
    if suspect_ratio >= FAIL_RATIO_THRESHOLD:
        return "FAIL"
    if suspect_ratio >= SUSPECT_RATIO_THRESHOLD:
        return "SUSPECT"
    return "PASS"


def main() -> None:
    client = db.get_client()
    console.print("[bold]Loading program list …[/bold]")
    programs = client.table("programs").select("id,name_th").execute().data
    console.print(f"  {len(programs)} programs in DB\n")

    results: list[dict] = []
    rng = random.Random(42)

    for i, prog in enumerate(programs, 1):
        pid = prog["id"]
        name = prog.get("name_th") or pid

        # Get total count first to sample randomly
        count_res = client.table("chunks").select("id", count="exact").eq("program_id", pid).limit(1).execute()
        total = count_res.count or 0
        if total == 0:
            results.append({"name": name, "total": 0, "verdict": "EMPTY", "suspect_ratio": 0.0, "samples": 0})
            console.print(f"  [{i}/{len(programs)}] [yellow]EMPTY[/yellow]  {name[:50]}  (0 chunks)")
            continue

        # Random offsets
        n_samples = min(SAMPLES_PER_PROGRAM, total)
        offsets = sorted(rng.sample(range(total), n_samples)) if total >= n_samples else list(range(total))

        sampled_scores = []
        for off in offsets:
            r = client.table("chunks").select("content").eq("program_id", pid).range(off, off).limit(1).execute()
            if r.data:
                sampled_scores.append(_score_chunk(r.data[0]["content"]))

        suspect_count = sum(1 for s in sampled_scores if s["suspect"])
        suspect_ratio = suspect_count / len(sampled_scores) if sampled_scores else 1.0
        verdict = _classify(suspect_ratio)

        avg_garbage = sum(s["garbage_ratio"] for s in sampled_scores) / max(len(sampled_scores), 1)
        avg_alnum = sum(s["alnum_ratio"] for s in sampled_scores) / max(len(sampled_scores), 1)

        results.append({
            "name": name,
            "total": total,
            "verdict": verdict,
            "suspect_ratio": suspect_ratio,
            "avg_garbage": avg_garbage,
            "avg_alnum": avg_alnum,
            "samples": len(sampled_scores),
        })

        color = {"PASS": "green", "SUSPECT": "yellow", "FAIL": "red"}[verdict]
        console.print(
            f"  [{i}/{len(programs)}] [{color}]{verdict:7}[/{color}] {name[:50]:50} "
            f"chunks={total:5}  suspect={suspect_count}/{len(sampled_scores)}  garb={avg_garbage:.2f}  alnum={avg_alnum:.2f}"
        )

    # ── Final summary ─────────────────────────────────────────────────────
    console.print("\n[bold]Audit Summary[/bold]")
    by_verdict = defaultdict(list)
    for r in results:
        by_verdict[r["verdict"]].append(r)

    table = Table(show_header=True)
    table.add_column("Verdict")
    table.add_column("Count", justify="right")
    table.add_column("% of programs", justify="right")
    for v in ("PASS", "SUSPECT", "FAIL", "EMPTY"):
        n = len(by_verdict[v])
        pct = 100 * n / len(results) if results else 0
        table.add_row(v, str(n), f"{pct:.1f}%")
    console.print(table)

    # Decision hint
    pass_pct = 100 * len(by_verdict["PASS"]) / len(results) if results else 0
    fail_pct = 100 * (len(by_verdict["FAIL"]) + len(by_verdict["EMPTY"])) / len(results) if results else 0

    console.print()
    if pass_pct >= 80:
        console.print(f"[green]→ {pass_pct:.0f}% PASS — keep existing chunks, only ingest the remaining files[/green]")
    elif fail_pct >= 20:
        console.print(f"[red]→ {fail_pct:.0f}% FAIL/EMPTY — recommend wipe + full re-ingest with stronger OCR model[/red]")
    else:
        console.print(f"[yellow]→ Mixed results — review SUSPECT programs individually[/yellow]")

    # Print failures explicitly
    if by_verdict["FAIL"] or by_verdict["EMPTY"]:
        console.print("\n[bold]FAIL / EMPTY programs:[/bold]")
        for r in by_verdict["FAIL"] + by_verdict["EMPTY"]:
            console.print(f"  - {r['name']}  (chunks={r['total']})")


if __name__ == "__main__":
    main()
