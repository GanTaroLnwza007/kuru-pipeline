# KUru — Faculty & Advisor Meeting Prep
> Date: 2026-04-07 | Authors: Thanawat Tantijaroensin, Phantawat Luengsiriwattana

---

## 1. Current Implementation State

### What works today (CLI pipeline)
| Component | Status | Notes |
|-----------|--------|-------|
| PDF/DOCX/xlsx download | ✅ Done | Google Drive, txt-redirect folders supported |
| Text extraction | ✅ Done | PyMuPDF + Gemini OCR fallback for scanned PDFs |
| Curriculum chunking + embedding | ✅ Done | 768-dim multilingual-e5, stored in Supabase |
| TCAS structured extraction | ✅ Done | Round 1 (1,463 records) + Round 3 (1,061 records) |
| PLO extraction → Neo4j | ⚠️ Partial | Works for 2 programs only (see §3 Known Issues) |
| RAG chatbot (CLI) | ✅ Done | Thai + English, TCAS round-aware |
| Web frontend | ❌ Not started | Entire UI layer |
| RIASEC elicitation | ❌ Not started | |
| Program recommendation engine | ❌ Not started | Schema only, no O\*NET data |
| PLO spider chart | ❌ Not started | |
| Portfolio readiness checker | ❌ Not started | |
| Curriculum timeline | ❌ Not started | |
| User auth / saved profiles | ❌ Not started | |

### Data ingested so far
- **Curriculum chunks:** บางเขน — 22 docs (20 PDF + 1 DOCX + 1 OCR-recovered)  กพส — 1 PDF
- **TCAS records:** 2,524 total (Round 1 PDF + Round 3 PDF + xlsx score spreadsheet)
- **Neo4j PLOs:** 2 programs (วิศวกรรมโยธา-ชลประทาน, พยาบาลสัตว์)

---

## 2. Data Gaps — What We Need from Faculty

### 2.1 Missing มคอ.2 Curriculum Documents
We have documents for ~22 programs under บางเขน. The SRS targets the **top 50 most popular programs** across Engineering, Science, and Business faculties. Major gaps:

| Faculty area | Status |
|---|---|
| วิศวกรรมศาสตร์ (most programs) | ⚠️ Partially ingested — PLO extraction broken (see §3) |
| วิทยาการคอมพิวเตอร์ (CS) | ❌ No มคอ.2 in data |
| วิทยาศาสตร์ (general science programs) | ❌ Unknown |
| บริหารธุรกิจ / เศรษฐศาสตร์ | ❌ Unknown |
| สถาปัตยกรรมศาสตร์ | ❌ Unknown |
| กำแพงแสน campus (all programs) | ❌ Need Google Drive folder URL |
| ศรีราชา campus (all programs) | ❌ Need Google Drive folder URL |

**Ask faculty:** Can you share มคอ.2 PDFs (or Google Drive folder links) for all programs you want covered?

### 2.2 TCAS Data Gaps
- **Rounds 2 and 4**: Not ingested. We only have Rounds 1 and 3 PDFs.
- **Round coverage by program**: Patchy — only programs in our specific PDFs are covered. Many programs (e.g. CS, architecture) have no TCAS data at all.

**Ask faculty:** Do you have TCAS announcement PDFs or Excel data for Rounds 2 and 4? Can we get a complete list of all KU TCAS programs per round?

### 2.3 Portfolio Criteria Data
The **Portfolio Readiness Checker** (UC-12) requires pre-extracted faculty criteria schemas for the top 10 programs. This cannot be automatically derived — it needs formal faculty input.

**Ask faculty:** What are the official portfolio requirements for each Round 1 program? Can you provide them in a structured format (required items, GPAX minimum, specific documents needed)?

### 2.4 English Program Names
The `programs` table has no `name_en` column populated. English queries like "Computer Sciences" fail to resolve correctly because there is no English↔Thai program name mapping.

**Ask faculty/advisor:** Is there an official English name list for all KU programs? (Even a spreadsheet would work.)

---

## 3. Known Technical Issues (Internal — For Transparency)

### 3.1 PLO Extraction Fails for Most Engineering Programs (**Critical**)
**Problem:** The curriculum chunker identifies PLO sections using Thai header patterns (e.g. "ผลลัพธ์การเรียนรู้ของหลักสูตร"). Engineering มคอ.2 PDFs use different header formats not matched by the current patterns.

**Result:** PLOs are only extracted for 2 of 22 ingested programs. The entire Neo4j recommendation graph is nearly empty.

**Fix required:** Read each engineering PDF, find the actual PLO section headers, expand `SECTION_PATTERNS` in `chunker.py`, re-ingest.

**Ask faculty:** Can you confirm the standard PLO section heading used in your faculty's มคอ.2 template? Is it standardized across the faculty, or does each department use different formatting?

### 3.2 English → Thai Program Disambiguation ("Computer Sciences" Bug)
**Problem:** Querying "Computer Sciences" returns Computer Engineering (CPE) instead of Computer Science (CS). Root cause: no CS curriculum PDF exists in the data, and English words aren't mapped to Thai program names.

**Pending fix:** Add English→Thai keyword hint map in the query engine so "sciences" → "วิทยา" (narrowing to วิทยาการคอมพิวเตอร์) vs "engineering" → "วิศวกรรม".

### 3.3 Some Scanned PDFs Still Fail OCR
`หลักสูตรเทคนิคการสัตวแพทย์_ฉบับปรับปรุง 2565.pdf` fails Gemini Files API upload (SDK bug on Windows with Thai filenames). Content not ingested.

### 3.4 กำแพงแสน/ศรีราชา Campuses Not Downloaded
Placeholder exists in `download_data.py` but no folder IDs provided yet. Add Drive URLs → run `kuru-download` → run `kuru-ingest-mko กำแพงแสน`.

---

## 4. Should We Scrape from the Web?

The SRS states curriculum data comes from **official KU curriculum documents provided by faculty**. Web scraping is a possible fallback if faculty cannot provide PDFs directly.

**Options:**

| Source | Data available | Risk |
|---|---|---|
| `ku.ac.th` faculty pages | Some program descriptions, not PLOs | Terms of service unclear |
| `mytcas.com` | Full TCAS data for all programs/rounds | Public data, likely acceptable |
| `reg.ku.ac.th` | Course catalog (not PLOs) | Requires KU account |

**Recommendation:** Use `mytcas.com` to fill TCAS coverage gaps for rounds 2 and 4 — it is the official national TCAS portal and publicly accessible. This would give us complete TCAS data for all KU programs without needing faculty to provide PDFs.

**Ask advisor:** Is web scraping mytcas.com acceptable for the project? Should we integrate it into the pipeline?

---

## 5. Questions for the Faculty Committee

| # | Question | Why it matters |
|---|---|---|
| F1 | Can you share Google Drive folders for **กำแพงแสน** and **ศรีราชา** campus มคอ.2 documents? | Without these, those campus programs are entirely missing |
| F2 | Which **50 programs** should be prioritized for the MVP? | Focuses ingestion and evaluation effort |
| F3 | What is the standard PLO section heading in engineering มคอ.2 documents? | Fixes PLO extraction for all engineering programs |
| F4 | Do you have **TCAS Round 2 and Round 4** PDFs or Excel data? | Rounds 2 and 4 are completely missing |
| F5 | Can you provide official **English program names** for all KU programs? | Needed for English query resolution |
| F6 | What are the formal **portfolio requirements** for Round 1 programs (top 10)? | Required for Portfolio Readiness Checker (UC-12) |
| F7 | Are there any programs with **non-standard มคอ.2 formats** we should know about? | Prevents silent ingestion failures |

---

## 6. Questions for the Advisor

| # | Question | Why it matters |
|---|---|---|
| A1 | Is scraping **mytcas.com** acceptable for completing TCAS data coverage? | Would give us all rounds without waiting for faculty PDFs |
| A2 | How should we handle **O\*NET Thai localization**? O\*NET is US-centric — should we use a Thai occupational database or translate O\*NET? | Required for Pipeline A (career-to-RIASEC matching) |
| A3 | Do you have **evaluation test questions** in mind for the RAGAS assessment? | SRS specifies RAGAS for RAG quality + MRR/NDCG@5 for recommendation |
| A4 | What is the **POC scope** for the April 2026 deadline? SRS says "RAG chatbot + recommendation engine with RIASEC elicitation." Can we agree on a minimal demo? | Clarify what "working demonstration" means concretely |
| A5 | Should we target a **web app** for the April POC, or is a CLI demo acceptable? | Frontend is the largest missing piece |

---

## 7. Priority Fixes Before the Demo (Internal Roadmap)

Based on the SRS April 2026 POC target:

### Immediate (this week)
1. **Fix PLO extraction** — expand `SECTION_PATTERNS` in `chunker.py`, re-ingest engineering docs
2. **Fix English disambiguation** — add English→Thai keyword hints in `query_engine.py`
3. **Ingest กำแพงแสน/ศรีราชา** — once Drive folder IDs received from faculty

### Short-term (pipeline completeness)
4. **Populate `name_en`** in programs table (manual or faculty-provided)
5. **Scrape mytcas.com** for rounds 2 and 4 TCAS data
6. **Load O\*NET data** into Supabase pgvector for career matching

### For POC demo (April 2026)
7. **RIASEC elicitation** — implement the 12-step questionnaire (UC-01)
8. **Program recommendation engine** — Pipeline A (O\*NET) + Pipeline B (Neo4j PLO match)
9. **Web UI** — at minimum, chatbot + TCAS guide + recommendation results
10. **PLO spider chart** — Neo4j → radar chart visualization

---

## 8. Summary for Faculty Meeting

**What we've built:**
- A working AI chatbot that can answer questions about KU programs and TCAS admission in Thai and English, grounded in official curriculum documents.
- A data ingestion pipeline that processes มคอ.2 PDFs, DOCX files, and TCAS spreadsheets automatically.

**What we need from faculty:**
- มคอ.2 documents for all target programs (especially CS and กำแพงแสน/ศรีราชา)
- TCAS data for Rounds 2 and 4
- Official portfolio criteria for Round 1 programs
- English program name list
- Confirmation of PLO section header format in engineering documents

**What we're building next:**
- RIASEC interest elicitation quiz
- Program recommendation engine (linking interests → careers → KU programs)
- Web application frontend
- PLO spider chart visualization
