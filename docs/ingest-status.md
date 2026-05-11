# Ingest Status

Last updated: 2026-04-25

---

## Current State

| Item | Count |
|------|-------|
| Total programs in DB | 48 |
| Programs with chunks | 46 |
| Programs with 0 chunks (OCR failed) | 2 |
| Total chunks in DB | ~95,938 |
| TCAS records | 2,524 |

---

## What Has Been Done

### 50-file test batch (บางเขน)
- 50 files sampled proportionally across 20 faculties
- All ingested, then audited for OCR quality
- 14 programs identified as garbled and cleared from DB
- 1 of 14 successfully re-ingested (`ปร.ด._นวัตกรรมสิ่งแวดล้อมสรรค์สร้าง_2565.pdf`, 5,803 chunks)
- 13 still pending re-ingest (processes killed due to rate limiting from duplicate instance)

### Bugs fixed (code changes committed)

**`src/kuru/ingestion/text_extractor.py`**
- Added `_is_garbage_line()` — filters OCR hallucination lines where >85% of non-space characters are the same single character (e.g. `า า า า า า` or `7777777`)
- Upgraded `_dedup_lines()` to call the garbage filter on every line
- Added cross-batch dedup in `_extract_with_vision()` — if Gemini gets stuck in a loop and returns the same content for every 8-page batch, duplicate batch outputs are discarded (fixes the "same 2 lines × 1000 chunks" problem)

**`src/kuru/ingestion/tcas_extractor.py`**
- Updated `EXTRACTION_PROMPT` to clarify that `gpax_min` is a GPA on a 4.0 scale and NOT a score weight percentage
- Added Pydantic `field_validator` on `TCASRecord.gpax_min` that nulls out any value > 4.0
- Fixed 2 existing bad records in DB (`ภ.บ.` gpax_min=20.0 → null, `ศศ.บ.` gpax_min=50.0 → null)

**`src/kuru/rag/query_engine.py`**
- Narrowed `LISTING_KEYWORDS` regex — removed bare `what courses` and `what programs` so that "What courses will I take in Computer Engineering?" no longer triggers list mode and suppresses re-ranking

**`src/kuru/scripts/ingest_curriculum.py`**
- Added `_program_name_from_stem()` — derives human-readable Thai name from PDF filename (e.g. `วท.บ._วนศาสตร์_2567` → `วท.บ. วนศาสตร์`)
- Added `_degree_level()` — derives doctoral/master/bachelor from filename prefix
- Added `_extract_name_en()` — extracts English program name from OCR text (e.g. "Bachelor of Science Program in Forestry")
- Added `_CLOSED_RE` filter in `find_documents()` — skips PDFs with `ปิดหลักสูตร` or `สภาฯ อนุมัติปิด` in filename
- Moved `upsert_program()` before the skip check so re-running the ingest backfills `name_th` and `degree_level` even for already-ingested files
- After OCR, calls `upsert_program()` again with `name_en` if found

**DB backfill**
- Ran one-time script to update `name_th` and `degree_level` for all 48 already-ingested programs using their source filenames (was storing hash IDs like `bangkhen_agri_0f6da02d` before)

---

## OCR Failure Analysis & Options

### Root Cause

Two forestry PDFs (`วท.บ._วนศาสตร์_2567.pdf`, `ปร.ด._วนศาสตร์_(นานาชาติ)_2569.pdf`) produced 0
chunks after re-ingest. The OCR pipeline has two aggressive filters that compound:

1. **`_is_garbage_line()`** — drops any line where >85% of non-space chars are the same character.
2. **Cross-batch dedup** — if Gemini hallucinates the same content for every 8-page batch, only
   the first batch survives.

For very poor quality scans, Gemini hallucinates garbage repeatedly → cross-batch dedup kills all
but one batch → garbage filter kills that batch → empty string → 0 chunks. Neither filter alone
causes this; it's the combination.

### Options (ranked by effort)

| # | Option | Effort | Status |
|---|--------|--------|--------|
| 1 | **Higher DPI + smaller batch** — 100→150 DPI, 8→4 pages/batch. Bigger images give the model more detail; smaller batches reduce hallucination loops. | Low — 2-line change | **Implemented** |
| 2 | **Stronger Gemini model** — `gemini-2.5-flash` (full) instead of `flash-lite` for files that return empty. Better OCR on poor scans. | Low — per-file model override | Deferred |
| 3 | **Tesseract local fallback** — when Gemini vision returns < 500 chars after filtering, fall through to Tesseract with Thai language pack (`tha+eng`). Free, local, no quota, no hallucination. | Medium — add pytesseract dep + function | **Implemented** |
| 4 | **Smarter cross-batch dedup** — replace exact string match with edit-distance similarity so slightly-different-garbage batches each survive one copy. | Medium — more complex logic | Deferred |
| 5 | **Google Document AI / Azure Document Intelligence** — purpose-built document OCR with Thai support. Best quality but costs ~$1.50/1000 pages and requires API setup. | High | Deferred — consider if Tesseract still fails |

### Setup Required for Tesseract (Option 3)

Tesseract binary must be installed separately from the Python package:

```powershell
# Windows — download installer from https://github.com/UB-Mannheim/tesseract/wiki
# Make sure to tick "Thai" language data during install
# Default install path: C:\Program Files\Tesseract-OCR\tesseract.exe

# Then install Python wrapper
uv add pytesseract
```

If Tesseract binary is not found, the fallback logs a warning and returns empty — it never crashes
the ingest. Re-ingest the failed files after installing:

```powershell
$env:PYTHONUTF8=1; uv run python reingest_targets.py
```

---

## Pending: 2 Programs Still at 0 Chunks (OCR failed)

These produced 0 chunks after re-ingest — Gemini OCR returned empty after garbage/dedup filtering.
Re-ingest after installing Tesseract (see above) — the Tesseract fallback will catch them.

| Program | File | Failure mode |
|---------|------|-------------|
| วท.บ. วนศาสตร์ | วท.บ._วนศาสตร์_2567.pdf | garbage + cross-batch dedup → empty |
| ปร.ด. วนศาสตร์ (นานาชาติ) | ปร.ด._วนศาสตร์_(นานาชาติ)_2569.pdf | garbage + cross-batch dedup → empty |

---

## Known Remaining Issues (after re-ingest)

1. **English queries still weak** — `name_en` populated going forward from OCR text, but most existing programs still have `name_en=null`. English program name resolution won't fire for them. Workaround: query in Thai.

2. **Closed-program chunks in DB** — several programs with `สภาฯ อนุมัติปิดหลักสูตร` in their name were ingested before the filter was added. They won't appear in new ingests but their chunks are still in the DB. Not actively harmful but add noise.

3. **PLO chunks missing for most engineering programs** — section headers don't match `SECTION_PATTERNS` in `chunker.py`. Only Civil Engineering and Vet Nursing have PLO sections detected.

4. **Answer depth on program overview questions** — when no `overview` section chunk is retrieved, the model answers from course-list chunks and gives a narrow answer (mentions one course instead of the whole program).

---

## Next Steps

1. Run `reingest_targets.py` to completion (13 files, ~2 hrs, single process)
2. Re-run `test_rag_quality.py` and `student scenario` test to verify fixes
3. If quality is satisfactory → run full 260-file ingest overnight: `uv run kuru-ingest-mko`
4. Post-ingest: run PLO extraction (`kuru-extract-plos`) and verify Neo4j graph
