# -*- coding: utf-8 -*-
"""Run RAG evaluation against a golden eval set using LLM-as-judge.

Usage:
    uv run python scripts/run_eval.py --eval data/eval_set.csv
    uv run python scripts/run_eval.py --eval data/eval_set.csv --out data/eval_results.csv --sample 20

Output CSV columns:
    question, ground_truth_answer, rag_answer, score, reasoning,
    question_type, source_file, program_id, section_type, sources_used
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv

load_dotenv()

from kuru.llm import GENERATION_MODEL, get_openrouter_client, session_usage
from kuru.rag.query_engine import query

# ── Judge prompt ─────────────────────────────────────────────────────────────

_JUDGE_SYSTEM = """You are an expert evaluator for a Thai university RAG chatbot.
Score the RAG answer against the ground truth on a 0–3 scale:

3 = Correct and complete: answer covers the key facts in ground truth
2 = Partially correct: answer contains the main point but misses details, or has minor errors
1 = Tangentially related: answer is on-topic but does not address the question correctly
0 = Wrong or hallucinated: answer contradicts ground truth or invents facts

Output valid JSON only — no markdown, no explanation:
{"score": <0|1|2|3>, "reasoning": "<one short sentence>"}"""

_JUDGE_USER = """Question: {question}

Ground truth: {ground_truth}

RAG answer: {rag_answer}"""


def _judge(question: str, ground_truth: str, rag_answer: str) -> tuple[int, str]:
    """Call LLM judge. Returns (score 0-3, reasoning)."""
    prompt = _JUDGE_USER.format(
        question=question, ground_truth=ground_truth, rag_answer=rag_answer
    )
    try:
        response = get_openrouter_client().chat.completions.create(
            model=GENERATION_MODEL,
            messages=[
                {"role": "system", "content": _JUDGE_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=200,
        )
        if response.usage:
            session_usage.add(GENERATION_MODEL, response.usage)
        raw = (response.choices[0].message.content or "").strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
        return int(parsed["score"]), str(parsed.get("reasoning", ""))
    except Exception as exc:
        return -1, f"judge error: {exc}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate RAG against golden eval set")
    parser.add_argument("--eval", default="data/eval_set.csv", help="Input eval CSV")
    parser.add_argument("--out", default="data/eval_results.csv", help="Output results CSV")
    parser.add_argument("--sample", type=int, default=0, help="Randomly sample N rows (0=all)")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between queries")
    args = parser.parse_args()

    eval_path = Path(args.eval)
    if not eval_path.exists():
        print(f"ERROR: eval file not found: {eval_path}")
        sys.exit(1)

    with open(eval_path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    if args.sample and args.sample < len(rows):
        import random
        random.seed(42)
        rows = random.sample(rows, args.sample)

    print(f"Evaluating {len(rows)} questions from {eval_path}\n")

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "question", "ground_truth_answer", "rag_answer", "score", "reasoning",
        "question_type", "source_file", "program_id", "section_type", "sources_used",
    ]

    scores: list[int] = []
    results: list[dict] = []

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()

        for i, row in enumerate(rows):
            question = row["question"]
            ground_truth = row["ground_truth_answer"]
            q_type = row.get("question_type", "")
            section = row.get("section_type", "")

            print(f"  [{i+1}/{len(rows)}] {question[:60]:60s}", end=" ", flush=True)

            # RAG answer — pass program_id so retrieval targets the right program
            program_id = row.get("program_id") or None
            try:
                rag_result = query(question, program_id=program_id)
                rag_answer = rag_result.answer
                sources_used = "|".join(
                    s.get("source_file", "") for s in rag_result.sources[:3]
                )
            except Exception as exc:
                rag_answer = f"[RAG error: {exc}]"
                sources_used = ""

            # Judge
            score, reasoning = _judge(question, ground_truth, rag_answer)
            scores.append(score)

            label = {3: "✓✓", 2: "✓ ", 1: "~ ", 0: "✗ ", -1: "??"}.get(score, "??")
            print(f"→ {label} {score}  (~${session_usage.estimated_cost_usd:.4f})")

            out_row = {
                "question": question,
                "ground_truth_answer": ground_truth,
                "rag_answer": rag_answer,
                "score": score,
                "reasoning": reasoning,
                "question_type": q_type,
                "source_file": row.get("source_file", ""),
                "program_id": row.get("program_id", ""),
                "section_type": section,
                "sources_used": sources_used,
            }
            writer.writerow(out_row)
            f.flush()
            results.append(out_row)

            if args.delay and i < len(rows) - 1:
                time.sleep(args.delay)

    # Summary
    valid_scores = [s for s in scores if s >= 0]
    if valid_scores:
        avg = sum(valid_scores) / len(valid_scores)
        dist = {s: valid_scores.count(s) for s in range(4)}
        pct_good = (dist[3] + dist[2]) / len(valid_scores) * 100
        print(f"\n{'─'*60}")
        print(f"Results: {len(valid_scores)} scored, {scores.count(-1)} errors")
        print(f"Average score:  {avg:.2f} / 3.0")
        print(f"Good answers:   {pct_good:.0f}%  (score 2-3)")
        print(f"Distribution:   3={dist[3]}  2={dist[2]}  1={dist[1]}  0={dist[0]}")
        print(f"API usage:      {session_usage.summary()}")
        print(f"Output:         {out_path}")

        # Breakdown by question type
        by_type: dict[str, list[int]] = {}
        for r in results:
            t = r["question_type"] or "unknown"
            by_type.setdefault(t, []).append(int(r["score"]) if str(r["score"]).lstrip("-").isdigit() else -1)
        if len(by_type) > 1:
            print(f"\nBy question type:")
            for t, sc in sorted(by_type.items()):
                vs = [s for s in sc if s >= 0]
                if vs:
                    print(f"  {t:12s}  avg={sum(vs)/len(vs):.2f}  n={len(vs)}")


if __name__ == "__main__":
    main()
