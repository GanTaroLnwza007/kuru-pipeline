# KUru POC Submission Plan — 01219462

**Course:** Software Engineering for AI-Enabled System (01219462), Kasetsart University  
**Deadline:** 14 May 2026, 23:59 (via Google Classroom)  
**Target:** Complete in 2-3 days (starting May 10)

---

## Core Framing: RAG = The ML Model

| RAG concept | Course concept |
|---|---|
| Embedding selection + chunking strategy | Model architecture |
| chunk_size, overlap, top_k, MIN_SIMILARITY | Hyperparameters |
| RAGAS scores (faithfulness, answer_relevance, context_precision) | Evaluation metrics |
| Ingestion pipeline | Training loop |
| multilingual-e5-base (768-dim, local) | Embedding model |
| Supabase pgvector IVFFlat | Vector store / model storage |
| Gemini Flash Lite | Generator / inference engine |

---

## Day 1 — May 10: Part A Report + B1 Notebook

### Part A — AI-Enabled System Design (PDF report)

**A1.1 — Project Title and Motivation**
- Title: "KUru: KU Curriculum & PLO Navigator"
- Problem: Students cannot efficiently navigate 34 program curricula, PLOs, and TCAS admission requirements spread across scanned PDFs
- Target users: KU prospective and current students
- Why AI: Natural language queries, Thai/English multilingual, multi-intent (PLO vs TCAS vs course requirements) — rule-based lookup is insufficient
- Impact: Students resolve curriculum questions in <5s without reading full PDFs

**A2.1 — System Objectives (MAC)**
- System Goal: Answer ≥80% of curriculum queries correctly (RAGAS faithfulness >0.7)
- Leading Indicator: Retrieval hit rate >70% (relevant chunk in top-5)
- User Outcome: Query resolved in <5s, with cited sources

**A2.2 — AI Component Design**
- Problem AI solves: Semantic retrieval over unstructured Thai/English curriculum text + grounded answer generation
- Model properties: multilingual-e5-base (768-dim, handles Thai), pgvector cosine similarity, Gemini Flash Lite (cheap, fast)
- ML Canvas: inputs=student query, outputs=answer+chunk sources, data=curriculum PDFs, evaluation=RAGAS
- FTA Root failure: "Wrong answer delivered to user"
  - Branch 1: Retrieval miss (chunk too coarse, scanned PDF not OCR'd)
  - Branch 2: Hallucination (generator ignores retrieved context)
  - Branch 3: Empty DB (ingestion failure, 0 chunks for program)
  - Minimum cut set: {retrieval miss} ∧ {no empty-result guard}
  - Mitigations: contextual chunk enrichment, OCR for scanned PDFs, MIN_SIMILARITY=0.35 guard

**A2.3 — User Interaction Design**
- Intelligence experience: Automation (answer appears directly, no user configuration needed)
- Model lives: Cloud (Supabase pgvector + Gemini API via OpenRouter)
- Beyond accuracy: Latency <5s (streaming response), model size irrelevant (API-based), Thai language support critical
- Model composition: Sequential — embedder → pgvector retrieval → Gemini Flash Lite generation

**A2.4 — Feedback Collection and Monitoring**
- Mechanism: Thumbs up/down on each answer stored in `feedback` table in Supabase
- Metrics: RAGAS faithfulness, answer relevance, context precision; retrieval hit rate per program
- Retraining loop: Low-scoring programs trigger re-ingestion with improved chunking config

---

### B1 — Data Exploration Notebook

**File:** `notebooks/B1_data_exploration.ipynb`

Contents:
1. Connect to Supabase, pull `chunks` table
2. Distribution: chunk count per program (bar chart)
3. Distribution: chunk token length (histogram)
4. Coverage heatmap: programs × data types (PLO / courses / TCAS)
5. Scanned vs native PDF breakdown across 34 programs
6. Example raw chunk vs contextually enriched chunk (before/after)
7. Embedding space: 2D UMAP of 200 random chunks colored by program

**Sensitive features / fairness note:** Programs with scanned PDFs have 0 chunks → retrieval always fails → systematic bias against those programs.

---

## Day 2 — May 11: Notebooks B2–B6 + MLflow

### B2 — Model Training Notebook

**File:** `notebooks/B2_model_training.ipynb`

Three experiment configurations to compare:

| Run | chunk_size | overlap | top_k | enrichment | notes |
|-----|-----------|---------|-------|-----------|-------|
| baseline | 500 | 50 | 5 | False | current production config |
| small-chunks | 300 | 75 | 8 | False | finer granularity |
| contextual | 500 | 50 | 5 | True | prepend breadcrumb metadata |

For each config:
1. Re-embed 5 sample programs (not full 34 — saves cost/time)
2. Run 10 test queries (manually written from known curriculum facts)
3. Compute RAGAS scores
4. Log to MLflow

Preprocessing steps to show: PDF → text extraction → chunking → embedding → upsert to pgvector  
Validation: hold-out 5 queries per program (do not use during config selection)

### B3 — Fairness Analysis (section inside B2)

- Per-program RAGAS scores — visualize as heatmap
- Hypothesis: programs with scanned PDFs (0 chunks) score near 0
- Hypothesis: Thai-only programs score lower than bilingual (English query → Thai chunk mismatch)
- Mitigation: OCR pipeline for scanned PDFs (already implemented via OpenRouter)

### B4 — MLflow Tracking

```python
import mlflow

mlflow.set_experiment("kuru-rag-chunking")

for config in configs:
    with mlflow.start_run(run_name=config["name"]):
        mlflow.log_params({
            "chunk_size": config["chunk_size"],
            "overlap": config["overlap"],
            "top_k": config["top_k"],
            "enrichment": config["enrichment"],
            "embedding_model": "multilingual-e5-base",
        })
        mlflow.log_metrics({
            "faithfulness": ...,
            "answer_relevance": ...,
            "context_precision": ...,
            "avg_retrieval_score": ...,
        })
```

**Required artifact:** Screenshot of MLflow Tracking UI comparison table (PNG/JPG)

### B5 — Explainability Notebook

**File:** `notebooks/B5_explainability.ipynb`

- "Feature importance" = cosine similarity scores of retrieved chunks
- For a given query: bar chart of top-5 chunks with similarity scores
- Aggregated: which section types (PLO / courses / admission) are retrieved most often
- Interpret: high-scoring PLO chunks for PLO queries validates retrieval is topic-aware

### B6 — Prediction Reasoning Notebook

**File:** `notebooks/B6_prediction_reasoning.ipynb`

Three test cases (distinct query types):
1. PLO question: "What are the learning outcomes for SKE program?"
2. TCAS question: "What are the TCAS round 3 requirements for CPE?"
3. Course requirement: "How many credits does the SKE program require?"

For each:
- Show retrieved chunks (top-5) with similarity scores = evidence (SHAP-equivalent)
- Show final generated answer
- Annotate which sentence in the answer is grounded by which chunk (source attribution)
- Ensures output is interpretable to non-technical users

---

## Day 3 — May 12: B7 + Part C + Slides + Video

### B7 — Deployment as Service

**File:** `notebooks/B7_deployment.ipynb`

The existing FastAPI backend IS the deployed service:

```
POST /api/chat
Content-Type: application/json

Request:  { "query": string, "program_id": string | null }
Response: { "answer": string, "sources": [...], "confidence": float }
```

Tasks:
1. Document all API endpoints with request/response schemas
2. Wrap query engine in `mlflow.pyfunc.PythonModel` for the model artifact
3. Log embedding model path + chunking config as MLflow artifacts (`MLmodel` file)
4. Scalability discussion: Supabase horizontal DB scaling, Gemini API rate limits, caching strategy

**Required files:** `MLmodel` + `model.pkl` or equivalent (config JSON + embedding model reference)

---

### Part C — UI-Model Interface

**C1 — UI Design**
- Use existing React chat UI screenshots
- Annotate: where answer appears, where source citations show (= confidence signal), thumbs up/down feedback button

**C2 — Interface Design**

Request schema:
```json
{
  "query": "string (required)",
  "program_id": "string | null (optional, filters retrieval)"
}
```

Response schema:
```json
{
  "answer": "string",
  "sources": [{ "chunk_id": "uuid", "program": "string", "section": "string", "similarity": float }],
  "confidence": "float (avg similarity of top chunks)"
}
```

Sequence diagram: User → React UI → FastAPI `/api/chat` → pgvector retrieval → Gemini Flash Lite → FastAPI → React UI

**C3 — Interface Testing**

Postman collection with 3 scenarios:
1. PLO query (no program_id filter)
2. TCAS query with program_id filter
3. Invalid query (empty string) → 422 error handling

---

### Slides (PDF)

1. Problem statement + target users
2. System architecture diagram (React → FastAPI → pgvector → Gemini)
3. RAG pipeline diagram (query → embed → retrieve → generate)
4. MLflow comparison table (3 configs, RAGAS scores)
5. Key design decisions (multilingual-e5, chunk enrichment, OpenRouter OCR)
6. Limitations + future work (RAGAS-driven retraining, hybrid BM25 search)

### Video (5-7 min)

1. Show the chat UI live
2. Ask 3 queries (PLO, TCAS, course credits)
3. Show source citations in response
4. Show MLflow UI comparison table
5. Brief code walkthrough of RAG pipeline

---

## Critical Path Risks

| Risk | Mitigation |
|------|-----------|
| RAGAS needs labeled test set (10-20 Q&A pairs) | Write manually from known curriculum facts on Day 1 alongside Part A |
| `ragas` + `datasets` packages not installed | `uv add ragas datasets` in pipeline venv |
| Scanned PDFs have 0 chunks → B1 notebook looks broken | Run `uv run kuru-ingest-mko` before Day 2 (stop backend first to free .venv lock) |
| MLflow model artifact complex to implement | Minimum: log embedding model dir + config.json as artifacts; skip full pyfunc if tight on time |
| RAGAS requires OpenAI-compatible LLM judge | Configure RAGAS to use Gemini via OpenAI-compat client (already set up in llm.py) |

---

## Full Deliverable Checklist

| # | Deliverable | Format | Day | Done |
|---|-------------|--------|-----|------|
| 1 | Part A PDF report | PDF | 1 | [ ] |
| 2 | B1_data_exploration.ipynb | .ipynb | 1 | [ ] |
| 3 | B2_model_training.ipynb (includes B3 fairness) | .ipynb | 2 | [ ] |
| 4 | MLflow comparison screenshots | PNG/JPG | 2 | [ ] |
| 5 | B5_explainability.ipynb | .ipynb | 2 | [ ] |
| 6 | B6_prediction_reasoning.ipynb | .ipynb | 2 | [ ] |
| 7 | B7_deployment.ipynb + MLmodel artifact | .ipynb + files | 3 | [ ] |
| 8 | Part C PDF (UI design + interface docs) | PDF | 3 | [ ] |
| 9 | Postman collection / API test screenshots | PNG/JPG | 3 | [ ] |
| 10 | Video demo | video file | 3 | [ ] |
| 11 | Slides PDF | PDF | 3 | [ ] |
| 12 | GitHub repo with README + requirements.txt | GitHub | 3 | [ ] |

---

## Package Dependencies to Add

```bash
cd kuru/pipeline
uv add ragas datasets mlflow
```

RAGAS needs an LLM judge — configure it to use the existing Gemini client in `llm.py`.
