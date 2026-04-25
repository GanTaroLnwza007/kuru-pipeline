# Ingest Status

Last updated: 2026-04-25

---

## Current State

| Item | Count |
|------|-------|
| Total programs in DB | 56 |
| Programs with chunks | 37 |
| Programs pending re-ingest | 13 |
| Total chunks in DB | ~75,000 |
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

## Pending: 13 Programs to Re-ingest

These were cleared from DB and need to be re-processed with the fixed OCR code.
Run `reingest_targets.py` as a **single process** (no background `&`):

```powershell
$env:PYTHONUTF8=1; uv run python reingest_targets.py
```

| Program | File | Failure mode |
|---------|------|-------------|
| ปร.ด. นิเทศศาสตร์ดิจิทัล | ปร.ด._นิเทศศาสตร์ดิจิทัล_2568.pdf | garbage 30/30 + identical 97% |
| วท.บ. วนศาสตร์ | วท.บ._วนศาสตร์_2567.pdf | garbage 27/30 + identical 90% |
| บธ.บ. การตลาด (นานาชาติ) | บธ.บ._การตลาด_(นานาชาติ)_2568.pdf | identical 97% (cross-batch repeat) |
| ปร.ด. วิศวกรรมคอมพิวเตอร์ | ปร.ด._วิศวกรรมคอมพิวเตอร์_2566.pdf | า า า า า hallucination |
| ปร.ด. วิทยาศาสตร์สิ่งแวดล้อม | ปร.ด._วิทยาศาสตร์สิ่งแวดล้อม_2564.pdf | identical 77% |
| ปร.ด. วนศาสตร์ (นานาชาติ) | ปร.ด._วนศาสตร์_(นานาชาติ)_2569.pdf | garbage 30/30 + identical 97% |
| ปร.ด. วิศวกรรมทรัพยากรน้ำ | ปร.ด._วิศวกรรมทรัพยากรน้ำ_2564.pdf | identical 97% |
| ปร.ด. วิศวกรรมวัสดุ | ปร.ด._วิศวกรรมวัสดุ_2569.pdf | identical 97% |
| ปร.ด. การท่องเที่ยวฯ | ปร.ด._การท่องเที่ยวและการบริการร่วมสมัยอย่างยั่งยืน_2569.pdf | garbage 3/30 + identical 77% |
| พ.บ. | พ.บ._2567.pdf | identical 93% |
| ภ.บ. | ภ.บ._2569.pdf | garbage 30/30 + identical 93% |
| (เดิม) วท.ม. ศาสตร์แห่งแผ่นดิน | (เดิม_วท.ม._ศาสตร์แห่งแผ่นดินเพื่อการพัฒนาที่ยั่งยืน)_2564.pdf | garbage 30/30 + identical 97% |
| วท.ม. บูรณาการศาสตร์ | วท.ม._บูรณาการศาสตร์เพื่อการพัฒนาที่ยั่งยืน_2569.pdf | garbage 2/30 + identical 80% |

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
