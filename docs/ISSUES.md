# KUru Pipeline — Known Issues Log

---

## ISSUE-001 — Gemini free tier daily quota exhausted

**Status:** Blocked (resets daily)
**Date encountered:** 2026-04-05
**Affected steps:** All Gemini API calls — text extraction, PLO extraction, embedding

### Symptom
```
RetryError[<Future ... raised ClientError>]
embedding: RetryError[...]
PLO extraction: RetryError[...]
```
All 22 PDFs fail with `chunks=0 PLOs=0`.

### Root cause
Gemini free tier quotas (per API key, per day, Pacific time reset):

| Model | Daily limit | Per-minute limit |
|-------|------------|-----------------|
| `gemini-2.5-flash` | **20 req/day** | 15 RPM |
| `gemini-1.5-flash` | 1,500 req/day | 15 RPM |
| `gemini-embedding-001` | 1,500 req/day | 100 RPM |

Repeated failed ingestion runs across the day burned through the `gemini-2.5-flash` daily quota.
Switching to `gemini-1.5-flash` was done (see fix below) but the API key's overall quota may
have also been flagged temporarily after excessive retry attempts.

### Fix applied
- Switched all generation calls from `gemini-2.5-flash` → `gemini-1.5-flash`
- Updated retry config: 5 attempts, backoff 10s–120s
- Added 15s sleep between files in `ingest_curriculum.py`

### Resolution
Wait for quota reset (~07:00 Thai time = midnight Pacific), then re-run:
```bash
uv run kuru-ingest-mko
```

### Long-term options
- Use `gemini-1.5-flash` (1,500 req/day) — sufficient for full ingestion run
- Use Groq API (llama-3.3-70b, 14,400 req/day free) for generation, keep Gemini for embeddings
- Use Ollama locally (unlimited, no API key needed)

---

## ISSUE-002 — Gemini Files API TypeError on Thai filenames (Windows)

**Status:** Partially fixed — one file still fails
**Date encountered:** 2026-04-05
**Affected file:** `หลักสูตรเทคนิคการสัตวแพทย์_ฉบับปรับปรุง 2565.pdf`

### Symptom
```
Gemini Files extraction failed: RetryError[<Future ... raised TypeError>]
```
Only affects scanned PDFs with Thai-only filenames on Windows.

### Root cause
The Gemini Files API SDK on Windows throws `TypeError` when the file path contains Thai
characters, even after copying to a temp file. The issue is in how the SDK reads the filename
for the multipart upload boundary.

### Fix applied
Changed upload method to copy to a temp file with an ASCII path before uploading:
```python
with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
    tmp.write(pdf_path.read_bytes())
    tmp_path = Path(tmp.name)
uploaded = client.files.upload(file=tmp_path, ...)
```

### Remaining issue
`หลักสูตรเทคนิคการสัตวแพทย์_ฉบับปรับปรุง 2565.pdf` continues to fail — this file may be
corrupted or in an unsupported PDF format. The `TypeError` suggests the SDK itself is crashing
internally, not returning an API error.

### Investigation results

- File opens correctly with PyMuPDF: **85 pages, not corrupted**
- The failure is purely in the Gemini Files API upload path on Windows
- Root cause is likely `UploadFileConfig` being passed incorrectly, or the SDK
  still reading the original Thai path from the `Path` object metadata internally

### Next steps

Try passing the temp file as an open file handle instead of a Path, and drop `UploadFileConfig`:

```python
with open(tmp_path, "rb") as f:
    uploaded = client.files.upload(file=f)
```

Can only test after ISSUE-001 (quota) is resolved.

---

## ISSUE-003 — Wrong embedding model name

**Status:** Fixed
**Date encountered:** 2026-04-05

### Symptom
```
404 NOT_FOUND: models/text-embedding-004 is not found for API version v1beta
```

### Root cause
`text-embedding-004` does not exist in the `google-genai` SDK's v1beta endpoint.
Available embedding models are:
- `gemini-embedding-001` (3072 dims, truncatable to 768)
- `gemini-embedding-2-preview`

### Fix applied
- Changed `EMBEDDING_MODEL` from `"text-embedding-004"` → `"gemini-embedding-001"` in
  `embedder.py` and `query_engine.py`
- Added `output_dimensionality=768` to `EmbedContentConfig` to match the `vector(768)` schema

---

## ISSUE-004 — `config` dict rejected by embed_content

**Status:** Fixed
**Date encountered:** 2026-04-05

### Symptom
Embedding silently fails or raises `ClientError` even with valid API key.

### Root cause
`google-genai` SDK does not coerce plain dicts for the `config` parameter of `embed_content`.
Must use `types.EmbedContentConfig(...)`.

### Fix applied
```python
# Before (broken)
config={"task_type": "RETRIEVAL_DOCUMENT"}

# After (correct)
config=types.EmbedContentConfig(
    task_type="RETRIEVAL_DOCUMENT",
    output_dimensionality=768,
)
```

---

## ISSUE-005 — MemoryError on large scanned PDFs

**Status:** Fixed
**Date encountered:** 2026-04-05

### Symptom
```
MemoryError
  File "chunker.py" in _split_into_chunks
    chunks.append(Chunk(...))
```

### Root cause
Two separate bugs:
1. tiktoken `encode()` loads the entire document token array into memory — OOM on 200+ page scanned PDFs
2. Infinite loop in character chunker: `pos = end - OVERLAP_CHARS` bounced back past the loop
   guard condition, creating millions of identical chunks until memory was exhausted

### Fix applied
- Removed tiktoken entirely; replaced with character-based chunking (4 chars ≈ 1 token)
- Added loop termination: `if end >= len(text): break` before computing next `pos`

---

## ISSUE-006 — Slow ingestion (page-by-page OCR)

**Status:** Fixed
**Date encountered:** 2026-04-05

### Symptom
Single PDF taking 10–20 minutes to process. Error on page 202:
```
Page 202: OCR failed — RetryError[...]
```

### Root cause
Original implementation sent each scanned page as a separate Gemini Vision API call.
A 200-page scanned PDF = 200 individual API calls.

### Fix applied
Replaced page-by-page OCR with Gemini Files API — uploads the entire PDF in one call
regardless of page count. Processing time reduced from ~20 min → ~30 sec per PDF.
