"""One-shot script: re-log existing experiment results to MLflow with SQLite backend.

Reads eval_results_exp1/2/3.csv (already produced by B2 notebook Section 4)
and re-logs them to a fresh SQLite-backed MLflow store.

Usage:
    uv run python scripts/migrate_mlflow_to_sqlite.py
"""
import csv
from pathlib import Path

import mlflow

DATA_DIR = Path("data")
CSV_FILES = {
    "baseline":         DATA_DIR / "eval_results_exp1.csv",
    "wider_retrieval":  DATA_DIR / "eval_results_exp2.csv",
    "strict_threshold": DATA_DIR / "eval_results_exp3.csv",
}

ARCHITECTURE = {
    "embed_model":       "intfloat/multilingual-e5-base",
    "embed_dim":         768,
    "embed_prefix_doc":  "passage:",
    "embed_prefix_query": "query:",
    "index_type":        "IVFFlat",
    "index_probes":      50,
    "chunk_size":        2000,
    "chunk_overlap":     200,
    "fetch_multiplier":  3,
    "generator_model":   "google/gemini-2.5-flash-lite",
    "reranker":          "pythainlp-token-overlap",
    "total_chunks":      18027,
    "total_programs":    66,
}

EXPERIMENT_CONFIG = {
    "baseline":         {"top_k": 5,  "min_similarity": 0.35, "description": "Production defaults: top_k=5, MIN_SIMILARITY=0.35"},
    "wider_retrieval":  {"top_k": 8,  "min_similarity": 0.30, "description": "Wider context: top_k=8 + softer threshold (0.30)"},
    "strict_threshold": {"top_k": 5,  "min_similarity": 0.45, "description": "Stricter filter: top_k=5, MIN_SIMILARITY=0.45"},
}

SAMPLE_SIZE = 20
RANDOM_SEED = 42


def main() -> None:
    DB_URI = "sqlite:///mlflow.db"
    mlflow.set_tracking_uri(DB_URI)
    mlflow.set_experiment("kuru-rag-hyperparameter-search")

    print(f"Backend: {DB_URI}")
    print()

    for run_name, csv_path in CSV_FILES.items():
        if not csv_path.exists():
            print(f"SKIP {run_name}: {csv_path} not found")
            continue

        cfg = EXPERIMENT_CONFIG[run_name]

        # Read CSV
        with open(csv_path, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))

        scores = [int(r["score"]) for r in rows if str(r.get("score", "")).lstrip("-").isdigit() and int(r["score"]) >= 0]

        if not scores:
            print(f"SKIP {run_name}: no valid scores")
            continue

        avg_score = sum(scores) / len(scores)
        dist = {s: scores.count(s) for s in range(4)}
        pct_good = (dist[2] + dist[3]) / len(scores) * 100
        avg_top_sim = sum(float(r.get("top_similarity", 0) or 0) for r in rows) / len(rows)
        avg_n_chunks = sum(int(r.get("n_chunks_returned", 0) or 0) for r in rows) / len(rows)

        # Breakdown by question_type
        by_type: dict[str, list[int]] = {}
        for r in rows:
            s = int(r["score"])
            if s < 0:
                continue
            qt = r.get("question_type", "unknown")
            by_type.setdefault(qt, []).append(s)

        with mlflow.start_run(run_name=run_name) as run:
            mlflow.log_params({
                "top_k":            cfg["top_k"],
                "min_similarity":   cfg["min_similarity"],
                "fetch_multiplier": ARCHITECTURE["fetch_multiplier"],
                "embed_model":      ARCHITECTURE["embed_model"],
                "embed_dim":        ARCHITECTURE["embed_dim"],
                "generator_model":  ARCHITECTURE["generator_model"],
                "chunk_size":       ARCHITECTURE["chunk_size"],
                "chunk_overlap":    ARCHITECTURE["chunk_overlap"],
                "index_type":       ARCHITECTURE["index_type"],
                "index_probes":     ARCHITECTURE["index_probes"],
                "reranker":         ARCHITECTURE["reranker"],
                "sample_size":      SAMPLE_SIZE,
                "random_seed":      RANDOM_SEED,
                "description":      cfg["description"],
            })

            metrics = {
                "avg_score":              round(avg_score, 3),
                "pct_good":               round(pct_good, 1),
                "n_score_3":              dist[3],
                "n_score_2":              dist[2],
                "n_score_1":              dist[1],
                "n_score_0":              dist[0],
                "n_valid":                len(scores),
                "avg_top_similarity":     round(avg_top_sim, 4),
                "avg_n_chunks_returned":  round(avg_n_chunks, 2),
            }
            for qt, sc in by_type.items():
                metrics[f"avg_score_{qt}"] = round(sum(sc) / len(sc), 3)

            mlflow.log_metrics(metrics)
            mlflow.log_artifact(str(csv_path), artifact_path="eval_results")

            print(f"[{run_name}]  run_id={run.info.run_id}  avg={avg_score:.2f}  good={pct_good:.0f}%  "
                  f"dist=3:{dist[3]} 2:{dist[2]} 1:{dist[1]} 0:{dist[0]}")

    print()
    print(f"Done. Start UI: mlflow ui --backend-store-uri {DB_URI}")


if __name__ == "__main__":
    main()