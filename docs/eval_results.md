# RAG Evaluation Results

## Setup

- **Eval tool**: LLM-as-judge (0–3 scale) via `scripts/run_eval.py`
- **Judge model**: `google/gemini-2.5-flash-lite` via OpenRouter
- **Sample size**: 20 questions (random seed 42) from 50-question golden eval set
- **Eval set**: Synthetic Q&A pairs generated from actual Supabase chunks via `scripts/generate_eval_set.py`

### Score rubric
| Score | Meaning |
|-------|---------|
| 3 | Correct and complete — covers all key facts in ground truth |
| 2 | Partially correct — main point addressed but details missing or minor errors |
| 1 | Tangentially related — on-topic but does not directly answer the question |
| 0 | Wrong or hallucinated — contradicts ground truth or invents facts |

---

## Iteration 1 — Baseline (v1 eval set, no program_id targeting)

| Metric | Value |
|--------|-------|
| Average score | **1.30 / 3.0** |
| Good answers (score ≥ 2) | **40%** |
| Distribution | 3=5, 2=3, 1=5, 0=7 |
| Admission avg | 1.17 (n=6) |
| Curriculum avg | 1.36 (n=14) |
| API cost | ~$0.0094 |

**Root causes of failures:**
- Eval set contained decontextualized questions ("this program", "this curriculum") that are unanswerable without knowing which program was being referenced
- One question asked about Thammasat University (OCR picked up a comparison table in a KU document)
- Multiple near-duplicate "Languages and Communication credit" questions from different programs — RAG retrieved chunks from the wrong program
- `query()` called without `program_id` — retrieval was not scoped to the correct program

---

## Iteration 2 — After fixes (v2 eval set + program_id targeting)

| Metric | Value |
|--------|-------|
| Average score | **1.85 / 3.0** |
| Good answers (score ≥ 2) | **65%** |
| Distribution | 3=9, 2=4, 1=2, 0=5 |
| Admission avg | 2.00 (n=6) |
| Curriculum avg | 1.79 (n=14) |
| API cost | ~$0.0091 |

**Changes made:**
1. **Eval set prompt** — required program name in every question, banned "this program" references and other-university mentions
2. **Eval runner** — passes `program_id` from CSV to `query()` to scope retrieval to the correct program

**Improvement: +0.55 avg score (+42% relative), +25pp good-answer rate (40% → 65%)**

---

## Remaining failure patterns (score 0–1 after fixes)

| Question | Issue |
|----------|-------|
| "minimum credit for Languages and Communication" (×3) | Credit structure chunks still retrieving wrong program despite program_id — likely section_type mismatch |
| "วิศวกรรมไฟฟ้าเครื่องกลการผลิต ต้องเรียนกี่หน่วย" | EME program has sparse chunks — curriculum structure not well-indexed |
| "นานาชาติ program accept students..." | `name_th` = "นานาชาติ" (too generic) — program resolution fails |
| "Geography admission" | Geography chunks exist but program_id resolution may be mismatched |

**Next improvement candidates:**
- Fix generic `name_th` values ("นานาชาติ") — update programs table with full program names
- Improve credit-structure retrieval: consider dedicated `structure` section type for credit tables
- Re-ingest วิทยาศาสตร์สิ่งแวดล้อม and เทคโนโลยีผลิตภัณฑ์ไม้ with better OCR model (currently 15 and 19 chunks)

---

## Iteration 3 — After re-ingesting full มคอ.2 PDFs (v2 eval set)

| Metric | Value |
|--------|-------|
| Average score | **1.80 / 3.0** |
| Good answers (score ≥ 2) | **65%** |
| Distribution | 3=8, 2=5, 1=2, 0=5 |
| Admission avg | 1.83 (n=6) |
| Curriculum avg | 1.79 (n=14) |
| API cost | ~$0.0095 |

**Changes made:**
- Re-ingested 9 engineering bachelor's programs using full มคอ.2 PDFs from `data/raw` (via Gemini OCR) instead of compact TCAS booklets from `data/native`
- Chunk counts improved dramatically: EME 31→332, SemE 56→432, DMriE 21→277, WRE 27→177, MatE 46→192

**Result: No significant improvement vs v2 (+0% good-answer rate, -0.05 avg score)**

**Why better chunks didn't help:**
- Failures are structural, not data-volume issues
- Credit structure questions ("Languages and Communication minimum credits" ×3) still fail — credit tables are not well-indexed by section_type
- EME หน่วยกิต question still scores 0 despite 332 chunks — credit summary not in top-k chunks
- Geography admission still fails — program_id resolution mismatch persists

---

## Files

| File | Description |
|------|-------------|
| `data/eval_set.csv` | v1 eval set (50 Q&A pairs, has quality issues) |
| `data/eval_set_v2.csv` | v2 eval set (50 Q&A pairs, program-named questions) |
| `data/eval_results.csv` | v1 results (40% good) |
| `data/eval_results_v2.csv` | v2 results (65% good) |
| `data/eval_results_v3.csv` | v3 results (65% good, re-ingested full PDFs) |
| `scripts/generate_eval_set.py` | Synthetic eval set generator |
| `scripts/run_eval.py` | LLM-as-judge evaluation runner |
