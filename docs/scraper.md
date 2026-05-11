# Curriculum Scraper

Scrapes มคอ.2 curriculum PDFs from [registrar.ku.ac.th](https://registrar.ku.ac.th/cur/all) and saves them locally so the existing `kuru-ingest-mko` pipeline can process them unchanged.

**Scope:** Bangkhen campus, latest curriculum version per program only.  
**Source:** 22 faculty pages, ~273 PDFs (public, no authentication required).

---

## Prerequisites

Dependencies are already declared in `pyproject.toml`. If you haven't synced yet:

```bash
uv sync
```

No API keys or credentials are needed — the registrar website is public.

---

## Running the scraper

### 1. Dry run (recommended first step)

Prints every PDF that *would* be downloaded without touching the filesystem:

```bash
uv run kuru-scrape-curriculum --dry-run
```

Example output:
```
[agri] https://registrar.ku.ac.th/agri
  found 27 program(s)
  [dry]   วท.บ._วิทยาศาสตร์เกษตร_2564.pdf
          https://registrar.ku.ac.th/wp-content/uploads/...
  ...

[eng] https://registrar.ku.ac.th/eng
  found 42 program(s)
  ...

Done — would download: 273, skipped: 0, failed: 0
```

Check that `failed: 0` before proceeding. Any faculty pages that 404 or time out will show `[ERROR]` lines and increment the failed counter.

### 2. Full download

```bash
uv run kuru-scrape-curriculum
```

PDFs are saved to:

```
data/raw/curriculum/บางเขน/
├── agri/
│   ├── วท.บ._วิทยาศาสตร์เกษตร_2564.pdf
│   └── ...
├── eng/
│   ├── วศ.บ._วิศวกรรมคอมพิวเตอร์_2565.pdf
│   └── ...
└── ...
```

The scraper is **resume-safe** — re-running it skips files that already exist (shown as `[skip]`). Partial downloads (e.g. from a network error) are deleted automatically so they don't corrupt the dataset.

---

## Output status codes

| Code | Meaning |
|------|---------|
| `[dry]` | Dry-run only — file would be downloaded |
| `[dl]` | File downloaded successfully |
| `[skip]` | File already exists locally, skipped |
| `[ERROR]` | Fetch or download failed (check stderr) |

---

## After downloading — ingest into the pipeline

Once the PDFs are on disk, run the existing ingest command unchanged:

```bash
uv run kuru-ingest-mko
# or for a specific campus subfolder:
uv run kuru-ingest-mko บางเขน
```

---

## Testing the scraper

### Quick smoke test — single faculty

The fastest way to verify the scraper works is to temporarily limit it to one faculty. You can do this by editing `BANGKHEN_SLUGS` in the source, or just run:

```bash
uv run python - <<'EOF'
import httpx
from bs4 import BeautifulSoup
from kuru.scripts.scrape_curriculum import _parse_faculty_page, BASE_URL

with httpx.Client() as c:
    r = c.get("https://registrar.ku.ac.th/eng", timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")

programs = _parse_faculty_page(soup, BASE_URL)
for name, year, url in programs[:5]:
    print(f"{year}  {name}")
    print(f"     {url}")
EOF
```

Expected: 5 engineering programs printed with year (25xx) and a `wp-content/uploads/...pdf` URL.

### Verify a downloaded PDF is readable

After a real download, confirm PyMuPDF can extract text from a file:

```bash
uv run python - <<'EOF'
from pathlib import Path
from kuru.ingestion.text_extractor import extract_text_auto, full_text

pdf = next(Path("data/raw/curriculum/บางเขน").rglob("*.pdf"))
pages = extract_text_auto(pdf, verbose=True)
text = full_text(pages)
print(f"File : {pdf.name}")
print(f"Pages: {len(pages)}")
print(f"Chars: {len(text)}")
print(f"Method: {pages[0].extraction_method}")
print("\nFirst 300 chars:")
print(text[:300])
EOF
```

A healthy PDF should show `method: pymupdf`, `chars > 500`, and readable Thai/English text.

### End-to-end: scrape → ingest → query

```bash
# 1. Download (or dry-run first)
uv run kuru-scrape-curriculum --dry-run
uv run kuru-scrape-curriculum

# 2. Ingest
uv run kuru-ingest-mko

# 3. Sanity-check with the demo chatbot
uv run kuru-demo
# Try: "What courses will I take in Computer Engineering?"
```

---

## Troubleshooting

**`failed: N` with `[ERROR] fetch ...`**  
The registrar site may be temporarily down or a faculty URL may have changed. Re-run after a few minutes. If a slug consistently 404s, check `BANGKHEN_SLUGS` in `src/kuru/scripts/scrape_curriculum.py`.

**`no programs found` for a faculty**  
The HTML table structure for that faculty page differs from the expected format. Fetch the page manually and inspect the table layout:
```bash
uv run python -c "import httpx; print(httpx.get('https://registrar.ku.ac.th/<slug>').text[:3000])"
```

**PDFs download but ingest produces 0 chunks**  
The PDF is likely image-only (scanned). The ingest pipeline will fall back to the vision OCR path automatically via OpenRouter. Check the ingest log for `Vision OCR` messages.

**Windows terminal shows `?` instead of Thai characters**  
Run the terminal in UTF-8 mode:
```powershell
chcp 65001
```
Or set the environment variable `PYTHONUTF8=1` before running.
