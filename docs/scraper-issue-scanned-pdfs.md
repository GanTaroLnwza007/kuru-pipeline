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
**Estimated time:** ~12–13 hours with 3-file parallelism (3 files × 3 OCR workers = 9 concurrent API calls).

> On Windows, always prefix commands with `$env:PYTHONUTF8=1;` in PowerShell to avoid Thai character encoding errors.

```powershell
# 1. Re-create tables if DB was wiped
$env:PYTHONUTF8=1; uv run kuru-setup-db

# 2. Re-ingest TCAS if also wiped
$env:PYTHONUTF8=1; uv run kuru-ingest-tcas

# 3. Run the full curriculum ingest (leave running overnight)
$env:PYTHONUTF8=1; uv run kuru-ingest-mko

# 4. Verify with the demo chatbot
$env:PYTHONUTF8=1; uv run kuru-demo
```

---

### Pausing and resuming

**You can safely Ctrl+C at any time.** Re-running the same command resumes automatically —
any file that already has chunks in Supabase is skipped. No data is lost on a clean stop.

```powershell
# Just re-run the same command — it skips completed files and continues from where it stopped
$env:PYTHONUTF8=1; uv run kuru-ingest-mko
```

---

### Crash recovery

**Mostly safe.** Each file goes through two phases:

| Phase | Duration | If crash here |
|-------|----------|---------------|
| OCR (Gemini API) | ~8 min/file | Nothing written to DB → file retried on next run ✓ |
| Embed + Supabase upsert | ~5–10 sec/file | Partial chunks may be in DB → file skipped on next run ⚠ |

The crash risk window is small (upsert takes seconds vs OCR taking minutes). With 3 parallel
files, at most 3 files could be affected.

**If a file was partially ingested** (some chunks in DB but data looks wrong), force re-ingest it:

```powershell
# In a Python shell — delete chunks for a specific file then re-run ingest
$env:PYTHONUTF8=1; uv run python -c "
from kuru.db.supabase_client import get_client
db = get_client()
fname = 'ปร.ด._กีฏวิทยา_2565.pdf'   # replace with affected filename
db.table('chunks').delete().eq('source_file', fname).execute()
print('Deleted chunks for', fname)
"

# Then re-run ingest — it will re-process that file
$env:PYTHONUTF8=1; uv run kuru-ingest-mko
```

---

### Re-ingesting TCAS after the DB was cleared

If `tcas_records` was also wiped during debugging, re-ingest it first:

```powershell
$env:PYTHONUTF8=1; uv run kuru-ingest-tcas
```

---

### Checking ingestion progress mid-run

Open a second terminal and run:

```powershell
$env:PYTHONUTF8=1; uv run python -c "
from kuru.db.supabase_client import get_client
db = get_client()
count = db.table('chunks').select('id', count='exact').execute()
files = db.table('chunks').select('source_file').execute()
unique = len(set(r['source_file'] for r in files.data))
print(f'Chunks: {count.count}  |  Files ingested: {unique} / 260')
"
```
