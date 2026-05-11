# Part A — AI System Design Report
**Course:** 01219462 — Software Engineering for AI-Enabled System  
**Project:** KUru: KU Curriculum & PLO Navigator  
**Team:** Thanawat Tantijaroensin (6610545294), Phantawat Luengsiriwattana (6610545871)  
**Role Assignment:** Thanawat Tantijaroensin — Data Scientist (embedding model selection, chunking strategy, RAG pipeline design, evaluation framework) | Phantawat Luengsiriwattana — Software Engineer (ingestion pipeline, FastAPI backend, Supabase schema, deployment)  
**Date:** May 2026

---

## A1 — Project Identification

### A1.1 Project Title and Justification

**Title:** KUru: KU Curriculum & PLO Navigator

**Problem domain and target users:** Kasetsart University (KU) prospective students — high school leavers preparing for TCAS applications — need to query specific information about KU programs: credit requirements, course structure, Program Learning Outcomes (PLOs), and admission criteria. This information exists in official มคอ.2 curriculum documents: 20–100 page formal Thai-language PDFs, one per program. Students currently must read them manually. There is no searchable interface.

**Why AI/ML is essential — why rule-based is insufficient:**
1. **Vocabulary mismatch** — students ask in colloquial Thai or English; PDFs use formal academic Thai terminology. Exact keyword matching cannot bridge this gap (e.g., "เรียนอะไรบ้าง" vs. "โครงสร้างหลักสูตร").
2. **Cross-lingual retrieval** — the student population queries in both Thai and English, but all curriculum documents are in Thai. A rule-based system has no mechanism for cross-language matching.
3. **Synthesis across sections** — questions like "What are the minimum credits for general education in Computer Engineering?" require combining a credit table, a section header, and program identity from different parts of the document. Keyword search returns fragments; an LLM synthesises them into a coherent answer.

**Expected impact:** Students can resolve curriculum and admission questions in under 5 seconds through natural language, without downloading or reading PDFs. This reduces the information barrier to informed TCAS program selection across 66+ KU programs.

---

## A2 — AI System Design

### A2.1 System Objectives

**System goal:** Enable KU prospective students to get accurate, grounded answers about curriculum content and TCAS admission requirements through natural language queries in Thai or English.

The following objectives satisfy the MAC criteria: each metric is **Measurable** (has a defined collection method), **Achievable** (based on current system benchmarks and eval results), and **Communicable** (expressed in terms meaningful to both technical and non-technical stakeholders).

| Level | Metric | Target | How Measured |
|-------|--------|--------|--------------|
| System goal | Good-answer rate (LLM-as-judge score ≥2/3) | ≥80% | Offline eval set, 20-question sample per run |
| Leading indicator | Retrieval hit rate | ≥70% | Fraction of eval queries where correct chunk appears in top-k |
| User outcome | Query resolved without follow-up | ≥80% of sessions | Thumbs-up rate in production feedback table |
| System quality | End-to-end response latency | ≤5 seconds | Measured per request in FastAPI middleware |
| Coverage | Programs queryable | ≥30 programs | Chunk count > 0 per program in Supabase |

**Current status (eval set v3, n=20 questions):**
- Good-answer rate: 65% (target: 80%)
- Average LLM-as-judge score: 1.80 / 3.0
- Admission questions avg: 1.83 | Curriculum questions avg: 1.79

---

### A2.2 AI Component Design

#### A2.2.1 — Problem AI Is Used to Solve

The system uses AI to solve two specific sub-problems:

1. **Semantic retrieval across a multilingual document corpus** — given a Thai or English question, find the most relevant passages from มคอ.2 PDFs across 66 programs. This cannot be solved with keyword search due to vocabulary and language gaps.

2. **Answer synthesis and grounding** — given retrieved passages, generate a fluent, accurate answer that cites its sources and does not hallucinate beyond the provided context. This requires an LLM with a strict citation-grounded prompt.

#### A2.2.2 — Goals, Indicators, Outcomes, and Model Properties

| Property | Measure | Data Collection | Operationalization |
|----------|---------|-----------------|-------------------|
| **Correctness** (system goal) | LLM-as-judge score 0–3 per question | Run `scripts/run_eval.py` against 20-question sample from 50-question synthetic eval set | Score ≥2 = "good answer"; target ≥80% of sample |
| **Retrieval hit rate** (leading indicator) | Fraction of eval queries where ground-truth answer is in top-k chunks | Compare retrieved chunks against ground-truth answer in eval CSV | Hit if judge scores ≥2; target ≥70% |
| **User satisfaction** (user outcome) | Thumbs-up / thumbs-down ratio per program | `feedback` table in Supabase, written on each user rating | Negative rate >30% per program triggers re-ingestion review |
| **Latency** (system quality) | Time from query received to response returned (ms) | FastAPI middleware logs per-request timing | p95 ≤ 5,000ms; alert if p95 > 8,000ms |
| **Coverage** (system quality) | Number of programs with chunk_count > 100 | Daily query: `SELECT COUNT(*) FROM chunks GROUP BY program_id` | Target ≥30 programs above threshold |
| **Hallucination rate** (model property) | Fraction of answers containing claims not in retrieved chunks | LLM-as-judge secondary prompt asking "Is this answer grounded in the provided passages?" | Target <10% hallucination rate |

#### A2.2.3 — ML Canvas

| Field | Detail |
|-------|--------|
| **Prediction task** | Given a natural language question (Thai/English) and optional program scope, retrieve relevant passage(s) from มคอ.2 curriculum documents and generate a grounded, cited answer |
| **Input** | User question text (Thai or English); optional program_id filter |
| **Output** | Generated answer text with inline source citations (source file + section type) |
| **Training data / corpus** | 18,027 document chunks from 66 KU programs at บางเขน campus. Ingestion = "training loop": chunking strategy and embedding model selection are the architecture decisions; chunk_size, overlap, top_k, MIN_SIMILARITY are the hyperparameters tuned across experiments |
| **Features** | 768-dimensional dense embeddings (intfloat/multilingual-e5-base) with asymmetric prefixes: `passage:` for documents, `query:` for queries |
| **Model — retriever** | IVFFlat pgvector index, cosine similarity, probes=50, fetch 3×top_k then re-rank |
| **Model — generator** | Google Gemini 2.5 Flash Lite via google-genai SDK; strict citation-grounded prompt |
| **Hyperparameters** | chunk_size=2000 chars, overlap=200 chars, top_k=5, IVFFlat probes=50 |
| **Evaluation metric** | LLM-as-judge score (0–3 scale), good-answer rate (score ≥2), split by question type (admission / curriculum) |
| **Offline evaluation** | 50-question synthetic eval set generated from actual Supabase chunks; 20 sampled per run with fixed seed |
| **Online feedback** | Thumbs up/down → `feedback` table → flags low-coverage programs for re-ingestion |
| **Known limitations** | Credit tables not extracted as structured text (fragmented by PyMuPDF); ambiguous program names ("นานาชาติ") cause resolution failures; กำแพงแสน / ศรีราชา campuses not yet ingested |

#### A2.2.4 — Fault Tree Analysis (FTA)

**Top-level undesired event:** User receives a wrong or unhelpful answer

Failure categories per node:
- **REQ** = failure originating from missing or incorrect requirements/data
- **ENV** = failure from the operating environment (infrastructure, external APIs)
- **SPEC** = failure from incorrect system design or implementation

```
Wrong/unhelpful answer  [TOP]
│
├── [OR] Retrieval failure — correct chunks not in top-k
│   ├── [REQ] Program not ingested — no chunks exist in DB for this program
│   ├── [SPEC] Query-document vocabulary mismatch — embedding space gap between
│   │          colloquial question and formal academic document text
│   └── [SPEC] program_id not resolved — wrong program's chunks retrieved
│              because name_th is ambiguous or missing
│
├── [OR] Generation failure — correct chunks retrieved but wrong answer produced
│   ├── [SPEC] LLM hallucination — model generates claims beyond retrieved context
│   ├── [REQ]  Retrieved chunks lack sufficient detail — sparse program coverage
│   │          (< 100 chunks; TCAS booklet used instead of full มคอ.2)
│   └── [REQ]  Tabular data not in chunk text — credit tables extracted as
│              fragmented cell text by PyMuPDF, losing row/column structure
│
└── [OR] Guard failure — system should return "no data" but calls LLM instead
    ├── [SPEC] Empty-result guard not triggered — chunks list is non-empty but
    │          irrelevant; LLM hallucinates from wrong context
    └── [ENV]  TCAS records missing — query routed to tcas_records table
               but no records exist for this program/round
```

**Minimum cut sets:**

| Cut Set | Failure | Category | Mitigation Implemented |
|---------|---------|----------|----------------------|
| MCS-1 | Program not ingested | REQ | Ingestion pipeline with chunk-count monitoring; flagging programs with <50 chunks |
| MCS-2 | program_id resolution failure | SPEC | Token-based name matching on name_th + name_en; program_id passed explicitly in eval |
| MCS-3 | LLM hallucination | SPEC | System prompt: "only answer using information from the provided passages"; no-LLM guard when context empty |
| MCS-4 | No empty-result guard | SPEC | `if not chunks and not tcas_records: return hardcoded "no data" message` — LLM never called |
| MCS-5 | Tabular data loss | REQ | Identified as root cause of 3/20 eval failures; proposed fix: table-aware chunking with PyMuPDF `find_tables()` |

---

### A2.3 User Interaction Design (Intelligence Experiences)

#### A2.3.1 — Intelligence Experience Design

**Approach: Automation with inline transparency**

The system uses full automation — the user types a question and receives a generated answer without any intermediate steps or manual review. This is appropriate because:
- The target users (prospective students) expect a conversational interface, not a search results list
- Response latency ≤5s makes automation viable without frustrating waits
- The risk of a wrong answer is low-stakes (curriculum browsing, not medical or legal advice)

**How intelligence is presented to the user:**

| Element | Design decision | Rationale |
|---------|----------------|-----------|
| Answer text | Direct prose answer in the user's query language (Thai or English) | Matches conversational expectation; no raw chunk dumps |
| Source citations | Inline badges showing source filename and section type after each claim | Allows user to verify; reduces blind trust in generated text |
| Confidence signal | If no relevant chunks found, system returns a fixed "ไม่พบข้อมูล" message instead of generating | Honest uncertainty > hallucinated confidence |
| Feedback | Thumbs up / thumbs down below each response | Simple, low-friction; actionable signal for monitoring |
| Coverage note | If program has known data gaps (e.g., no PLO sections), a note is injected: "PLO information not available for this program" | Sets correct expectations before the user asks follow-ups |

**What is NOT shown to the user:** raw chunk text, similarity scores, program_id, embedding vectors. These are internal pipeline details that add noise without benefit to a student user.

#### A2.3.2 — Where the Model Lives

**Hybrid deployment: local embedding + cloud LLM**

| Component | Location | Justification |
|-----------|----------|---------------|
| Embedding model (intfloat/multilingual-e5-base, 768-dim) | **Local** — runs on the backend server process | Gemini embedding API has a 1,000 requests/day free quota — far too low for production. Local inference costs ~50ms per query with no quota constraint |
| Vector index (pgvector IVFFlat) | **Cloud** — Supabase managed PostgreSQL | Managed scaling, persistent storage, no infrastructure to maintain; sub-200ms search across 18,027 chunks |
| LLM generator (Gemini 2.5 Flash Lite) | **Cloud** — Google Gemini API | State-of-the-art Thai language generation; pay-per-token with no infrastructure; stateless per call |
| Backend API (FastAPI) | **Cloud** — Railway | Managed deployment; co-located with embedding model to avoid network round-trip for local inference |
| Frontend (Next.js) | **Cloud** — Vercel | CDN-distributed; no backend coupling |

The embedding model runs locally on the same server as FastAPI specifically to avoid the API quota bottleneck — this is a justified architectural trade-off that differs from full cloud deployment.

#### A2.3.3 — Considerations Beyond Model Accuracy

| Consideration | Design decision | Justification |
|---------------|----------------|---------------|
| **Prediction speed / latency** | Target p95 ≤ 5s; local embedding (~50ms) + pgvector (~100ms) + Gemini (~2–4s) | Students expect near-instant response; >10s abandon rate is high. Gemini dominates latency; local embedding avoids adding a second ~500ms API call |
| **Model size** | multilingual-e5-base (278M parameters, ~1.1GB on disk) | Chosen over larger multilingual models (e5-large: 560M params) because base provides sufficient retrieval quality at half the memory footprint; runs on a standard 2GB Railway instance |
| **Throughput** | Stateless query pipeline; no session state | Enables horizontal scaling: multiple FastAPI instances share the same Supabase vector store without coordination overhead |
| **Cost** | Local embedding = $0/query; Gemini Flash Lite ≈ $0.00015/query at ~1,000 tokens input | For a student-facing advisory tool, cost per query must be near-zero to be viable without per-user charging |
| **Multilingual robustness** | multilingual-e5 trained on 100 languages including Thai | Retrieval quality on Thai-English mixed queries confirmed empirically; alternative Thai-only models lack English cross-lingual capability |

#### A2.3.4 — Model Composition

The system composes two AI components in sequence:

```
Component 1: Embedding model (intfloat/multilingual-e5-base)
    Role: Dense retriever
    Input: Raw question text
    Output: 768-dim vector
    Failure mode: If model fails to load, entire query pipeline aborts (no fallback)
        │
        ▼ (vector passed to pgvector; top chunks returned)
        │
Component 2: LLM generator (Gemini 2.5 Flash Lite)
    Role: Answer synthesiser
    Input: Retrieved chunks (plain text) + original question
    Output: Grounded answer with citations
    Failure mode: If Gemini API unavailable, return "service temporarily unavailable"
```

**Composition pattern: Sequential (pipeline)**
- Component 1 output (embedding vector) is consumed by the pgvector retrieval step
- Component 1 and Component 2 are decoupled — Component 2 receives only plain-text chunks, not the embedding vector
- Component 2 does not know what retrieval strategy was used; it sees only the assembled context window

**Guard between components:** If Component 1 retrieval returns zero chunks AND zero TCAS records, Component 2 is not called. This prevents the LLM from generating an answer with an empty context window.

**No parallel composition:** The system does not currently run multiple models in parallel. The re-ranker (PyThaiNLP token matching) is a deterministic heuristic, not an ML model, and runs synchronously within the retrieval step.

---

### A2.4 Feedback Collection and Model Monitoring

**User feedback mechanism:** Each generated response in the chat UI includes a thumbs up / thumbs down rating button. On click, the following record is written to the `feedback` table in Supabase:

```
feedback(
    id          UUID PRIMARY KEY,
    question    TEXT,
    answer      TEXT,
    program_id  TEXT,
    score       INTEGER,  -- +1 (thumbs up) or -1 (thumbs down)
    timestamp   TIMESTAMPTZ
)
```

**Monitoring metrics and tools:**

| Metric | Tool | Alert threshold |
|--------|------|----------------|
| Negative feedback rate per program | Daily Supabase query aggregating `feedback` table | >30% negative → flag for re-ingestion review |
| Good-answer rate (offline) | `scripts/run_eval.py` — LLM-as-judge on 20-question sample | <60% → investigate retrieval quality |
| Empty-result rate | Count of responses where no-data guard triggered / total queries | >20% → corpus coverage gap; ingest more programs |
| Response latency p95 | FastAPI middleware timing log | >8,000ms → investigate embedding or Gemini API latency |
| Chunk count per program | Supabase query: `SELECT program_id, COUNT(*) FROM chunks GROUP BY program_id` | <50 chunks → program flagged as low-coverage |

**Note on "retraining" for a RAG system:** For a RAG pipeline, re-ingestion is the functional equivalent of model retraining. The "model" is the indexed vector store — updating it with better-extracted or more complete document chunks directly improves retrieval quality without changing any model weights. The pipeline below describes this re-ingestion loop, which serves the same role as a retraining pipeline in a classical ML system.

**Feedback → retraining pipeline:**

```
User thumbs down
    │
    ▼
feedback table (Supabase)
    │
    ▼ [daily aggregation]
Programs with negative_rate > 30%
    │
    ├── If chunks < 100: re-ingest with full มคอ.2 from data/raw
    │   (upgraded OCR model: gemini-2.5-flash)
    │
    └── If chunks ≥ 100: investigate chunking quality
        (tabular extraction, section boundary detection)
    │
    ▼
Re-ingestion → VACUUM ANALYZE → IVFFlat index rebuild
    │
    ▼
Re-run eval set for affected program(s)
    │
    ▼
Compare score before/after → log in eval_results.md
```

**Eval set iteration history:**

| Iteration | Avg score | Good (≥2) | Key change |
|-----------|-----------|-----------|------------|
| v1 baseline | 1.30 / 3.0 | 40% | No program_id scoping; decontextualized eval questions |
| v2 (query fix) | 1.85 / 3.0 | 65% | program_id scoping + program-named questions in eval set |
| v3 (re-ingest) | 1.80 / 3.0 | 65% | Full มคอ.2 PDFs (10× more chunks for engineering programs) |

The v1→v2 improvement (+25pp) came from fixing program-scoped retrieval. The v2→v3 plateau confirms the remaining failures are structural (credit table extraction), not data-volume failures.

---

## A3 — Proposed Improvements

Current system: 65% good-answer rate. Three concrete improvements address the confirmed root causes.

### Improvement 1: Table-Aware Chunking (highest impact)

**Root cause confirmed:** Credit-structure questions score 0 even after re-ingesting the EME program with 332 full-document chunks. The issue is extraction quality: PyMuPDF breaks table cells into fragmented text, losing row/column relationships. "30" appears in a chunk with no context that it means "30 minimum credits for general education."

**Solution:**
1. Detect tabular regions via PyMuPDF `page.find_tables()` during extraction
2. Serialize tables as Markdown: `| หมวดวิชา | หน่วยกิต |\n|---|---|\n| วิชาศึกษาทั่วไป | 30 |`
3. Tag as `section_type = "structure"` for targeted retrieval on credit queries

**Expected gain:** +10–15pp (3 failing questions out of 20 recovered)

### Improvement 2: Program Name Alias Resolution (lowest effort)

**Root cause confirmed:** "นานาชาติ" matches 10+ programs; resolver falls back to all-program search and mixes chunks from multiple programs in the context.

**Solution:** Add `name_aliases` column to `programs` table; resolve ambiguous short forms to the full official program name before retrieval.

**Expected gain:** +5pp (1 confirmed failure)

### Improvement 3: Hybrid BM25 + Dense Retrieval (medium effort)

**Root cause:** Dense-only retrieval underperforms on exact-keyword queries (course codes, credit numbers). PostgreSQL `tsvector` full-text search is already available in Supabase.

**Solution:** Run BM25 and dense search in parallel; merge with Reciprocal Rank Fusion (`score = Σ 1/(60 + rank_i)`). Activate only when query contains numeric tokens.

**Expected gain:** +5–10pp on keyword-heavy curriculum questions

### Combined Projection

| Improvement | Est. gain |
|-------------|-----------|
| Table-aware chunking | +10–15pp |
| Name alias resolution | +5pp |
| Hybrid BM25 + dense | +5–10pp |
| **Combined** | **~75–85% good-answer rate** |

---

## AI Usage Disclosure

Claude (Anthropic) was used to assist with: drafting and structuring this report, generating the B1 data exploration notebook code, and writing the eval runner script (`scripts/run_eval.py`). All architectural decisions, evaluation design, pipeline implementation, and data ingestion were performed by the team. All submitted code has been reviewed and can be explained by the team members.

---

*KUru pipeline — evaluation data current as of May 2026*
