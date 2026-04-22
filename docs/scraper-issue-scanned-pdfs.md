# Issue: Registrar PDFs Are Scanned Images

## Summary

The curriculum PDFs hosted on `registrar.ku.ac.th` are scanned image-only documents.
PyMuPDF extracts **0 characters** from every file. The scraper downloads them successfully,
but the ingest pipeline cannot process them without an OCR step.

## What We Tried

1. Scraped 260 PDFs from `registrar.ku.ac.th/cur/all` (Bangkhen campus, all faculties).
2. Ran `kuru-ingest-mko` — only **4 out of 260** produced any chunks.
3. Confirmed with PyMuPDF directly: all sampled files return 0 characters.

```
0 chars  agri/ปร.ด._กีฏวิทยา_2565.pdf
0 chars  agri/ปร.ด._คหกรรมศาสตร์_2569.pdf
0 chars  agri/ปร.ด._ปฐพีวิทยา_2559.pdf
0 chars  agri/ปร.ด._พืชสวน_2565.pdf
0 chars  agri/ปร.ด._พืชไร่_2569.pdf
```

## Root Cause

The registrar site hosts scanned PDFs (photographed/printed documents converted to PDF),
not born-digital PDFs. Born-digital PDFs have embedded text that PyMuPDF can extract
instantly. Scanned PDFs contain only raster images and require OCR to read.

## Why the Pipeline Stalled for 6 Hours

The first ingest run had two compounding problems that were fixed along the way,
but the fundamental scanned-PDF issue remained:

| Problem | Impact | Fix Applied |
|---------|--------|-------------|
| `INTER_FILE_SLEEP = 5` | 22 min of sleep for 260 files | Set to 0 |
| PLO extraction via OpenRouter on every file | ~25 min per file (API calls + retries) | Removed from ingest loop |
| All PDFs are scanned → 0 chars → vision OCR fallback | Thousands of OpenRouter API calls | Not yet fixed |

## Current State

- Supabase is **empty** (all data cleared during debugging).
- 260 PDFs are downloaded locally in `data/raw/curriculum/บางเขน/`.
- TCAS data in `data/raw/tcas1/` is intact and has not been re-ingested.

## Options Going Forward

### Option A — Vision OCR via OpenRouter (slow, costly)
Enable the vision fallback in the ingest pipeline. Each scanned PDF page becomes a
base64 PNG sent to the LLM. At ~10 pages per PDF × 260 PDFs = ~2,600 API calls.
Estimated time: several hours. Estimated cost: depends on OpenRouter pricing per token.

**Pros:** Works with existing downloaded files, no new scraping needed.  
**Cons:** Slow, expensive, OCR quality depends on scan quality.

### Option B — Go back to Google Drive (recommended short-term)
The original 22 Google Drive PDFs were born-digital and ingested cleanly.
Re-run `kuru-download` and `kuru-ingest-mko` to restore the working state.

**Pros:** Fast, free, proven to work.  
**Cons:** Only 22 programs covered; requires Google Drive access.

### Option C — Find a born-digital source
Investigate whether KU provides curriculum documents in a different format
(e.g., the university's internal system, or a different section of the registrar site).
Some Thai universities publish มคอ.2 documents as Word/DOCX files which are born-digital.

**Pros:** Best long-term solution with full coverage.  
**Cons:** Requires investigation; source may not be publicly accessible.

## Recommendation

Short-term: restore the working state with **Option B** (Google Drive).  
Long-term: investigate **Option C** for broader coverage.

If OCR is acceptable, **Option A** can be run as a one-time batch job overnight —
but validate cost with a small subset first (e.g., one faculty folder).

---

## Running the Full OCR Batch (Option A)

260 PDFs are already downloaded in `data/raw/curriculum/บางเขน/`.
The ingest pipeline automatically falls back to vision OCR for scanned files.

**Tested cost:** ~2 THB per 3 files → estimated ~170 THB total for all 260 PDFs.  
**Estimated time:** 4–6 hours (average ~60–90s per file). Run overnight.

```bash
# 1. Clear old (empty) data from the failed run
uv run kuru-setup-db          # re-creates tables if needed

# 2. Run the full ingest (OCR fallback fires automatically on scanned PDFs)
PYTHONUTF8=1 uv run kuru-ingest-mko

# 3. After ingest, verify with the demo chatbot
PYTHONUTF8=1 uv run kuru-demo
```

> `PYTHONUTF8=1` is required on Windows to avoid Thai character encoding errors in the terminal.

### Re-ingesting TCAS after the DB was cleared

If `tcas_records` was also wiped during debugging, re-ingest it first:

```bash
PYTHONUTF8=1 uv run kuru-ingest-tcas
```
