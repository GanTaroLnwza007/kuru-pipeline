# KUru Pipeline — Setup Guide

Complete walkthrough from credentials to first demo.

---

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) — `pip install uv`
- A [Supabase](https://supabase.com) project with pgvector enabled
- A [Neo4j Aura Free](https://neo4j.com/cloud/platform/aura-graph-database/) instance _(optional — only needed for PLO graph queries)_
- An [OpenRouter](https://openrouter.ai) API key (for Gemini generation)
- Google Drive access to the KU curriculum folder (read-only link)

---

## Step 1 — Credentials

Copy `.env.example` to `.env` and fill in:

```env
# OpenRouter (LLM generation)
OPENROUTER_API_KEY=sk-or-...

# Supabase (vector store)
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_KEY=<service_role key>
DATABASE_URL=postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres

# Neo4j (PLO graph — optional)
NEO4J_URI=neo4j+s://<id>.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<password>
```

### Where to get each key

**`OPENROUTER_API_KEY`**
1. Sign up at [openrouter.ai](https://openrouter.ai)
2. Dashboard → **Keys** → **Create key**
3. Add credit ($5 is enough for a full ingest run)

**`SUPABASE_URL` and `SUPABASE_KEY`**
1. Supabase dashboard → **Project Settings** → **API**
2. Copy **Project URL** → `SUPABASE_URL`
3. Copy **service_role** key → `SUPABASE_KEY` (not the `anon` key — write access needed)

**`DATABASE_URL`**
1. Same page → **Database** → **Connection string** → **URI** tab
2. Replace `[YOUR-PASSWORD]` with your database password

**`NEO4J_*`** _(skip if not using PLO graph)_
1. [console.neo4j.io](https://console.neo4j.io) → **New Instance** → **Free**
2. Download the generated credentials file — it contains all three values

---

## Step 2 — Install Dependencies

```bash
uv sync
```

Creates `.venv/` and installs everything from `pyproject.toml`. The multilingual-e5 embedding model (~280 MB) is downloaded on first query automatically.

---

## Step 3 — Apply the Database Schema

```bash
uv run kuru-setup-db
```

This connects to Supabase via `DATABASE_URL` and executes `db/schema.sql`, which creates:

| Object | Purpose |
|--------|---------|
| `programs` table | Canonical program registry (name_th, name_en, coverage, etc.) |
| `chunks` table | Document chunks with `vector(768)` embeddings |
| `tcas_records` table | Structured TCAS admission data |
| `match_chunks()` RPC | pgvector similarity search with `ivfflat.probes=50` for full recall |

> **Note:** Neo4j constraints are also applied here. If Neo4j is not configured, a DNS error is printed but the Supabase setup still completes.

---

## Step 4 — Download Raw Data

```bash
# First time — download everything
uv run kuru-download

# Subsequent runs — only fetch files missing locally
uv run kuru-download --sync
```

Downloads into:
- `data/native/tcas/` — TCAS PDFs + xlsx score spreadsheets
- `data/native/curriculum/บางเขน/` — มคอ.2 curriculum PDFs (บางเขน campus)
- `data/native/curriculum/กพส/` — กพส campus PDFs
- Any folders linked via `.txt` redirect files (followed automatically)

**If a file fails to download** (permission or gdown glitch), add its Drive file ID to `MANUAL_RETRY` in `download_data.py` and re-run.

**For additional campuses** (กำแพงแสน, ศรีราชา): add the Drive folder IDs to `EXTRA_CAMPUS_FOLDERS` in `download_data.py` once you have the links.

---

## Step 5 — Ingest Curriculum Documents (มคอ.2)

```bash
# บางเขน campus (default)
uv run kuru-ingest-mko

# Specific campus
uv run kuru-ingest-mko กำแพงแสน
uv run kuru-ingest-mko ศรีราชา
```

For each document, the pipeline:
1. Skips ภาคผนวก (appendix) subfolders and DOCX files when a same-stem PDF exists
2. Extracts text — PyMuPDF for born-digital PDFs; Gemini OCR fallback for scanned pages
3. Chunks text into ~2,000-char segments tagged by section type (`plo` / `course` / `general`)
4. Embeds each chunk with local `multilingual-e5-base` and upserts into Supabase
5. Extracts PLOs via Gemini and writes to Neo4j (skipped if Neo4j not configured)
6. Updates the program's `coverage` field in the `programs` table

**OCR quality:** The default OCR model (`google/gemini-2.5-flash-lite`) has a ~25% failure rate on poor scans. For a full ingest run, set `OCR_MODEL=google/gemini-2.5-flash` in `.env` to use the stronger model (~$25 for 260 files vs ~$5, but far fewer failures).

After ingestion, check coverage:
```bash
uv run kuru-coverage
```

---

## Step 6 — Populate English Program Names

```bash
uv run kuru-coverage --populate-names data/program_name_mapping.csv
```

Uploads English names from the CSV to the `programs` table. Required for English-language queries like "Computer Engineering courses" to resolve to the correct program. The CSV is pre-filled for all currently ingested บางเขน programs — add rows for new campuses as you ingest them.

---

## Step 7 — Ingest TCAS Data

```bash
uv run kuru-ingest-tcas
```

Processes TCAS PDFs and xlsx spreadsheets from `data/native/tcas/`. Extracts structured records (quotas, GPAX minimums, exam weights, deadlines) into the `tcas_records` table. Currently covers round1 and round3 for บางเขน programs.

---

## Step 8 — Run the Chatbot

```bash
uv run kuru-demo
```

Interactive CLI. Type `samples` to see example queries, `q` or `exit` to quit.

The embedding model loads on startup (~5 seconds). First query after a cold start may take 2–3 seconds longer.

---

## Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `KeyError: OPENROUTER_API_KEY` | `.env` missing or not loaded | Check `.env` file exists in project root |
| gdown download fails | Drive folder not public | Set folder to "Anyone with the link can view" |
| `match_chunks RPC not found` | Schema not applied | Run `uv run kuru-setup-db` |
| Queries return wrong program | `name_en` not populated | Run `kuru-coverage --populate-names` |
| CPE / other program chunks missing | IVFFlat probes too low | `kuru-setup-db` re-applies the function with `probes=50` — run it |
| Neo4j `ServiceUnavailable` | AuraDB Free pauses after 3 days idle | Resume at [console.neo4j.io](https://console.neo4j.io) |
| `choices=None` / OCR garbage | Weak OCR model on poor scan | Set `OCR_MODEL=google/gemini-2.5-flash` in `.env` |
| Thai text garbled in terminal | Windows console encoding | Set `PYTHONUTF8=1` environment variable |
