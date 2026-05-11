# Handoff Notes — KUru AI-Enabled Project (B5 status)

Date: 11 May 2026

These notes summarize the current status, alignments with course criteria, and next actions for the B5 stage and onward.

## Project summary

- **Project:** KUru — KU Curriculum & PLO Navigator
- **Core AI approach:** RAG pipeline (embed → retrieve → generate)
- **Backend:** FastAPI + Supabase pgvector + Gemini Flash Lite (OpenRouter)
- **Frontend:** React chat UI (sources + feedback)

## Current status (B5 stage)

### Completed/available

- **B2 experiments completed** (3 configs):
  - Artifacts:
    - `data/eval_results_exp1.csv`
    - `data/eval_results_exp2.csv`
    - `data/eval_results_exp3.csv`
    - `docs/figures/B2_experiment_comparison.png`
    - `docs/figures/B2_score_distribution.png`
    - `docs/figures/B2_score_by_qtype.png`
  - MLflow runs stored in `mlruns/` (experiment name used in plan: `kuru-rag-hyperparameter-search`)
- **B3 fairness findings** noted in summary (section-type disparity, scanned PDF bias)
- **B4 guide created:** `kuru/docs/B4_MLflow_Run_and_Screenshots.md`

### In progress / next up

- **B4 MLflow screenshots** still pending (Tracking UI images)
- **B5 Explainability notebook** to implement and save results

## Criteria alignment (poc_criteria.md vs plan)

The submission plan in `docs/poc_submission_plan.md` aligns with all required parts A/B/C.

Key watch-outs:

- **B2 “training loop”**: ensure notebook explains RAG ingestion + evaluation as the training/validation loop.
- **B5 explainability**: similarity scores must be framed as interpretable signals (proxy for feature importance) with clear visuals.
- **B7 model artifact**: criteria require `MLmodel` + `model.pkl` (or equivalent). Consider a minimal MLflow pyfunc wrapper to satisfy this.
- **AI usage disclosure**: must be included in final report PDF.

## What Claude agent should do next (priority order)

1. **Create MLflow screenshots (B4)**
   - Start UI in `kuru/pipeline`:
     - `mlflow ui --backend-store-uri ./mlruns --port 5000`
   - Capture:
     - Experiments list
     - Single run overview
     - Artifacts tab
     - Metrics/params comparison
   - Save to `kuru/docs/figures/` as:
     - `B4_mlflow_experiments_list.png`
     - `B4_mlflow_run_overview.png`
     - `B4_mlflow_artifacts.png`
     - `B4_mlflow_metrics_comparison.png`

2. **Finish B5 explainability notebook**
   - File: `notebooks/B5_explainability.ipynb`
   - Required visuals:
     - Bar chart of top-5 retrieved chunks with similarity scores per query
     - Aggregate chart of section types retrieved most often (PLO/courses/admission)
   - Interpretation: explain how higher similarity scores indicate evidence strength.

3. **Finish B6 prediction reasoning notebook**
   - File: `notebooks/B6_prediction_reasoning.ipynb`
   - Include 3 test cases with retrieved chunks + answer + source mapping.

4. **Implement B7 MLflow model artifact (minimum compliance)**
   - File: `notebooks/B7_deployment.ipynb`
   - Output: `MLmodel` + `model.pkl` (or equivalent) saved in repo.

## Known issues / risks

- Some programs have **0 chunks** (scanned PDF extraction issues) → retrieval fails, fairness bias.
- MLflow UI command previously exited with code 1 in terminal; retry from `kuru/pipeline` and confirm `mlflow` is installed in venv.
- **B2 training framing risk:** current B2 flow is RAG ingestion + evaluation, not a traditional training loop. The notebook must explicitly justify this as the “training/validation loop” (or add a minimal supervised training component) to satisfy the rubric.

## Helpful file map

- **Criteria:** `kuru/pipeline/docs/poc_criteria.md`
- **Plan:** `kuru/pipeline/docs/poc_submission_plan.md`
- **B2 notebook:** `kuru/pipeline/notebooks/B2_model_training.ipynb`
- **B5 notebook:** `kuru/pipeline/notebooks/B5_explainability.ipynb`
- **B6 notebook:** `kuru/pipeline/notebooks/B6_prediction_reasoning.ipynb`
- **B7 notebook:** `kuru/pipeline/notebooks/B7_deployment.ipynb`
- **Figures:** `kuru/pipeline/docs/figures/`

## Minimal environment notes

- If packages missing, add via:
  - `uv add ragas datasets mlflow`
- RAGAS judge uses Gemini (OpenAI-compatible client) per `llm.py`.

---

This handoff captures B5 status and next steps to satisfy the official criteria.
