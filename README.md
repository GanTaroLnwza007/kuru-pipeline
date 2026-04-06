# KUru Pipeline

AI-powered academic advisor for Kasetsart University (KU). Ingests มคอ.2 curriculum PDFs and TCAS admission PDFs, embeds them into Supabase pgvector, extracts PLOs into Neo4j, and serves a Thai/English RAG chatbot.

## Stack

| Component | Implementation |
|-----------|----------------|
| Embeddings | Local `intfloat/multilingual-e5-base` (sentence-transformers, 768-dim) |
| Generation | `gemini-2.5-flash-lite` via `google-genai` SDK |
| Vector DB | Supabase PostgreSQL + pgvector |
| Graph DB | Neo4j Aura |
| Package manager | `uv` |

---

## Prerequisites

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/getting-started/installation/) installed
- A [Supabase](https://supabase.com) project with pgvector enabled
- A [Neo4j Aura](https://neo4j.com/cloud/platform/aura-graph-database/) free instance
- A [Google AI Studio](https://aistudio.google.com) API key (for Gemini)

---

## Setup

### 1. Clone and install dependencies

```bash
git clone <repo-url>
cd kuru-pipeline
uv sync
```

### 2. Configure environment variables

Create a `.env` file in the project root:

```env
# Supabase
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_KEY=<your-anon-or-service-role-key>
DATABASE_URL=postgresql://postgres:<password>@db.<project-ref>.supabase.co:5432/postgres

# Neo4j
NEO4J_URI=neo4j+s://<your-instance>.databases.neo4j.io
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=<your-password>

# Gemini
GEMINI_API_KEY=<your-google-ai-studio-key>
```

### 3. Enable pgvector in Supabase

In your Supabase dashboard go to **Database → Extensions** and enable `vector`, or it will be enabled automatically when you run `kuru-setup-db`.

### 4. Initialize the databases

```bash
uv run kuru-setup-db
```

This applies `db/schema.sql` to Supabase (creates `programs`, `chunks`, `tcas_records` tables and the `match_chunks` RPC function) and creates Neo4j constraints.

---

## Ingesting Data

### Download PDFs

```bash
uv run kuru-download
```

Downloads curriculum and TCAS PDFs from Google Drive into `data/raw/`.

### Ingest curriculum PDFs (มคอ.2)

```bash
uv run kuru-ingest-mko
```

Extracts text from each PDF (PyMuPDF for born-digital, Gemini Files API fallback for scanned), chunks it, embeds with multilingual-e5, and upserts into Supabase. Also extracts PLOs into Neo4j.

### Ingest TCAS admission PDFs

```bash
uv run kuru-ingest-tcas
```

Uses Gemini to extract structured admission records (quotas, score requirements, deadlines) and stores them in the `tcas_records` table.

---

## Running the RAG Chatbot

```bash
uv run kuru-demo
```

Starts an interactive CLI chatbot. Type `samples` at the prompt to see example questions, or `q` / `exit` to quit.

The embedding model is pre-loaded on startup so the first query doesn't appear frozen.

---

## Testing the RAG

Once data is ingested, use the demo CLI to verify retrieval quality with these sample queries:

**TCAS / Admission (English)**
```
Tell me about TCAS of Computer Engineering
What are the TCAS requirements for Software and Knowledge Engineering?
How can I apply to Computer Engineering and what qualifications do I need?
```

**TCAS / Admission (Thai)**
```
วิศวกรรมคอมพิวเตอร์ต้องใช้คะแนนอะไรบ้างในการสมัคร
```

**Curriculum**
```
What courses will I take in Computer Engineering?
What is Software and Knowledge Engineering about?
```

**PLO** (limited to programs with detected PLO sections in their PDFs)
```
หลักสูตรวิศวกรรมโยธา-ชลประทาน มี PLO อะไรบ้าง
เล่มหลักสูตรพยาบาลสัตว์มี PLO อะไรบ้าง
```

Each response shows a **Sources** table listing the retrieved chunks (filename, section type, similarity score) so you can verify the retrieval is pulling from the right documents.

---

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

---

## Known Limitations

- **PLO chunks** — only detected for programs whose PDFs use matched section header patterns. Currently works for `วิศวกรรมโยธา-ชลประทาน` and `พยาบาลสัตว์`.
- **Multi-program queries** — asking about 2+ programs simultaneously may only surface one program's TCAS data.
- **TCAS coverage** — only programs present in the ingested TCAS PDFs are covered. SKE Thai-language track is not included.
- **Image-only PDFs** — `แผ่นพับ วท.บ. (ศาสตร์แห่งแผ่นดินฯ).pdf` cannot be processed; skip it.
