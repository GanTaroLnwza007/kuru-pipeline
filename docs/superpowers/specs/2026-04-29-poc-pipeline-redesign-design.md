# PoC Pipeline Redesign — Design Spec

**Date:** 2026-04-29
**Status:** Approved
**Authors:** Thanawat Tantijaroensin + Claude

---

## Problem

The previous pipeline attempted OCR on scanned PDFs using Gemini vision API. This resulted in
~$50 in API costs with poor quality output and a wiped Supabase database. The project needs a
working PoC before end of April 2026.

**Root cause:** Wrong data source. Google Drive contains mostly native (born-digital) PDFs.
Native PDFs need no OCR — PyMuPDF extracts text for free. Scanned PDFs are a minority and not
needed for the PoC.

**Secondary problems:**
- Some "PDF" files are redirect notices pointing to real PDFs or Drive folders
- Some PDFs lack PLO/CLO sections — need graceful partial storage, not failure
- No Thai ↔ English program name mapping
- No structured data in Supabase for the frontend program explorer (only RAG chunks existed)
- No API layer for the frontend team
- Supabase is currently empty (curriculum + TCAS data deleted)
- Neo4j is empty

---

## Goals (PoC Scope)

1. Ingest native PDFs from Google Drive with zero OCR cost
2. Extract structured program data (PLOs, courses, year timeline, curriculum mapping, overview)
   into Supabase JSONB fields — queryable directly by the frontend
3. Track which programs have data and which are missing
4. Preserve OCR code for later use without deleting it
5. Set up Supabase schema cleanly from scratch
6. Make Neo4j population a zero-reingest operation when ready

**Out of scope for PoC:**
- Scanned PDF OCR (code preserved, not run)
- Neo4j population (deferred — command designed, not implemented)
- API server (lives in a separate repo; frontend queries Supabase JS client directly)
- Full 260-program coverage (partial coverage is acceptable)

---

## Architecture

### What Stays the Same

- Chunking + embedding pipeline for RAG chatbot (`chunker.py`, `embedder.py`)
- Supabase as the database
- `ingest_tcas.py` pipeline (re-runs against native TCAS PDFs)
- `query_engine.py` RAG engine

### What Changes

| Component | Change |
|-----------|--------|
| Data directory | Add `data/native/` for native PDFs; keep `data/raw/` for scanned |
| `download_data.py` | Add PDF-redirect detection (single file + folder) |
| `text_extractor.py` | Disable OCR fallback by default; add per-page Typhoon for image pages only |
| `ocr_extractor.py` | **New** — OCR code moved here, isolated for future use |
| `structured_extractor.py` | **New** — Gemini text-mode structured extraction |
| `setup_db.py` | Add new JSONB columns to programs table |
| `ingest_curriculum.py` | Point to `data/native/curriculum/`, wire structured extractor |
| `program_name_mapping.csv` | **New** — manual Thai ↔ English name registry |
| `kuru-coverage` | **New** — CLI coverage report command |
| `kuru-populate-neo4j` | **New** — deferred command (designed, not implemented in PoC) |

### Data Flow

```
Google Drive
  → download_data.py
      → .txt redirect files → follow Drive folder URL (existing)
      → PDF-redirect detection (new):
          text < 200 chars + contains drive.google.com URL
          → single file URL  → download PDF directly
          → folder URL       → reuse existing folder-download logic
  → data/native/curriculum/<campus>/<faculty>/<file>.pdf

Ingest pipeline (per file):
  → PyMuPDF text extraction (free)
      ↳ total chars < 500 AND no drive redirect → mark as scanned, write partial
        programs record with coverage.extraction_method = "scanned", STOP (no OCR)
      ↳ per page: chars < 50 → Typhoon OCR that page (image-embedded table/page)
      ↳ merge Typhoon page text back into full document text
  → Chunking + embedding → Supabase chunks table (RAG, unchanged)
  → structured_extractor.py → Gemini text call → Supabase programs JSONB columns
  → Write coverage record to programs.coverage
```

---

## Directory Structure

```
data/
  raw/curriculum/          ← existing scanned PDFs (untouched, not processed by default)
  native/
    curriculum/
      บางเขน/
        eng/
        sci/
        agri/
        ...
    tcas/
      บางเขน/
        ...
data/program_name_mapping.csv   ← manual Thai ↔ English name registry
```

The pipeline's `base_dir` defaults to `data/native/curriculum/`. Scanned PDFs in `data/raw/`
are never touched unless explicitly pointed at.

---

## OCR Isolation

OCR-specific functions move from `text_extractor.py` to a new `src/kuru/ingestion/ocr_extractor.py`:

**Moved to `ocr_extractor.py`:**
- `_ocr_batch_gemini()`
- `_ocr_batch_typhoon()`
- `_extract_with_vision()`
- `_extract_with_tesseract()`
- `_ocr_batch()` (retry wrapper)

**Stays in `text_extractor.py`:**
- `_extract_pymupdf()`
- `_extract_page_typhoon(page_b64)` — new, targeted per-page OCR for image pages
- `extract_text()` — no longer calls vision fallback; calls `_extract_page_typhoon` per-page only
- All public API functions

To re-enable full scanned PDF OCR in the future, one import and one function call in
`extract_text()` is all that's needed.

---

## Per-Page Typhoon OCR

For pages inside native PDFs where a table or section was embedded as an image:

1. After PyMuPDF runs, identify pages where `len(page.text.strip()) < 50`
2. Render that page to PNG at 96 DPI
3. Call Typhoon OCR (1 page/call, respects 20 req/min free tier)
4. Merge the returned text back into the document at that page position
5. Continue to structured extraction with the merged text

This is the only place OCR is used in the native pipeline. It is not triggered for the whole
document — only for specific low-yield pages.

---

## Structured Extraction

**File:** `src/kuru/ingestion/structured_extractor.py`

**When it runs:** after PyMuPDF extraction, on the full merged document text.

**How:** one Gemini text-mode call (not vision) with a structured JSON prompt. Estimated cost:
~$0.002 per PDF at `gemini-2.5-flash-lite` pricing.

**Output schema:**

```python
@dataclass
class StructuredProgram:
    overview: str                    # Program overview paragraph (empty string if not found)
    plos: list[dict]                 # [{"id": "PLO1", "description": "...", "category": "..."}]
    courses: list[dict]              # [{"code": "01204111", "name_th": "...", "credits": 3,
                                     #   "year": 1, "semester": 1, "teaching_method": "lecture"}]
    year_timeline: list[dict]        # [{"year": 1, "narrative": "...", "course_codes": [...],
                                     #   "teaching_methods": {"lecture": 60, "lab": 40}}]
    curriculum_mapping: list[dict]   # [{"course_code": "...", "plo_primary": ["PLO1"],
                                     #   "plo_secondary": ["PLO3"]}]
```

All fields default to empty list / empty string when not found in the document. A program with
no PLO section still gets a record written — never a failure.

**Curriculum mapping tables** (the ● / ○ tables): PyMuPDF extracts the cell values including
Unicode bullet characters. The Gemini prompt interprets the multi-level header structure and
returns structured `plo_primary` / `plo_secondary` arrays per course. No programmatic table
parsing needed.

---

## Supabase Schema

Run once via updated `setup_db.py` (clean DB, no migrations needed):

```sql
-- Existing columns kept as-is
ALTER TABLE programs ADD COLUMN IF NOT EXISTS overview          TEXT;
ALTER TABLE programs ADD COLUMN IF NOT EXISTS plos             JSONB DEFAULT '[]';
ALTER TABLE programs ADD COLUMN IF NOT EXISTS courses          JSONB DEFAULT '[]';
ALTER TABLE programs ADD COLUMN IF NOT EXISTS year_timeline    JSONB DEFAULT '[]';
ALTER TABLE programs ADD COLUMN IF NOT EXISTS curriculum_mapping JSONB DEFAULT '[]';
ALTER TABLE programs ADD COLUMN IF NOT EXISTS coverage         JSONB DEFAULT '{}';
-- name_en already exists
```

Since Supabase is empty, `setup_db.py` can be run cleanly to recreate tables with the new
schema included from the start.

---

## Program Name Mapping

**File:** `data/program_name_mapping.csv`

```csv
program_id,name_th_canonical,name_en
bangkhen_eng_a1b2c3d4,วิศวกรรมคอมพิวเตอร์,Computer Engineering
bangkhen_sci_b2c3d4e5,วิทยาการคอมพิวเตอร์,Computer Science
```

**Pipeline load order:**
1. Check `program_name_mapping.csv` for `name_en` by `program_id`
2. If not found, try `_extract_name_en()` from PDF text (existing regex)
3. If neither works, `name_en` stays `null`

`coverage.name_en_source` records which path succeeded: `"csv_mapping"`,
`"auto_extracted"`, or `null`.

The CSV is committed to the repo and filled in incrementally. No code changes needed when
new entries are added — the pipeline picks them up on next run.

---

## Coverage Tracking

Every program record gets a `coverage` JSONB field written after ingest:

```json
{
  "extraction_method": "pymupdf",
  "has_overview": true,
  "has_plos": true,
  "plo_count": 6,
  "has_courses": true,
  "course_count": 48,
  "has_timeline": true,
  "has_curriculum_mapping": false,
  "scanned_pages": 2,
  "total_pages": 45,
  "name_en_source": "csv_mapping"
}
```

**`extraction_method` values:**
- `"pymupdf"` — fully native, no OCR
- `"pymupdf+typhoon_pages"` — native with some pages OCR'd by Typhoon
- `"scanned"` — PyMuPDF got < 500 chars, OCR disabled, partial record only

---

## Coverage Report Command

**Command:** `uv run kuru-coverage`

Queries the `programs` table and prints:

```
Program Coverage Report — บางเขน
─────────────────────────────────────────────────────────
Status              Count   Details
─────────────────────────────────────────────────────────
✓  Full              12     has overview + PLOs + courses + timeline
◑  Partial           28     missing 1–2 fields
✗  No text            4     scanned PDF, no native text
?  Redirect           2     drive redirect, pending download
─────────────────────────────────────────────────────────
Total               46
name_en filled:      8 / 46
─────────────────────────────────────────────────────────
Missing name_en:
  bangkhen_agri_xxxx  วท.บ. วนศาสตร์
  bangkhen_eng_yyyy   วศ.บ. วิศวกรรมเครื่องกล
  ...
```

---

## Neo4j Population (Deferred)

**Command:** `uv run kuru-populate-neo4j` — designed now, implemented later.

Reads from `programs.plos` and `programs.curriculum_mapping` in Supabase and writes the
Neo4j graph. **No PDF re-ingestion required.**

```
Supabase programs.plos + programs.curriculum_mapping
  → kuru-populate-neo4j
      → Faculty -[HAS_PLO]→ PLO nodes
      → PLO -[DEVELOPS]→ SkillCluster nodes
      → Course -[MAPS_TO]→ PLO nodes
```

The existing `plo_extractor.py` is refactored to read from `programs.plos` instead of
re-running Gemini on PDFs. This means Neo4j can be populated at any time after ingest
completes — same data, no extra API cost.

---

## Files Modified / Created

| File | Change |
|------|--------|
| `data/native/` | New directory tree for native PDFs |
| `data/program_name_mapping.csv` | New — manual Thai ↔ English name registry |
| `src/kuru/ingestion/ocr_extractor.py` | New — OCR functions moved here, isolated |
| `src/kuru/ingestion/structured_extractor.py` | New — Gemini text-mode structured extraction |
| `src/kuru/ingestion/text_extractor.py` | Remove OCR fallback; add per-page Typhoon; import from ocr_extractor |
| `src/kuru/scripts/ingest_curriculum.py` | Point to `data/native/`, wire structured extractor |
| `src/kuru/scripts/setup_db.py` | Add new JSONB columns to programs table |
| `src/kuru/scripts/coverage_report.py` | New — coverage report CLI |
| `pyproject.toml` | Add `kuru-coverage` entrypoint |

---

## Verification Checklist

- [ ] `uv run kuru-setup-db` creates programs table with all JSONB columns
- [ ] `uv run kuru-download` downloads native PDFs to `data/native/`
- [ ] Drive redirect PDFs (single file + folder) resolve correctly
- [ ] `uv run kuru-ingest-mko` on 3 test files produces structured JSONB in programs table
- [ ] Scanned PDFs produce a partial record with `coverage.extraction_method = "scanned"` and no API cost
- [ ] `uv run kuru-coverage` prints a readable report
- [ ] Frontend can query `programs` table via Supabase JS client and get PLOs, courses, timeline
- [ ] OCR code in `ocr_extractor.py` is importable but not called during normal ingest
