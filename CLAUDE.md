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
  -> detect TCAS round (e.g. "TCAS3" -> round3)
  -> embed with multilingual-e5 (query: prefix)
  -> pgvector similarity search (fetch 3x top_k)
  -> pythainlp tokenize question -> re-rank by filename match
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

- **Curriculum**: บางเขน — 22 docs (20 PDFs + 1 DOCX + 1 image-only brochure recovered via OCR);
  กพส — 1 PDF ingested; txt-redirect folder (กพส/ศวท) downloads on next `kuru-download`
- **TCAS**: 2,524 records — 1,463 round1 (PDF) + 1,061 round3 (PDF + xlsx spreadsheet)
- **Neo4j**: PLOs extracted for ingested programs (30 PLOs for กพส CPE, 4 for บูรณาการศาสตร์ DOCX)

## Known Issues / Limitations

1. **PLO chunks missing for most engineering programs** — their PDFs use different section header
   formats not matched by chunker patterns. PLO queries only work for:
   - `วิศวกรรมโยธา-ชลประทาน` (civil engineering)
   - `พยาบาลสัตว์` (animal nursing)
   Fix: expand `SECTION_PATTERNS` in `chunker.py` and re-ingest.

2. **`แผ่นพับ วท.บ. (ศาสตร์แห่งแผ่นดินฯ).pdf`** — image-only brochure; now ingested via Gemini
   OCR fallback (4 chunks). Previously failed.

3. **Duplicate program_id** — two veterinary PDFs both map to `bangkhen_2565`. Cosmetic only.

4. **TCAS coverage gaps** — only programs in our specific TCAS PDFs are covered.
   SKE Thai-language track is NOT in the TCAS data.

5. **Multi-program queries** — asking about 2+ programs simultaneously may only surface one
   program's TCAS data (TCAS lookup uses top chunk's filename).

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

- Add กำแพงแสน / ศรีราชา folder IDs to `EXTRA_CAMPUS_FOLDERS` in `download_data.py`, then re-run
  `kuru-download` + `kuru-ingest-mko <campus>`
- Fix PLO detection: add more header patterns to `chunker.py` SECTION_PATTERNS, re-ingest
- Populate `name_en` in programs table to improve English program name resolution
- Set up Neo4j connection (NEO4J_URI/USERNAME/PASSWORD in .env) for graph queries
- Ingest remaining TCAS rounds when PDFs become available
