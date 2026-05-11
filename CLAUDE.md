# CLAUDE.md

## Project Overview

KUru Pipeline — AI-powered academic advisor for Kasetsart University (KU).
Ingests มคอ.2 curriculum PDFs + TCAS admission PDFs, embeds them into Supabase pgvector,
extracts PLOs into Neo4j, and serves a Thai/English RAG chatbot.

## Commands

```bash
uv run kuru-download              # Download PDFs + xlsx + txt-redirect folders from Google Drive
uv run kuru-setup-db              # Create Supabase tables + Neo4j constraints
uv run kuru-ingest-mko            # Ingest curriculum docs for บางเขน (default)
uv run kuru-ingest-mko กำแพงแสน  # Ingest for a specific campus
uv run kuru-ingest-tcas           # Ingest TCAS PDFs + xlsx score spreadsheet
uv run kuru-demo                  # Interactive RAG chatbot CLI
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
Source files (PDF | DOCX | xlsx)
  -> text_extractor.py   PDF: PyMuPDF then Gemini Files API if scanned
                         DOCX: python-docx (paragraphs + table cells)
                         xlsx: openpyxl (sheet-by-sheet, structured columns)
  -> chunker.py          Section-aware char-based chunking (2000 chars, 200 overlap)
  -> embedder.py         Local multilingual-e5 -> Supabase chunks table
  -> plo_extractor.py    Gemini JSON extraction -> Neo4j graph  (PDF + DOCX)
  -> tcas_extractor.py   Gemini JSON extraction -> Supabase tcas_records table
                         (PDF: free-text prompt | xlsx: sheet text → same Gemini prompt)

download_data.py also:
  - Follows .txt redirect files (Drive folder URLs) -> downloads linked folders
  - Supports EXTRA_CAMPUS_FOLDERS dict for additional campuses

Query:
  user question
  -> detect TCAS / PLO / listing query type
  -> embed with multilingual-e5 (query: prefix)
  -> resolve program name (name_en match → name_th token match)
  -> if resolved: targeted similarity_search filtered to that program_id (prepended)
  -> pgvector similarity search via match_chunks RPC (probes=50, fetch 3x top_k)
  -> pythainlp tokenize question -> re-rank by filename match
  -> inject coverage note if program has known data gaps (no PLOs, scanned, etc.)
  -> if no chunks + no TCAS records: return honest "no data" message (no LLM call)
  -> if TCAS query:
       filter course chunks
       DB-level search per q_word + per chunk source file (5 records/program, round-preferred)
       sort matched by detected_round first
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
- **TCAS record matching** — searches DB directly per q_word first, then Thai words from every
  chunk's source filename. Takes 5 records per program (preferred round first) so no single
  program dominates the 30-record context window. Detected round is sorted to the front.
- **Round detection** — regex on `TCAS\d`, `round \d`, `รอบ\d` extracts the target round and
  prioritises those records, fixing cases where round1 records shadowed round3 results.

## Current Data State

- **Curriculum**: บางเขน — 33 programs (~9,300 chunks); กพส — 1 program (~69 chunks);
  กำแพงแสน and ศรีราชา not yet ingested (folder IDs needed)
- **TCAS**: 2,524 records — 1,463 round1 (PDF) + 1,061 round3 (PDF + xlsx spreadsheet)
- **name_en**: populated for all 32 ingested บางเขน programs (enables English query resolution)
- **IVFFlat**: `probes=50` — all 9,369 chunks searchable (see docs/ISSUES.md ISSUE-007)

## Known Issues / Limitations

1. **Most engineering PDFs lack PLO sections** — compact course-catalog format; PLO queries
   return "document does not contain PLO information." The LLM is told this via the coverage
   note in the prompt. Fix: find full มคอ.2 PDFs or scrape from KU registrar website.

2. **กำแพงแสน / ศรีราชา not ingested** — queries about those campuses return the no-data guard
   message. Fix: add folder IDs to `EXTRA_CAMPUS_FOLDERS` in `download_data.py`.

3. **OCR failure rate ~25%** — `gemini-2.5-flash-lite` fails on poor scans. Set
   `OCR_MODEL=google/gemini-2.5-flash` in `.env` before a full ingest run.

4. **TCAS coverage gaps** — only programs in our specific TCAS PDFs are covered.
   SKE Thai-language track is NOT in the TCAS data.

5. **Multi-program queries** — asking about 2+ programs simultaneously may only surface one
   program's TCAS data (TCAS lookup uses top chunk's filename).

6. **ศึกษาศาสตร์ program has wrong name_th** — stored as a form template title; Thai
   queries for "ศึกษาศาสตร์" will not resolve this program.

## Working Sample Queries

**TCAS / Admission (round-aware):**
- `What are the TCAS3 score requirements for Computer Engineering?`
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

- Add กำแพงแสน / ศรีราชา folder IDs to `EXTRA_CAMPUS_FOLDERS` in `download_data.py`, then:
  `uv run kuru-download --sync` + `uv run kuru-ingest-mko <campus>`
- Full 260-file re-ingest with `OCR_MODEL=google/gemini-2.5-flash` to fix ~25% OCR failures
- Fix ศึกษาศาสตร์ program: update `name_th` in Supabase programs table to the correct program name
- Ingest remaining TCAS rounds when PDFs become available
- Set up Neo4j connection (NEO4J_URI/USERNAME/PASSWORD in .env) for graph queries
- See `docs/STATUS.md` for full roadmap with effort estimates
