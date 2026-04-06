# CLAUDE.md

## Project Overview

KUru Pipeline — AI-powered academic advisor for Kasetsart University (KU).
Ingests มคอ.2 curriculum PDFs + TCAS admission PDFs, embeds them into Supabase pgvector,
extracts PLOs into Neo4j, and serves a Thai/English RAG chatbot.

## Commands

```bash
uv run kuru-download       # Download PDFs from Google Drive
uv run kuru-setup-db       # Create Supabase tables + Neo4j constraints
uv run kuru-ingest-mko     # Ingest มคอ.2 curriculum PDFs (Bangkhen campus)
uv run kuru-ingest-tcas    # Ingest TCAS admission PDFs
uv run kuru-demo           # Interactive RAG chatbot CLI
```

## Stack

| Component | Implementation |
|-----------|----------------|
| Embeddings | Local `intfloat/multilingual-e5-base` (sentence-transformers, 768-dim, no API quota) |
| Generation | `gemini-2.5-flash-lite` via `google-genai` SDK (pay-as-you-go, same GEMINI_API_KEY) |
| Vector DB | Supabase PostgreSQL + pgvector |
| Graph DB | Neo4j Aura Free |
| Package manager | `uv` |

## Architecture

```
PDF files
  -> text_extractor.py   PyMuPDF (born-digital) or Gemini Files API (scanned fallback)
  -> chunker.py          Section-aware char-based chunking (2000 chars, 200 overlap)
  -> embedder.py         Local multilingual-e5 -> Supabase chunks table
  -> plo_extractor.py    Gemini JSON extraction -> Neo4j graph
  -> tcas_extractor.py   Gemini JSON extraction -> Supabase tcas_records table

Query:
  user question
  -> embed with multilingual-e5 (query: prefix)
  -> pgvector similarity search (fetch 3x top_k)
  -> pythainlp tokenize question -> re-rank by filename match
  -> if TCAS query: filter course chunks, fetch matching tcas_records
  -> Gemini generate answer with context
```

## Key Design Decisions

- **Embeddings are local** — avoids 1,000/day Gemini embedding quota. `passage:` prefix for
  docs, `query:` prefix for queries (multilingual-e5 asymmetric retrieval).
- **Re-ranking** — fetches 3x more chunks than needed, boosts chunks whose source filename
  contains Thai tokens from the question (pythainlp tokenization), then trims to top_k.
  If top chunk strongly matches a program (score >= 10), fills context from that program first.
- **TCAS query detection** — `TCAS_KEYWORDS` regex (broad: includes apply/enroll/qualify/etc.)
  triggers: (1) filter out `course` section chunks (prevent course prerequisite hallucination),
  (2) fetch matching TCAS structured records from `tcas_records` table.
- **TCAS record matching** — tries question keywords first, then falls back to Thai words from
  ALL retrieved chunk filenames (so "Computer Engineering" finds วิศวกรรมคอมพิวเตอร์ records).

## Current Data State

- **Curriculum**: 20/22 Bangkhen PDFs ingested (1 skipped/already done, 1 image-only brochure)
- **TCAS**: 574 records across 16 PDF files (rounds 1 and 3, various scholarship tracks)
- **Neo4j**: PLOs extracted for ingested programs

## Known Issues / Limitations

1. **PLO chunks missing for most engineering programs** — their PDFs use different section header
   formats not matched by chunker patterns. PLO queries only work for:
   - `วิศวกรรมโยธา-ชลประทาน` (civil engineering)
   - `พยาบาลสัตว์` (animal nursing)
   Fix: expand `SECTION_PATTERNS` in `chunker.py` and re-ingest.

2. **`แผ่นพับ วท.บ. (ศาสตร์แห่งแผ่นดินฯ).pdf`** — image-only brochure, always fails. Skip it.

3. **Duplicate program_id** — two veterinary PDFs both map to `bangkhen_2565`. Cosmetic only.

4. **TCAS coverage gaps** — only programs in our specific TCAS PDFs are covered.
   SKE Thai-language track is NOT in the TCAS data.

5. **Multi-program queries** — asking about 2+ programs simultaneously may only surface one
   program's TCAS data (TCAS lookup uses top chunk's filename).

## Working Sample Queries

**TCAS / Admission:**
- `Tell me about TCAS of Computer Engineering`
- `What are the TCAS requirements for Software and Knowledge Engineering?`
- `How can I apply to Computer Engineering and what qualifications do I need?`
- `วิศวกรรมคอมพิวเตอร์ต้องใช้คะแนนอะไรบ้างในการสมัคร`

**Curriculum:**
- `What courses will I take in Computer Engineering?`
- `What is Software and Knowledge Engineering about?`

**PLO (limited to programs with detected PLO sections):**
- `หลักสูตรวิศวกรรมโยธา-ชลประทาน มี PLO อะไรบ้าง`
- `เล่มหลักสูตรพยาบาลสัตว์มี PLO อะไรบ้าง`

## Next Steps (not yet done)

- Fix PLO detection: add more header patterns to `chunker.py` SECTION_PATTERNS, re-ingest
- Ingest กำแพงแสน and ศรีราชา campuses
- Ingest remaining TCAS rounds
- Set up Neo4j connection (NEO4J_URI/USERNAME/PASSWORD in .env) for graph queries
