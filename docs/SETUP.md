# KUru Pipeline — Setup Guide

This guide walks you through everything from getting API credentials to running the first demo.

---

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager (`pip install uv`)
- Node.js (only needed for `npx skills add`, optional)

---

## Step 1 — Get Your API Credentials

Fill in `.env` (copy from `.env.example`). Here's where to get each value:

### `GEMINI_API_KEY`
1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Click **Get API key** → **Create API key**
3. Copy the key — this is free tier (no billing required)

### `SUPABASE_URL` and `SUPABASE_KEY`
1. Go to your Supabase project dashboard
2. **Project Settings** → **API**
3. Copy **Project URL** → `SUPABASE_URL`
4. Copy **service_role** secret key → `SUPABASE_KEY`
   - Use `service_role` (not `anon`) so the pipeline can write to tables

### `DATABASE_URL`
1. Same page: **Project Settings** → **Database** → **Connection string** → **URI** tab
2. Replace `[YOUR-PASSWORD]` with your database password
3. Format: `postgresql://postgres:PASSWORD@db.PROJECT_REF.supabase.co:5432/postgres`

### `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`
1. Go to [console.neo4j.io](https://console.neo4j.io) → **New Instance** → choose **Free** (AuraDB Free)
2. Download the credentials file when prompted — it contains all three values
3. `NEO4J_URI` looks like: `neo4j+s://xxxxxxxx.databases.neo4j.io`

---

## Step 2 — Install Dependencies

```bash
uv sync
```

This creates `.venv/` and installs all packages from `pyproject.toml`.

---

## Step 3 — Apply the Supabase Schema

Open the **Supabase SQL Editor** for your project and run the contents of [`db/schema.sql`](../db/schema.sql).

This creates:
- `programs` table — canonical program registry
- `chunks` table — มคอ.2 text chunks with `vector(768)` embedding column
- `tcas_records` table — structured TCAS admission data
- `match_chunks()` RPC function — used by the RAG engine for similarity search

> If you have the Supabase MCP connected, just ask Claude to apply the schema directly.

---

## Step 4 — Set Up Neo4j Constraints

```bash
uv run kuru-setup-db
```

This creates the uniqueness constraints on `Faculty`, `PLO`, and `SkillCluster` nodes.
Neo4j must be running and reachable before this step.

---

## Step 5 — Download Raw Data from Google Drive

```bash
uv run kuru-download
```

Downloads PDFs from both Google Drive folders into:
- `data/raw/tcas1/` — TCAS Round 1 admission PDFs
- `data/raw/curriculum/` — มคอ.2 curriculum PDFs

**Requirement:** Both Drive folders must be set to **"Anyone with the link can view"**.
If the download fails with an access error, check the sharing settings on Google Drive.

---

## Step 6 — Ingest Curriculum Documents (มคอ.2)

The curriculum Drive folder contains subfolders per วิทยาเขต (campus). The pipeline filters by campus name automatically.

```bash
# Default: บางเขน campus only
uv run kuru-ingest-mko

# Other campuses (run directly):
uv run python -m kuru.scripts.ingest_curriculum กำแพงแสน
uv run python -m kuru.scripts.ingest_curriculum ศรีราชา
```

Program IDs are prefixed with the campus slug to avoid collisions, e.g.:
- `bangkhen_cpe` (วิศวกรรมคอมพิวเตอร์ บางเขน)
- `kamphaengsaen_agri` (เกษตร กำแพงแสน)

For each PDF in the campus subfolder, the pipeline:
1. Classifies pages (born-digital vs scanned)
2. Extracts text (PyMuPDF for born-digital; Gemini Vision for scanned pages)
3. Chunks text into ~500-token segments tagged by section type (`plo`, `course`, `admission`, `general`)
4. Embeds each chunk with `text-embedding-004` and stores in Supabase pgvector
5. Extracts PLOs via Gemini and writes `Faculty → PLO → SkillCluster` graph to Neo4j

A summary table is printed on completion showing chunks stored and PLOs extracted per file.

---

## Step 7 — Ingest TCAS Data

```bash
uv run kuru-ingest-tcas
```

For each PDF in `data/raw/tcas1/`, Gemini extracts structured admission records:
- Program name, faculty, round
- Quota, GPAX minimum
- Exam score criteria (TGAT/TPAT/A-Level weights)
- Portfolio requirements and deadlines

Records are stored in the `tcas_records` Supabase table.

---

## Step 8 — Run the RAG Demo

```bash
uv run kuru-demo
```

An interactive CLI chatbot. Type `samples` to see example queries. Ask anything in Thai or English:

```
You: วิศวกรรมคอมพิวเตอร์มี PLO อะไรบ้าง?
You: รอบ 1 คณะวิศวกรรมศาสตร์ต้องการ GPAX เท่าไหร่?
You: What skills will I develop studying Computer Science?
You: portfolio ต้องมีอะไรบ้างสำหรับการสมัคร round 1?
```

Answers are grounded in the ingested documents with source citations.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `KeyError: 'GEMINI_API_KEY'` | `.env` file not found or key not set |
| `gdown` download fails | Set Google Drive folders to "Anyone with the link can view" |
| Supabase upsert error on `chunks` | Schema not applied — run Step 3 |
| `match_chunks` RPC not found | The `match_chunks` function in `schema.sql` was not executed |
| Neo4j `ServiceUnavailable` | Instance is paused (AuraDB Free pauses after 3 days idle) — resume in [console.neo4j.io](https://console.neo4j.io) |
| Embedding dimension mismatch | Schema uses `vector(768)` for `text-embedding-004` — do not mix models |

---

## File Naming Convention for PDFs

The pipeline derives `program_id` from the PDF filename. Use this convention for best results:

```
{program_slug}_{document_type}_{year}.pdf

Examples:
  cpe_mko2_2567.pdf       → program_id: cpe
  ku-cs_mko2_2567.pdf     → program_id: ku-cs
  engineering_tcas1.pdf   → program_id: engineering
```

The first segment (before `_`) becomes the `program_id` used as the key across Supabase and Neo4j.
