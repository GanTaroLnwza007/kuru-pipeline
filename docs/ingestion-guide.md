# Ingestion Guide

How to ingest curriculum PDFs and TCAS data into the KUru pipeline.

---

## Prerequisites

- `.env` file with `SUPABASE_URL`, `SUPABASE_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`
- PDFs already downloaded (`uv run kuru-download`)
- DB tables created (`uv run kuru-setup-db`)

---

## Commands

All commands must be run with `$env:PYTHONUTF8=1;` prefix in PowerShell (Windows UTF-8 fix).

### TCAS data (fast, run first)

```powershell
$env:PYTHONUTF8=1; uv run kuru-ingest-tcas
```

Takes a few minutes. Safe to re-run — skips already-ingested records.

---

### Curriculum PDFs

#### Test batch — 50 files across all faculties (~2 hrs)

Run this first before committing to the full ingest.

```powershell
$env:PYTHONUTF8=1; uv run kuru-ingest-mko --sample=50
```

#### Full ingest — all 260 files (~12 hrs, run overnight)

```powershell
$env:PYTHONUTF8=1; uv run kuru-ingest-mko
```

#### Specific campus

```powershell
$env:PYTHONUTF8=1; uv run kuru-ingest-mko กำแพงแสน
```

---

## Monitoring progress

Open a second terminal while ingest is running:

```powershell
$env:PYTHONUTF8=1; uv run python ingestion_monitor.py
```

Prints every 30s:
```
[10:15:32]  Files: 12/50  |  Chunks: 18,432  (+3 files, +4,210 chunks)  [running]
```

The ingest script itself also prints a heartbeat line every 30s so the terminal never looks frozen.

---

## Pausing and resuming

**Ctrl+C** stops the ingest immediately. Any file already fully committed to Supabase is safe.
Re-running the same command resumes from where it stopped — completed files are skipped automatically.

```powershell
# Resume — same command, picks up where it left off
$env:PYTHONUTF8=1; uv run kuru-ingest-mko --sample=50
```

Killing the terminal has the same effect as Ctrl+C.

---

## Clearing data

### Clear all curriculum chunks (keeps TCAS intact)

```powershell
$env:PYTHONUTF8=1; uv run python clear_chunks.py
```

### Clear a single file's chunks (force re-ingest)

```powershell
$env:PYTHONUTF8=1; uv run python -c "
from kuru.db.supabase_client import get_client
db = get_client()
fname = 'ปร.ด._กีฏวิทยา_2565.pdf'
db.table('chunks').delete().eq('source_file', fname).execute()
print('Cleared:', fname)
"
```

Then re-run the ingest command — that file will be re-processed.

---

## Crash recovery

The ingest is mostly crash-safe:

| Crash during | Data in DB | On next run |
|--------------|------------|-------------|
| OCR phase (~8 min) | Nothing written | File retried automatically ✓ |
| Embed/upsert phase (~5 sec) | Partial chunks possible | File skipped (use clear script above) ⚠ |
| File already done | Full chunks committed | Skipped ✓ |

The upsert window is only ~5 seconds out of ~8 minutes, so the risk is very low.

---

## After ingest — verify

```powershell
$env:PYTHONUTF8=1; uv run kuru-demo
```

Sample queries to test coverage:
- `What courses are in the Computer Engineering program?`
- `What are the PLOs for Entomology PhD?`
- `What are the TCAS3 requirements for Software and Knowledge Engineering?`
- `หลักสูตรวิศวกรรมไฟฟ้ามีรายวิชาอะไรบ้าง`
