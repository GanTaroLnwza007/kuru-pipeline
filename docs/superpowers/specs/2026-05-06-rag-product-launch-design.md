# KUru RAG Product Launch Design
_Created: 2026-05-06 | Deadline: 2026-05-15 (course 01219462 final submission)_

---

## Context

This spec covers the work needed to go from a working CLI RAG engine to a
demo-ready, graded submission for **01219462 — Software Engineering for
AI-Enabled System**.

**Two repos involved:**
- `D:\work\project\kuru-pipeline` — Python RAG engine (embeddings, Supabase,
  Gemini generation). The brains.
- `https://github.com/GanTaroLnwza007/kuru` — Next.js frontend + FastAPI
  backend. The face.

**Grading criteria (from `docs/project_poc_submission.pdf`):**

| Weight | Criterion |
|--------|-----------|
| 30% | Technical Correctness & Completeness |
| 20% | Code Quality & Documentation |
| 20% | Thoughtfulness of Design Decisions |
| 15% | Critical Analysis & Reflection (honest about limitations) |
| 15% | Innovation & Creativity |

Key tasks from the rubric that this spec directly addresses:
- **A2.3** — User Interaction Design (confidence display, prompting vs automation)
- **A2.4** — Feedback Collection and Model Monitoring
- **B-7** — Model Deployment as a Service (FastAPI)
- **C-1** — UI Design (mockups, feedback mechanism, uncertainty display)
- **C-2** — UI-Model Interface Design (API contract, sequence diagram)
- **C-3** — Interface Testing (web app integration with 3 test scenarios)

---

## Is the RAG Good Enough?

**Yes — for this PoC.** What works:
- Thai + English query resolution
- TCAS round-aware retrieval (rounds 1 and 3)
- No-data guard (honest "no data" instead of hallucination)
- Coverage-aware prompting (tells LLM when PLOs are missing)
- Re-ranking by Thai token match on filename

**One visible gap that breaks the demo:** No conversation memory — "What is
CPE?" followed by "How do I apply?" confuses the engine. Fix this first.

**Honest limitations to document (not bugs to hide):**
- Only บางเขน campus ingested (~33 of ~260 programs)
- ~25% OCR failure rate on scanned PDFs
- PLOs missing for most วิศวฯ programs (compact course-catalog format)
- Multi-program queries only surface one program's TCAS data

---

## Four Problems & Decisions

### 1. Conversation Memory

**Decision: Stateless with injected history (frontend owns state)**

The frontend (Zustand) holds the chat history. Each request sends the last 5
turns. The backend prepends them into the Gemini prompt as "Previous
conversation context." No server-side session store needed.

Why: Zero server state, survives restarts, fits existing `query()` function,
and the frontend already manages turns in Zustand.

### 2. Confidence Display

**Decision: Derive `confidence_level` from top similarity score**

| Score | Level | UI treatment |
|-------|-------|-------------|
| ≥ 0.5 | `"high"` | Green badge |
| ≥ 0.35 | `"medium"` | Yellow badge |
| < 0.35 or no chunks | `"low"` | Red badge + disclaimer text |

The similarity scores already exist in `QueryResult.sources`. No new ML needed.

For A2.3 (how to present AI uncertainty): this is the "annotation" approach —
show a confidence indicator alongside the answer rather than hiding uncertainty.

### 3. Influencing User Behavior

**Decision: Guided prompting + scope statement**

- Show example questions in the UI chat input area ("Try: What is Computer
  Engineering about?")
- Display a static scope note: "Covers KU บางเขน programs · TCAS Rounds 1 & 3"
- When `confidence_level == "low"`, append a disclaimer below the answer:
  "ข้อมูลนี้อาจไม่ครบถ้วน / This answer may be incomplete."

This satisfies A2.3.1 (prompting approach with explanation) and the "minimize
consequences of flawed predictions" requirement.

### 4. Feedback Collection

**Decision: Thumbs up/down per answer → Supabase `feedback` table**

New endpoint: `POST /api/v1/chat/feedback`

New Supabase table `feedback`:
```sql
CREATE TABLE feedback (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  session_id  text,
  question    text,
  answer      text,
  rating      smallint,   -- 1 = helpful, -1 = not helpful
  created_at  timestamptz DEFAULT now()
);
```

This satisfies A2.4 (feedback collection mechanism) and C-1 (show how users
provide feedback on predictions).

---

## API Contract

### `POST /api/v1/chat`

**Request:**
```json
{
  "message": "How do I apply to Computer Engineering?",
  "session_id": "uuid-optional",
  "program_context_id": null,
  "conversation_history": [
    { "role": "user",      "content": "What is Computer Engineering?" },
    { "role": "assistant", "content": "Computer Engineering covers..." }
  ]
}
```

**Response:**
```json
{
  "answer": "For TCAS Round 3, CPE requires...",
  "session_id": "uuid",
  "confidence_level": "high",
  "sources": [
    {
      "source_file": "CPE-69-TCAS3.pdf",
      "section_type": "tcas",
      "similarity": 0.71
    }
  ],
  "used_tcas_data": true
}
```

**Schema changes from current stub:**
- `ChatRequest`: add `conversation_history: list[ConversationTurn]` (optional, default `[]`)
- `ChatResponse`: add `confidence_level: str`, `sources: list[SourceChunk]`, `used_tcas_data: bool`
- New model: `ConversationTurn` with `role: str` and `content: str`

### `POST /api/v1/chat/feedback`

**Request:**
```json
{
  "session_id": "uuid",
  "question": "How do I apply?",
  "answer": "For TCAS Round 3...",
  "rating": 1
}
```

**Response:** `{ "ok": true }`

---

## Workspace Setup (resume on any machine)

### Prerequisites
- Python 3.12+, Node 20+, `uv` installed
- Access to both GitHub repos

### Step 1 — Clone both repos as siblings
```powershell
cd D:\work\project
git clone https://github.com/GanTaroLnwza007/kuru.git
# kuru-pipeline should already be here
```

### Step 2 — Wire kuru-pipeline into the FastAPI backend
In `D:\work\project\kuru\backend\pyproject.toml`, add under `[tool.uv.sources]`:
```toml
[tool.uv.sources]
kuru-pipeline = { path = "../../kuru-pipeline", editable = true }
```
And add `"kuru-pipeline"` to `[project].dependencies`.

Then:
```powershell
cd D:\work\project\kuru\backend
uv sync
```

### Step 3 — Copy .env
```powershell
cp D:\work\project\kuru-pipeline\.env D:\work\project\kuru\backend\.env
```

### Step 4 — Run both services
```powershell
# Terminal 1 — FastAPI backend
cd D:\work\project\kuru\backend
uv run uvicorn main:app --reload --port 8000

# Terminal 2 — Next.js frontend
cd D:\work\project\kuru\frontend
npm install
npm run dev
# → http://localhost:3000
```

---

## Implementation Plan (9 days to May 15)

| Day | Task | Maps to rubric |
|-----|------|---------------|
| 1 | Clone kuru repo, wire path dependency, verify import works | B-7 setup |
| 1 | Add `ConversationTurn` model, extend `ChatRequest` + `ChatResponse` | C-2 |
| 2 | Implement conversation history injection in `query()` | A2.3, B-7 |
| 2 | Add `confidence_level` derivation from similarity scores | A2.3, C-1 |
| 3 | Create `feedback` Supabase table | A2.4 |
| 3 | Implement `POST /api/v1/chat/feedback` endpoint | A2.4, C-1 |
| 4 | End-to-end test: frontend ↔ backend ↔ kuru-pipeline | C-3 |
| 4 | Document 3 test scenarios (TCAS query, curriculum query, follow-up question) | C-3 |
| 5–9 | Write Part A (design doc, risk analysis, ML canvas) and Part B notebooks | A, B |

---

## Open Questions / Not Yet Decided

- Does the frontend chat UI already send `conversation_history` or does that
  need to be added in the frontend too? (Check `frontend/src/app/(chat)/`)
- Does the backend need MLflow for B-4 model versioning, or will we document
  the RAG pipeline experiments differently?
- Sequence diagram for C-2 — draw in Mermaid or as an image?
