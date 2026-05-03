# KUru Pipeline

AI-powered academic advisor for Kasetsart University (KU). Ingests มคอ.2 curriculum PDFs and TCAS admission PDFs, embeds them into Supabase pgvector, and serves a Thai/English RAG chatbot.

## Stack

| Component | Implementation |
|-----------|----------------|
| Embeddings | Local `intfloat/multilingual-e5-base` (sentence-transformers, 768-dim, no API quota) |
| Generation | `gemini-2.5-flash-lite` via OpenRouter (`google/gemini-2.5-flash-lite`) |
| Vector DB | Supabase PostgreSQL + pgvector (IVFFlat index, `probes=50`) |
| Graph DB | Neo4j Aura (PLO graph — optional, not required for RAG) |
| Package manager | `uv` |

---

## Quick Start

```bash
uv sync                        # install deps
cp .env.example .env           # fill in credentials (see docs/SETUP.md)
uv run kuru-setup-db           # create Supabase tables + Neo4j constraints
uv run kuru-download --sync    # download PDFs from Google Drive
uv run kuru-ingest-mko         # ingest บางเขน curriculum (default campus)
uv run kuru-ingest-tcas        # ingest TCAS admission data
uv run kuru-demo               # start interactive RAG chatbot
```

See [docs/SETUP.md](docs/SETUP.md) for full setup walkthrough including credentials.

---

## CLI Commands

| Command | What it does |
|---------|--------------|
| `uv run kuru-download` | Full download of TCAS + curriculum PDFs from Google Drive |
| `uv run kuru-download --sync` | Download only files missing locally (incremental) |
| `uv run kuru-download --list` | List Drive folder contents without downloading |
| `uv run kuru-setup-db` | Apply `db/schema.sql` to Supabase; create Neo4j constraints |
| `uv run kuru-ingest-mko` | Ingest curriculum PDFs for บางเขน campus |
| `uv run kuru-ingest-mko กำแพงแสน` | Ingest a specific campus by name |
| `uv run kuru-ingest-tcas` | Ingest TCAS PDFs + xlsx score spreadsheet |
| `uv run kuru-demo` | Interactive RAG chatbot CLI |
| `uv run kuru-coverage` | Show per-program data coverage report |
| `uv run kuru-coverage --populate-names data/program_name_mapping.csv` | Upload English program names to Supabase |

---

## Architecture

```
Source files (PDF | DOCX | xlsx)
  -> text_extractor.py   PDF: PyMuPDF (born-digital) → Gemini OCR fallback (scanned)
                         DOCX: python-docx
                         xlsx: openpyxl
  -> chunker.py          Section-aware chunking (~2000 chars, 200 overlap)
                         Tags chunks as: plo | course | general
                         Skips ภาคผนวก folders; deduplicates PDF+DOCX pairs
  -> embedder.py         Local multilingual-e5-base → Supabase chunks table
  -> plo_extractor.py    Gemini JSON extraction → Neo4j (optional)
  -> tcas_extractor.py   Gemini JSON extraction → Supabase tcas_records table

Query pipeline:
  user question
  -> detect TCAS / PLO / listing query type
  -> embed with multilingual-e5 (query: prefix)
  -> resolve program name (English name_en match, then Thai name_th token match)
  -> if resolved: targeted similarity search for that program (prepended to results)
  -> pgvector similarity search via match_chunks RPC (probes=50, fetch 3×top_k)
  -> re-rank by filename token overlap with question
  -> if TCAS: filter course chunks, fetch matching tcas_records from DB
  -> inject coverage note if program has known data gaps (no PLOs, scanned, etc.)
  -> if no chunks and no TCAS data: return honest "no data" message (no LLM call)
  -> Gemini generate answer with context
```

---

## Current Data State

| Campus | Programs | Chunks | TCAS records |
|--------|----------|--------|--------------|
| บางเขน | ~33 | ~9,300 | 2,524 (round1 + round3) |
| กพส | 1 | ~69 | — |
| กำแพงแสน | 0 | 0 | — |
| ศรีราชา | 0 | 0 | — |

Run `uv run kuru-coverage` to see the live breakdown by coverage status.

---

## Sample Queries

**Curriculum (Thai)**
```
วิศวกรรมคอมพิวเตอร์ที่ KU เรียนอะไรบ้าง
หลักสูตรวิศวกรรมเครื่องกลมีวิชาอะไรบ้าง
```

**Curriculum (English)**
```
What courses does Computer Engineering cover?
Tell me about the Nursing Science program.
What is Software and Knowledge Engineering about?
```

**TCAS / Admission**
```
What are the TCAS3 score requirements for Computer Engineering?
วิศวกรรมคอมพิวเตอร์ต้องใช้คะแนนอะไรบ้างในการสมัคร
How can I apply to Aerospace Engineering?
```

**PLO** (limited to programs with PLO sections in their PDFs)
```
หลักสูตรวิศวกรรมโยธา-ชลประทาน มี PLO อะไรบ้าง
```

---

## Known Limitations & Gaps

See [docs/STATUS.md](docs/STATUS.md) for the full roadmap and gap analysis.

**Critical gaps right now:**
- **Only บางเขน ingested** (~33 of ~260 programs). กำแพงแสน and ศรีราชา campuses have zero data; queries about those programs return a "no data" message.
- **Most engineering PDFs have no PLO sections** — they use a compact course-catalog format (`courses_only` coverage). PLO queries for these programs will honestly say the document doesn't contain PLO information.
- **Scanned PDFs excluded** — สถาปัตย์ (Architecture) PDFs are image-only scans and cannot be processed by the native text pipeline.
- **Multi-program queries** — asking about 2+ programs simultaneously may only surface one program's TCAS data.
