# KUru Pipeline — Status & Roadmap

_Last updated: 2026-05-03_

---

## What's Working

### Infrastructure
- **pgvector search** — `match_chunks` RPC uses `ivfflat.probes=50`, giving full recall across all 9,369 chunks. (Default `probes=1` was making ~8,900 chunks invisible — fixed 2026-05-03.)
- **Embeddings** — local `multilingual-e5-base` (768-dim, no API quota, ~5s cold start).
- **Generation** — `google/gemini-2.5-flash-lite` via OpenRouter.
- **No-data guard** — when a program is identified but has no ingested chunks, the engine returns an honest Thai message instead of hallucinating.
- **Coverage-aware prompting** — the LLM is told when a program's source document lacks PLO sections or was scanned, so it hedges correctly instead of inventing PLOs.

### Query features
- **Thai name resolution** — tokenises the query with pythainlp and matches against `name_th` in the programs table.
- **English name resolution** — matches against `name_en` (now populated for all บางเขน programs).
- **Targeted fetch** — when a program is resolved, does a secondary similarity search filtered to that program and prepends results, fixing cases where the program's chunks rank outside the global top-K.
- **Re-ranker** — boosts chunks whose source filename contains Thai tokens from the query.
- **TCAS retrieval** — round-aware; detects round from query, searches DB by keyword, sorts matched round to the front.
- **Listing queries** — "what programs are available?" pulls the programs table directly instead of using chunks.

### Data ingested

| Campus | Programs | Chunks | Notes |
|--------|----------|--------|-------|
| บางเขน | 33 | ~9,300 | Full pass complete |
| กพส | 1 | ~69 | CPE-กพส only |
| กำแพงแสน | 0 | 0 | Folder IDs not yet added |
| ศรีราชา | 0 | 0 | Folder IDs not yet added |

**TCAS:** 2,524 records — 1,463 round1 + 1,061 round3.

**Coverage breakdown (บางเขน, approximate):**

| Status | Meaning |
|--------|---------|
| `full` | Has overview + PLOs + courses + timeline |
| `partial` | Has PLOs + courses, missing overview or timeline |
| `courses_only` | Courses extracted; source document has no PLO section (most วิศวฯ PDFs) |
| `scanned` | Image-only PDF, cannot extract native text (สถาปัตย์) |
| `no_data` | Program record exists but not yet ingested |

Run `uv run kuru-coverage` for live numbers.

---

## Implementation Gaps

### Gap 1 — Only บางเขน ingested (~33 of ~260 programs)

**Impact:** Queries about กำแพงแสน or ศรีราชา programs return "no data" (which is honest, but limits utility).

**Fix:** Add Google Drive folder IDs for the missing campuses to `EXTRA_CAMPUS_FOLDERS` in `download_data.py`, then:
```bash
uv run kuru-download --sync
uv run kuru-ingest-mko กำแพงแสน
uv run kuru-ingest-mko ศรีราชา
```

**Effort:** Low — 30 minutes once folder IDs are known.

---

### Gap 2 — Most engineering PDFs lack PLO sections (`courses_only`)

**Impact:** PLO queries for วิศวฯ programs return "this document does not contain PLO information." The raw data genuinely doesn't have them — these are compact course-catalog PDFs, not full มคอ.2 specifications.

**Fix options:**
- Find the full มคอ.2 PDFs for each engineering program (they may exist in a different Drive folder or on the KU registrar website) and re-ingest.
- Scrape PLOs from the KU registrar website directly (`uv run kuru-scrape-curriculum` — see `docs/scraper.md`).

**Effort:** Medium — depends on data availability.

---

### Gap 3 — OCR failure rate ~25% with weak model

**Impact:** Roughly 1 in 4 scanned-page PDFs fails OCR with `google/gemini-2.5-flash-lite` (hallucinated garbage text, `choices=None` errors, or 0 chunks extracted). The affected programs end up with `no_text` or `no_data` coverage.

**Fix:** Set `OCR_MODEL=google/gemini-2.5-flash` in `.env` before running `kuru-ingest-mko`. The stronger model costs ~5× more ($25 vs $5 for 260 files) but brings failure rate to ~2–5%.

For remaining failures after that, set `OCR_MODEL=google/gemini-2.5-pro` and re-run only the failed files via `reingest_targets.py`.

**Effort:** Low (config change) — but requires ~$25–30 in API credit.

---

### Gap 4 — Multi-program queries only surface one program's TCAS data

**Impact:** "Compare TCAS requirements for CPE and SKE" returns data for whichever program's chunks score highest, not both.

**Fix:** The TCAS keyword-search fallback already does per-word DB searches. Improving this requires:
1. Identifying multiple resolved programs from the query (currently only one is resolved).
2. Fetching TCAS records for all resolved programs and merging.

**Effort:** Medium — requires changes to `_resolve_program_from_query` and the TCAS fetch loop in `query_engine.py`.

---

### Gap 5 — IVFFlat index recall degrades as data grows

**Impact:** The current IVFFlat index was built with `lists=100`. Each query probes 50 lists (50% of data). As the chunk count grows past ~50,000, recall at `probes=50` will start to degrade — the index will need to be rebuilt with more lists or switched to HNSW.

**Fix (when chunk count > 50k):**
```sql
-- In Supabase SQL Editor:
DROP INDEX chunks_embedding_idx;
CREATE INDEX chunks_embedding_idx
  ON chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
```
HNSW doesn't need a `probes` equivalent — it gives exact-ish results at any scale.

**Effort:** Low (one SQL command) — but only needed when scale demands it.

---

### Gap 6 — ศึกษาศาสตร์ program has wrong name_th

**Impact:** The Education faculty program record has `name_th = "0 แบบในการเสนอขอปรับปรุงแก้ไขหลักสูตร 26-12-66"` — a form template title, not the actual program name. Thai name resolution will never match "ศึกษาศาสตร์" queries.

**Fix:** Update the record in Supabase directly or delete and re-ingest the Education faculty PDF with correct metadata.

**Effort:** Very low (one SQL UPDATE).

---

## Improvement Roadmap

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| High | Ingest กำแพงแสน + ศรีราชา campuses | Low | High — doubles program coverage |
| High | Full 260-file re-ingest with `gemini-2.5-flash` OCR | Low (cost: ~$30) | High — fixes ~25% of failed programs |
| Medium | Fix ศึกษาศาสตร์ name_th in DB | Very low | Low |
| Medium | Multi-program query support | Medium | Medium |
| Low | Switch IVFFlat → HNSW (when > 50k chunks) | Low | Medium (at scale) |
| Low | Scrape full PLO data from KU registrar | High | High (quality) |
