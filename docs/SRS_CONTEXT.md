# KUru SRS — Full Context Reference (PROPOSAL VERSION)

> **Purpose:** This document is a complete, readable summary of the KUru Software Requirements Specification for use by AI agents reviewing or extending the proposal.
>
> ⚠️ **PROPOSAL STATE:** This document reflects the **condensed proposal version** (Chapters 1–4 and Schedule). Sections not included in the proposal (Abstract, Acknowledgement, Chapters 6–7, Sections 5.1–5.3) are noted as hidden. For the full technical specification, refer to the full SRS document.

---

## Project Identity

- **Title:** KUru: An AI-powered academic pathway advisor for students exploring programs at Kasetsart University
- **Authors:** Thanawat Tantijaroensin (6610545294), Phantawat Luengsiriwattana (6610545871)
- **Academic Year:** 2568
- **Advisor:** Jitti Niramitranon

---

## Preamble — PROPOSAL VERSION

**This context document reflects the condensed PROPOSAL version of the KUru SRS.**

**Included in Proposal:**
- Cover pages with "(Proposal)" designation
- Chapters 1–4 (Introduction, Literature Review, Requirement Analysis, Software Architecture)
- Section 5.4 (Schedule only)

**Hidden in Proposal:**
- Abstract and Acknowledgement sections
- Chapter 5 Sections 5.1–5.3 (Development Methodology, Technology Stack, Coding Standards)
- Chapter 6 (Deliverables)
- Chapter 7 (Conclusion and Discussion)
- Appendices

**Schedule Focus:** April 2026 (P1 Foundation + P2 Core AI) and January–March 2027 (P3 Features + P4 Polish & Evaluation). **Proof of Concept:** By end of April 2026, core AI features (RAG chatbot + recommendation engine with RIASEC elicitation) will be delivered as a working demonstration. May–December 2026 background development period is not detailed in the proposal.

---

## Abstract (Hidden in Proposal)

KUru is an AI-powered academic pathway navigation system for Kasetsart University (KU). The system addresses a clearly defined problem: students who are interested in exploring career paths or programs at KU lack personalized, structured guidance when selecting programs for TCAS applications.

The system employs a Retrieval-Augmented Generation (RAG) pipeline grounded in official KU curriculum documents (มคอ.2) to enable semantic question-answering over program content in both Thai and English. A Neo4j knowledge graph maps KU faculties, Program Learning Outcomes (PLOs), skill clusters, and career paths, enabling multi-hop reasoning from a student's interest profile to personalized program recommendations. An interest discovery interface grounded in Holland's RIASEC vocational model, presenting six sequential Likert rating screens grounded in RIASEC dimensions, builds an initial student interest profile that is progressively refined through implicit behavioral signals. The system serves **prospective students only (pre-admission)**; features for enrolled KU students are out of scope.

The system covers KU programs for which มคอ.2 documents are available; MVP targets the top 50 most popular programs across Engineering, Science, and Business faculties, with full coverage dependent on data availability from faculty advisors. The portfolio readiness checker is scoped to the top 10 most popular KU programs in the MVP. The system is evaluated using the RAGAS framework for RAG quality and MRR and NDCG@5 for recommendation quality.

---

## Chapter 1 — Introduction

### 1.1 Background

Thailand's university admission system, TCAS (Thai University Central Admission System), requires students to select and apply to specific faculties through up to four rounds, each with distinct requirements, quotas, and criteria. Kasetsart University (KU) offers programs spanning agriculture, engineering, science, humanities, business, and more.

Program Learning Outcomes (PLOs) formally document the competencies a graduate will have developed, defined for every accredited Thai program in มคอ.2 documents. These are the authoritative source of what a program produces, yet they are inaccessible: written in formal Thai, formatted inconsistently, and distributed as PDFs without structured interfaces.

Prospective students — whether finishing high school, taking a gap year, or reconsidering options — must make high-stakes decisions with limited structured guidance.

### 1.2 Problem Statement

High school students selecting KU programs for TCAS lack personalized, grounded guidance that connects their interests to specific program PLOs, career outcomes, and admission requirements. Existing tools are either generic (general-purpose LLMs with no KU-specific data) or static (official faculty web pages with no personalization or synthesis).

The consequence is suboptimal faculty selection, contributing to higher rates of program dissatisfaction, transfer requests, and dropout.

### 1.3 Solution Overview

KUru is a bilingual (Thai and English) web application that serves as an intelligent advisor for students exploring career paths or programs at KU. The system is grounded in official KU curriculum documents provided by faculty, making its guidance specific, accurate, and authoritative.

**The system focuses exclusively on students at the pre-admission stage.**

The core AI architecture combines a RAG pipeline over มคอ.2 curriculum documents with a Neo4j knowledge graph connecting faculties, PLOs, skills, and careers. All recommendations are grounded in retrieved curriculum content, not generated from model weights alone.

**Features:**

1. **Interest Discovery:** A twelve-step adaptive elicitation interface grounded in Holland's RIASEC vocational model: (1) six sequential Likert rating screens, one per RIASEC dimension (R/I/A/S/E/C), each presenting 4 Thai-language statements rated on a 5-point scale (1 = ไม่เห็นด้วยอย่างมาก, 5 = เห็นด้วยอย่างมาก) — raw scores per dimension summed (max 20); (2) one global confidence check screen applying a scalar (1.0 / 0.75 / 0.5) to all six dimension scores; (3) 4–6 adaptive pairwise forced-choice questions targeting only dimension pairs where |score_A − score_B| < 3 after confidence scaling; (4–6) 3 scenario questions with A–F role options mapped to RIASEC dimensions, adjusting scores proportionally; and (7) a profile summary page with an optional dealbreaker filter zeroing out explicitly rejected dimensions before L2-normalisation. Output is a normalised 6-dimensional RIASEC vector. Total time: 2–4 minutes. A blending weight α shifts the system progressively from RIASEC-based to behavioural-signal-based recommendations as interaction data accumulates.

2. **Program Recommendation Engine:** Ranked list of KU programs matched to the student's RIASEC interest profile using a hybrid recommendation architecture combining two independent signals: a career-side signal (Pipeline A) matching the student's RIASEC vector against O\*NET occupation data via pgvector, and a curriculum-side signal (Pipeline B) matching against KU program PLO profiles via Neo4j and course content via pgvector semantic search. Final score = 0.35 × A-score + 0.65 × B-score. Recommendations explained in plain language covering the full chain from interests to career alignment to curriculum fit. Covers all KU programs for which มคอ.2 documents are available.

3. **PLO Spider Chart Visualizer:** Interactive radar chart showing the skill profile a student will develop, overlaid with the student's interest profile for visual fit assessment.

4. **KUru Advisor:** RAG-powered Q&A over มคอ.2 documents supporting Thai and English queries.

5. **TCAS Admission Guide:** Structured per-faculty, per-round admission information including GPAX requirements, TGAT/TPAT/A-Level criteria, portfolio requirements, and deadlines.

6. **Saved Profile Dashboard:** Optional login to persist interest profile, bookmarked programs, and TCAS deadline tracking.

7. **PLO Explorer with Semantic Search:** Browsable and searchable directory of all KU programs. Students can search using natural language queries in Thai or English (e.g., "หลักสูตรที่เรียน AI เน้นโปรเจกต์ รับ TGAT ต่ำ"). Queries parsed into structured constraints (topic areas, teaching methods, TCAS requirements) and matched via multi-source parallel query. Students can pin up to 4 programs to a persistent comparison tray for side-by-side comparison, batch portfolio checking, and multi-program chatbot queries.

8. **Portfolio Readiness Checker:** Student uploads a portfolio PDF; Gemini extracts a structured portfolio profile (activities, certificates, academic records, personal statement). System performs a four-part gap analysis (hard threshold eligibility, required item coverage, preferred item strength, qualitative criteria) against pre-extracted faculty criteria schemas. Output: eligibility status, portfolio strength profile, prioritised gap list, deadline-aware action recommendations. MVP scope: top 10 programs. Excludes programs requiring creative work evaluation.

9. **Curriculum Timeline Visualiser:** For any KU program, shows a visual map of what the student will study across 4 years. Course composition, teaching method breakdown, and time commitment per year extracted from มคอ.2 during ingestion. Gemini synthesises this structured data into natural-language year narratives on demand.

10. **Program Comparison:** Students pin up to 4 programs and compare side-by-side: overlaid PLO radar charts, career path overlap, curriculum character profile across 5 dimensions (theory vs. project, individual vs. team, lab vs. lecture, early specialisation vs. broad foundation, industry connection vs. academic focus), TCAS accessibility per round, and RIASEC fit scores.

### 1.4 Target Users

**Prospective KU applicants (pre-admission):** Anyone considering KU programs before making an enrollment decision. Includes high school students (Mathayom 4–6) preparing for TCAS, gap-year students reconsidering options, and anyone exploring KU programs. No prior KU enrollment assumed. Users may access without an account; login unlocks profile persistence, saved programs, and deadline notifications.

### 1.5 Terminology

| Term | Definition |
|------|-----------|
| PLO | Program Learning Outcome — formally defined competency graduates are expected to develop, as documented in มคอ.2 |
| CLO | Course Learning Outcome — course-level outcome, documented in มคอ.3; contributes to PLOs |
| มคอ.2 | Thai Qualifications Framework program specification document containing PLOs, curriculum structure, and admission requirements |
| มคอ.3 | Course-level specification detailing CLOs, teaching methods, and assessment for each course |
| TCAS | Thai University Central Admission System — national university admission platform, up to four rounds per year |
| TGAT/TPAT/A-Level | Standardized national examinations used as admission criteria in TCAS Rounds 2–4 |
| RAG | Retrieval-Augmented Generation — retrieves relevant passages from a corpus and provides them as context to an LLM before generating a response |
| Knowledge Graph | Graph database where nodes represent entities (faculties, PLOs, skills, careers) and edges represent typed relationships |
| O\*NET | Occupational Information Network — US Department of Labor database cataloguing ~900 occupations with structured skill requirements; used as the career-to-skill data layer |
| RIASEC | Holland's six vocational personality types: Realistic, Investigative, Artistic, Social, Enterprising, Conventional. Used as the theoretical framework for interest elicitation and as the native classification system of the O\*NET occupational database |
| Holland Code | A two-letter code formed from a person's two most dominant RIASEC types (e.g., IR for Investigative-Realistic), used as a human-readable summary of an individual's vocational interest profile |

---

## Chapter 2 — Literature Review and Related Work

### 2.1 Competitor Analysis

Five categories of existing solutions are relevant:

#### 2.1.1 KU Official Information Channels
KU's official website and faculty pages provide static information. PLO information is available only within มคอ.2 PDFs without structured interfaces. TCAS information is scattered across the main KU admissions page, individual faculty pages, and mytcas.com. No personalization, synthesis, or guidance is offered. Information exists but is not actionable for students making decisions.

#### 2.1.2 General-Purpose LLMs
ChatGPT and Gemini can respond to queries about KU programs but from training data rather than authoritative sources. This results in approximations and hallucinations for specific PLOs, current TCAS requirements, or quota numbers. No persistent memory across sessions, no structured outputs.

#### 2.1.3 University-Specific AI Advisors at Other Thai Institutions
**Knowva** (KMITL) and **ChulaGENIE** (Chulalongkorn University) are the closest competitors. Both are AI-assisted advising systems for specific Thai universities. Neither is available at KU, neither explicitly links PLOs to career skill requirements, and neither provides TCAS-specific admission guidance. ChulaGENIE focuses on course recommendation for enrolled students rather than pre-admission guidance.

#### 2.1.4 TCAS Information Platforms
**mytcas.com** (official national TCAS portal operated by the Ministry of Higher Education) aggregates admission data across all Thai universities. For each program, it presents per-round quotas, eligibility criteria (GPAX thresholds), score calculation methods (portfolio weighting, TGAT/TPAT/A-Level proportions), and links to faculty admission pages. Updated each TCAS cycle; authoritative source for students and universities.

Despite its comprehensiveness, mytcas.com is a passive information browser, not a guidance system. It presents raw admission data without connecting it to a student's interests, skills, or career goals. No discovery mechanism, no program matching, no PLO or career-path context. KUru is designed to complement mytcas.com by providing the personalized discovery and program-matching layer that sits upstream of the admission details mytcas.com supplies.

#### 2.1.5 Comparison Summary

| Feature | KU Website | mytcas.com | ChatGPT/Gemini | Knowva/ChulaGENIE | KUru (ours) |
|---------|-----------|-----------|----------------|-------------------|-------------|
| KU-specific curriculum data | Partial (PDF) | ✗ | ✗ | ✗ | Full (มคอ.2 RAG) |
| PLO visualization | ✗ | ✗ | ✗ | ✗ | Spider chart |
| Career-to-PLO mapping | ✗ | ✗ | ~ | ~ | Full graph |
| TCAS admission guide | Scattered | Full — all universities | ~ | ✗ | Structured, KU only |
| Personalization | ✗ | ✗ | Session-only | Basic | Progressive profile |
| Thai language support | ✓ | ✓ | ~ | ~ | ✓ |
| KU student skill tracking | ✗ | ✗ | ✗ | ✗ | Yes (Phase 2) |

### 2.2 Literature Review

#### 2.2.1 Retrieval-Augmented Generation (RAG)
Lewis et al. introduced RAG as an architecture combining dense retrieval with sequence-to-sequence generation for open-domain QA. Grounding generation in retrieved evidence substantially reduces hallucination and allows answering questions requiring specific factual knowledge not reliably encoded in model weights. Directly applicable to KUru's requirement to answer questions about specific PLO content, admission criteria, and course structures from มคอ.2 documents.

The RAGAS framework provides automated metrics for RAG pipeline quality including faithfulness, answer relevancy, and context recall.

#### 2.2.2 Knowledge Graphs for Educational Recommendation
Knowledge graph-based recommendation enables multi-hop reasoning that purely embedding-based approaches cannot support. Embedding-based retrieval can identify semantically similar items but cannot follow explicit typed relationships such as "this PLO develops this skill" or "this career requires this skill level." The Neo4j graph in KUru encodes these typed relationships explicitly, enabling recommendation paths that are both explainable and traceable to specific curriculum documents.

Abu-Rasheed et al. propose a conversational explainability approach where knowledge graph data is injected into LLM prompts to reduce hallucination risk while maintaining natural dialogue. This is the precise architectural pattern KUru uses: Neo4j provides the structured PLO-to-skill data, and Gemini generates the natural-language explanation from that data rather than from general knowledge.

#### 2.2.3 Adaptive Quiz and Interest Profiling
KUru's interest discovery interface is grounded in **Holland's RIASEC model** (Realistic, Investigative, Artistic, Social, Enterprising, Conventional), the dominant framework in vocational psychology for connecting individual interests to occupational environments. This theoretical foundation is directly compatible with KUru's O\*NET career data layer, which uses RIASEC codes to classify all 900+ occupations. Rather than presenting abstract RIASEC labels, KUru presents six sequential Likert screens using relatable Thai-language statements grounded in Holland's six dimensions, reducing cognitive load for a high school student audience while producing a more reliable initial vector than a tile-selection approach. The elicitation design is defined in §4.3.2 and the full question bank is documented in Appendix A.

The interface design is shaped by three evidence-based principles from the preference elicitation (PE) and recommender systems literature:

**First — Attribute-based elicitation:** Item-based approaches (asking users to evaluate individual items directly) are unsuitable when the item corpus is large, because no single item efficiently maps a new user's preference space. KUru instead presents topic clusters (attributes) that map directly to RIASEC dimensions and downstream skill vectors, enabling broad preference coverage in minimal interactions.

**Second — Minimal questionnaire:** An optimized Static Preference Questionnaire (SPQ) can reduce necessary questionnaire length by up to a factor of three while maintaining or improving recommendation quality. KUru's twelve-step adaptive design — (1) six Likert screens (4 statements per dimension, 5-point scale); (2) one global confidence check; (3) 4–6 adaptive pairwise questions targeting only ambiguous dimension pairs (delta < 3 points); (4) three scenario questions confirming the dominant signal; (5) an optional dealbreaker filter on the profile summary page — is substantially shorter than a full validated interest inventory while producing a more reliable initial vector than a tile-selection approach. The pairwise step is adaptive: students with a clearly differentiated profile encounter fewer questions, keeping total completion time within 2–4 minutes.

**Third — Cold-start + implicit profiling:** The system addresses the new user cold-start problem through explicit elicitation, then transitions to progressive implicit profiling. Behavioral signals including program page visits, chatbot queries, and saved items continuously refine the user's RIASEC vector without additional questioning. High-guidance elicitation (presenting structured options rather than open-ended prompts) produces significantly higher recommendation match scores than low-guidance alternatives.

**Limitation:** Interest-based elicitation has inherent limitations as a predictor of long-term academic fit. Meta-analytic research on full validated interest inventories reports approximately 50% accuracy in predicting eventual career choice even with substantially longer instruments. KUru's abbreviated elicitation is accordingly framed as a starting point for exploration rather than a definitive match, with recommendation confidence increasing as the implicit profiling layer accumulates behavioral signals.

This work applies established cold-start PE methods and the RIASEC vocational framework to academic pathway advising for Thai university applicants — a novel application context in which the user population (Thai high school students navigating TCAS), the item space (university programs defined by PLOs), and the decision stakes (a multi-year academic commitment) differ substantially from the content recommendation domains in which these methods were originally developed.

### 2.2.4 Hybrid Recommendation Architecture

KUru's recommendation pipeline is a hybrid system combining two independent signals: a knowledge-based signal derived from matching the student's RIASEC vector against O\*NET occupation profiles (Pipeline A), and a content-based signal derived from matching against KU program PLO profiles and course content via Neo4j and pgvector semantic search (Pipeline B). Hybrid recommender systems that combine independent evidence sources consistently outperform single-signal approaches by reducing the error compounding that occurs when one signal feeds sequentially into the next. In the previous single-chain design, an approximation introduced at the O\*NET-to-SkillCluster crosswalk step would propagate through to the final ranking; the parallel architecture eliminates this dependency. The final score weights curriculum-side evidence more heavily (65%) than career-side evidence (35%), reflecting the system's primary purpose: helping students understand what they will actually study at KU, not merely what careers they might eventually pursue.

---

## Chapter 3 — Requirement Analysis

### 3.1 Stakeholder Analysis

- **High school students (prospective KU applicants):** Primary users. Need personalized program recommendations, PLO-based skill previews, career path information, and structured TCAS guidance. Low technical proficiency expected.
- **KU Faculty / Academic Advisors:** Data providers. Provide มคอ.2 curriculum documents and TCAS admission data. Indirect beneficiaries through reduced advising load and better-prepared incoming students.
- **KU Admissions Office:** Indirect stakeholders. Benefit from better-informed applicants and reduced mismatched enrollments.
- **Development Team:** Two SKE students responsible for design, development, and evaluation within one semester.

### 3.2 User Stories

**High School Student:**
- Discover which KU programs match my interests to make an informed TCAS application.
- See what skills I will graduate with from a specific program to assess career alignment.
- Understand TCAS admission requirements for programs I am interested in.
- Ask questions about a program's curriculum in Thai without reading long PDFs.
- Save programs I am considering to compare later.

**Additional:**
- As a returning visitor, have my saved interest profile and bookmarked programs persist across sessions.
- As a parent, browse KU programs and understand what careers they lead to.

### 3.3 Key Use Cases

#### UC-01: Discover Interests
- **Actor:** Guest / High School Student
- **Precondition:** None — accessible without login
- **Flow:**
  1. Student opens KUru and navigates to ค้นหาความสนใจ. System presents six sequential screens, one per RIASEC dimension (R, I, A, S, E, C), each showing 4 Thai-language statements rated on a 5-point Likert scale. A progress bar shows current step out of 12 total.
  2. After completing all six Likert screens, system presents one confidence check screen: "คุณรู้สึกมั่นใจแค่ไหนกับคำตอบที่เพิ่งเลือก?" with three options (มั่นใจมาก = scalar 1.0, ค่อนข้างมั่นใจ = 0.75, ไม่แน่ใจเลย = 0.5). The scalar is applied globally to all six Likert-derived dimension scores.
  3. System identifies ambiguous dimension pairs where |score_A − score_B| < 3 after confidence scaling. Only pairs meeting this threshold are shown as adaptive pairwise forced-choice questions (maximum 4–6). Each pair presents two options with "ชอบเท่ากัน" as a middle choice.
  4. System presents 3 scenario questions (สถานการณ์ที่ 1–3), each offering A–F role options mapped to all six RIASEC dimensions. Student selects one preferred role per scenario. Scenario responses adjust dimension scores proportionally.
  5. System displays the profile summary page showing top 2 dominant dimensions as Holland Code, a bar chart of all 6 dimension scores (out of 20), and an optional dealbreaker filter: "มีสาขาไหนที่คุณไม่อยากเรียนเลย?" showing 6 dimension chips. Tapped dimensions are zeroed in the final vector regardless of score. "ไม่มี ข้ามได้เลย" is prominently shown.
  6. System applies L2-normalisation to the final 6-dimensional vector and stores it as the student's RIASEC profile. Student proceeds via "ดูผลลัพธ์".
- **Alternative Flow — Targeted re-elicitation:** If invoked from UC-02 with specific RIASEC dimensions flagged for clarification, the system skips Steps 1–2 and begins directly at Step 3, presenting only pairwise questions targeting the flagged dimensions. Steps 4–6 run normally. This path is triggered when the student selects "No" on the profile correction prompt in UC-02.
- **Postcondition:** Student has a RIASEC-grounded interest profile used as input to the career matching and program recommendation pipeline. Total elicitation time: 2–4 minutes across 12 steps.

#### UC-02: View Program Recommendations
- **Actor:** Guest / High School Student
- **Precondition:** Interest profile (RIASEC vector) has been built via UC-01
- **Flow:**
  1. System runs Pipeline A: queries precomputed O\*NET occupation RIASEC interest profiles in Supabase pgvector for occupations with the highest cosine similarity to the student's RIASEC vector. Top 10–15 form the internal career space. A-score computed per KU program based on career-program pathway alignment.
  2. System runs Pipeline B concurrently: (B1) queries Neo4j for KU programs whose PLO SkillCluster profiles best match the student's RIASEC-derived SkillCluster weight vector via cosine similarity; (B2) runs semantic search over course description embeddings in Supabase pgvector using the student's interest query. B-score = 0.4 × B1 + 0.6 × B2.
  3. System synthesises final score: 0.35 × A-score + 0.65 × B-score. Programs ranked by final score. Top-N programs selected for display.
  4. System displays ranked program cards, each showing fit score, matched career paths from Pipeline A, curriculum alignment themes from Pipeline B, and a plain-language explanation generated by Gemini grounded in both signals.
  5. Student can tap any card to navigate to the full program detail page at `/programs/[program-id]` — a full-page view, not a modal.
  6. System presents a profile correction prompt — "Do these recommendations feel right?" — on the first visit to the recommendation screen. If the student selects "No", the system returns them to a targeted re-elicitation of the RIASEC dimensions most influential in the current ranking, preventing a poor initial vector from entering the interaction log.
- **Postcondition:** Student sees a ranked list of KU programs with recommendations traceable from their interests through real-world careers to specific program outcomes via two independent evidence paths.

#### UC-03: Explore PLO Spider Chart
- **Actor:** Guest / High School Student
- **Precondition:** A program card is selected
- **Flow:**
  1. Student selects a KU program from the recommendation list.
  2. System retrieves PLO data from Supabase and skill mappings from Neo4j.
  3. System renders an interactive radar (spider) chart showing the skill profile the program develops.
  4. Student's interest profile is overlaid on the chart for visual fit comparison.
- **Postcondition:** Student has a visual understanding of the skills a program builds and how well they match their interests.

#### UC-04: Query KUru Advisor

- **Actor:** Guest / High School Student
- **Precondition:** มคอ.2 documents have been ingested and indexed in Supabase pgvector
- **Flow:**
  1. Student enters a question in Thai or English.
  2. System embeds the query using Gemini text-embedding-001.
  3. System retrieves the top semantically relevant มคอ.2 document chunks from pgvector.
  4. System passes chunks and question to Gemini 2.5 Flash with a strict citation instruction.
  5. System displays the generated answer with inline มคอ.2 source citation badges.
  6. The chatbot also handles TCAS questions for any program where admission data has been ingested — e.g., "Computer Engineering Round 1 ต้องการ GPAX เท่าไหร่?" or "Architecture portfolio ต้องมีอะไรบ้าง?" Answers are grounded in ingested TCAS data with source citations. If TCAS data for a requested program has not been ingested, the system returns the standard fallback message.
- **Alternative Flow:** If no relevant chunk is found, system responds: "This information was not found in the curriculum document."
- **Postcondition:** Student has received a cited answer grounded in the official curriculum document.

#### UC-05: View TCAS Admission Guide
- **Actor:** Guest / Registered User
- **Precondition:** TCAS admission data collected and structured per faculty and round. Students may also query TCAS information conversationally via the curriculum chatbot (UC-04), which draws from the same ingested data source.
- **Flow:**
  1. Student navigates to the TCAS Guide for a faculty.
  2. System displays structured breakdown of applicable rounds, score requirements (GPAX, TGAT/TPAT/A-Level), portfolio criteria, and deadlines.
  3. Student can filter by round and view side-by-side comparisons of faculties.
- **Postcondition:** Student understands the specific admission requirements to prepare for.

#### UC-06: Explore Career Paths
- **Actor:** Guest / High School Student
- **Precondition:** Interest profile has been built via UC-01
- **Flow:**
  1. Student taps "ดูอาชีพที่เหมาะกับคุณ" from the recommendation screen.
  2. System retrieves the top 7 O\*NET occupations (selected from the 10–15 matched internally during the recommendation pipeline) to display in the career explorer.
  3. System displays a career list; each card shows occupation title, Thai-localised description, top 3 required skills, and KU programs that develop those skills.
  4. Student taps a career card to expand detail.
  5. System shows the full O\*NET skill breakdown (35 standardized skills) and highlights which matched KU programs develop each skill, using Neo4j data.
  6. Student can navigate directly from a career card to the relevant program card.
- **Postcondition:** Student understands which careers align with their interests and which KU programs prepare them for those careers.

#### UC-07: Refine Profile Through Implicit Signals
- **Actor:** Registered User
- **Precondition:** Student is logged in and has an existing RIASEC profile from UC-01
- **Flow:**
  1. Student browses program cards, saves programs, checks TCAS guides, and asks chatbot questions.
  2. System records behavioral signals alongside the PLO skill profiles of the associated programs, weighted by interaction type: save (1.0), TCAS guide viewed (0.8), chatbot query about a program (0.6), card expanded (0.4), card viewed (0.1).
  3. System adjusts blending weight α based on accumulated interaction data. New user: α = 1.0 (pure RIASEC). After 3–5 meaningful interactions: α ≈ 0.5. Regular user: α ≈ 0.2 (behaviour-dominated). Ranking = α × RIASEC fit score + (1 − α) × behavioural fit score. Transition is smooth and invisible to the student.
  4. On the next session, the recommendation ranking reflects the updated blended profile.
  5. Student can view a summary of how their recommendation ranking has shifted under "โปรไฟล์ของคุณ", including a before/after comparison of highest-ranked programs.
- **Alternative Flow:** Student taps "รีเซ็ตโปรไฟล์" to clear accumulated interaction data and return to pure RIASEC recommendations (α = 1.0).
- **Fallback hierarchy (sparse collaborative data):** (1) sufficient similar-profile users exist → collaborative signal applied normally; (2) few similar users → α is held higher regardless of individual interaction count; (3) no similar users → pure RIASEC (α = 1.0).
- **Note on guests:** Interaction signals are only logged persistently for registered users. Guest interactions are session-scoped and do not update α across visits. Guests always begin a new session at α = 1.0.
- **Postcondition:** Recommendation ranking becomes progressively more personalised to the student's actual behaviour. The underlying RIASEC vector from elicitation remains fixed; the behavioural fit score is derived from the individual student's own interaction history (not from other users — true collaborative filtering across students is deferred to Phase 2) and operates as a separate signal blended at ranking time via α.

#### UC-08: Explain Why a Program Was Recommended
- **Actor:** Guest / High School Student
- **Precondition:** Student is viewing a program recommendation card
- **Flow:**
  1. Student taps "ทำไมถึงแนะนำคณะนี้?" on any program card.
  2. System retrieves the full reasoning chain: student RIASEC vector → matched O\*NET occupations → aggregated skill requirements → PLO matches → program.
  3. System generates a plain-language explanation via Gemini: "Based on your interest in [topic], you match careers like [Y] and [Z]. These careers require skills like [A] and [B]. This program develops both through its PLOs."
  4. Student can tap any career name in the explanation to navigate to its full detail in UC-06.
- **Postcondition:** Student understands the specific chain of reasoning behind a recommendation and can verify each step themselves.

#### UC-09: Search Programs Semantically

- **Actor:** Guest / High School Student
- **Precondition:** None — accessible without login
- **Flow:**
  1. Student enters a natural language query in Thai or English in the semantic search bar on the PLO Explorer.
  2. System uses Gemini to parse the query into a structured constraint object: topic areas, teaching methods, TCAS requirements, campus preferences.
  3. System executes a multi-source parallel query: Neo4j for topic/skill constraints, Supabase for TCAS constraints, pgvector for semantic content matching against course descriptions.
  4. System returns ranked program cards matching the constraints with explanation of which constraints each program satisfies.
  5. Student can refine query or apply faceted filters (faculty, program level, TCAS round).
- **Postcondition:** Student finds programs matching specific criteria without browsing the full catalogue.

#### UC-10: Pin Programs and Compare

- **Actor:** Guest / High School Student
- **Precondition:** At least 2 programs pinned via pin button on any program card (maximum 4)
- **Flow:**
  1. Student pins programs from the explorer or recommendation screen. Pinned programs appear in a persistent tray at the top of the explorer.
  2. Student taps "เปรียบเทียบ" from the pin tray.
  3. System generates a side-by-side comparison: overlaid PLO radar charts, career path overlap, curriculum character profiles across 5 dimensions, TCAS accessibility per round, and RIASEC fit scores.
  4. Student can tap "เช็ค Portfolio ทั้งหมด" to run portfolio gap analysis against all pinned programs simultaneously, showing which program the student is most ready for.
  5. Student can tap "แชทกับ KUru" to open chatbot with all pinned programs as active context.
- **Postcondition:** Student has a clear comparative picture of shortlisted programs and knows which they are most ready to apply for.

#### UC-11: View Curriculum Timeline

- **Actor:** Guest / High School Student
- **Precondition:** Student is on a program detail page
- **Flow:**
  1. Student selects the "ชีวิตนักศึกษา" tab on a program detail page.
  2. System retrieves course structure data extracted from มคอ.2 during ingestion: courses per year, credit hour distribution, teaching method breakdown, assessment method types, and sample learning activity descriptions.
  3. System displays a year selector (ปี 1–4). Default shows Year 1.
  4. For the selected year, system displays a Gemini-generated narrative, course composition breakdown, workload indicator, and one concrete example activity description extracted from มคอ.2.
  5. Student taps different years to compare progression.
- **Postcondition:** Student has a concrete sense of what studying this program year by year actually involves before applying.

#### UC-12: Portfolio Readiness Check

- **Actor:** Guest / High School Student
- **Precondition:** Student has a portfolio PDF. Target program has portfolio criteria data ingested (MVP: top 10 programs)
- **Flow:**
  1. Student navigates to Portfolio Coach from nav, program detail page, or pin tray.
  2. Student selects target program(s) and uploads portfolio PDF.
  3. System uses Gemini to extract a structured portfolio profile: activities by type and level, GPAX, certificates, personal statement presence.
  4. System retrieves the pre-extracted faculty criteria schema for selected program(s).
  5. System performs four-part gap analysis: (1) hard threshold eligibility; (2) required item coverage; (3) preferred item strength with level-aware scoring; (4) qualitative criteria assessment using multi-step Gemini reasoning.
  6. System displays structured report: eligibility status, portfolio strength profile, prioritised gap list, deadline-aware action recommendations.
  7. If multiple programs selected, system shows which program the student is most ready for right now.
- **Postcondition:** Student knows exactly what is missing from their portfolio and what to prioritise before the application deadline. System provides preparation guidance, not admission probability prediction.

### 3.4 User Interface Design

Mobile-first web design using Next.js, Tailwind CSS, and Shadcn/UI. Key screens:

- **Landing page:** Value proposition with two entry paths (interest discovery for undecided students; career search for students with a goal in mind). Bilingual Thai/English.
- **Interest discovery:** Twelve-step adaptive elicitation — Steps 1–6: one Likert screen per RIASEC dimension (4 statements, 5-point scale, color-coded per dimension R/I/A/S/E/C); Step 7: global confidence check (single tap, three options); Step 8: adaptive pairwise questions targeting only ambiguous dimension pairs (maximum 4–6, shown only where delta < 3); Steps 9–11: three scenario questions with A–F role options; Step 12: profile summary with inline dealbreaker filter chips and Holland Code display. Progress bar throughout showing step x of 12.
- **Program explorer:** Ranked program cards with fit score and matched career paths from Pipeline A. On first visit, includes a profile correction prompt ("Do these feel right?") that returns the student to targeted re-elicitation if they disagree with the ranking.
- **Program detail page:** Full-page view at `/programs/[program-id]` — not a modal — to support URL sharing, extended reading, and mobile scrolling. Contains: hero section, career section (matched O\*NET occupations), curriculum timeline tab (UC-11), PLO radar chart overlaid with student profile, TCAS section with personal eligibility check, and portfolio checker entry point (UC-12).
- **PLO Explorer:** Browsable program directory with natural language semantic search (UC-09). Persistent pin tray (up to 4 programs) with comparison and batch portfolio check entry points.
- **Program comparison view:** Side-by-side comparison triggered from the pin tray (UC-10).
- **Portfolio Coach:** Portfolio readiness checker (UC-12) accessible from nav, program detail page, or pin tray.
- **Career explorer:** List of O\*NET occupations matched to the student's RIASEC profile from Pipeline A. Each card shows Thai-localised title, required skills, and links to KU programs that develop them.
- **TCAS guide:** Faculty-specific breakdown of applicable rounds, score requirements, portfolio criteria, and deadlines.
- **Curriculum chatbot:** Conversational interface supporting Thai and English queries, with source citations from มคอ.2 documents. When programs are pinned, supports multi-program context queries.
- **Saved profile dashboard:** Bookmarked programs, TCAS deadline tracker, interest profile summary, before/after comparison of recommendation ranking shift. Requires login.

---

## Chapter 4 — Software Architecture Design

### 4.1 System Architecture Overview

KUru is a three-tier web application with a distinct AI layer:

```
Next.js frontend
    → FastAPI backend
        → RAG Engine (Supabase pgvector + Gemini)
        → Recommendation Engine (Neo4j + interest profile)
        → Data Ingestion Pipeline
            → External sources (มคอ.2 PDFs, O*NET, TCAS data)
    → Supabase Auth (user profiles)
    → Gemini API (LLM calls)
```

**Domain Model (Figure 4.2 — 11 entities):** `Student` holds one `RIASECProfile` (normalised 6D RIASEC vector) and generates `InteractionLog` entries. Each `Program` belongs to a `Faculty`, which defines its `PLO`s and publishes `PortfolioCriteria`. PLOs link to `SkillCluster` nodes (*develops*) and `Career` nodes link to the same clusters (*requires*) — this shared vocabulary enables the multi-hop recommendation path from student interests to program outcomes. `TCASRecord` and `Course` are extracted structured layers stored in Supabase alongside embeddings. The `RIASECProfile` feeds Pipeline A (matched against `Career` RIASEC profiles) and Pipeline B1 (converted to SkillCluster weights for Neo4j query). See DIAGRAMS.md Figure 6 for Mermaid classDiagram source.

### 4.2 Software Design

#### 4.2.1 RAG Pipeline Sequence

When a user submits a query to the curriculum chatbot:
1. Query is embedded using Gemini text-embedding-001.
2. Embedding performs cosine similarity search against the pgvector store of มคอ.2 document chunks.
3. Top-k retrieved chunks assembled into a prompt context along with the user query and conversation history.
4. Gemini 2.5 Flash generates a grounded response in the requested language.
5. Source citations are appended to the response.

#### 4.2.2 Recommendation Pipeline Sequence (5 Stages — Two Parallel Signals)

When a student completes the interest discovery flow:

1. **RIASEC vector construction.** The twelve-step adaptive elicitation (UC-01) produces a weighted 6-dimensional RIASEC vector. Steps 1–6 (Likert screens) produce raw scores per dimension (max 20 each). Step 7 applies a global confidence scalar (1.0, 0.75, or 0.5). Step 8 (adaptive pairwise) adjusts scores for dimension pairs with delta < 3. Steps 9–11 (scenario questions) adjust scores proportionally per response. Step 12 applies the optional dealbreaker filter, zeroing out explicitly rejected dimensions. The resulting vector is L2-normalised to a unit vector before use in Pipeline A and Pipeline B.

2. **Parallel signal computation.** Two independent pipelines run concurrently:

   **Pipeline A (Career-side):** The student RIASEC vector is compared against precomputed O\*NET occupation RIASEC interest profiles in Supabase pgvector using cosine similarity. O\*NET interest profiles are empirically derived from surveys of employed workers. Top 10–15 occupations form the internal career space; top 7 are surfaced to the student in the Career Explorer (UC-06). An A-score per KU program is computed based on career-program pathway alignment. O\*NET's 35-skill taxonomy is used for Career Explorer display only — it is not used as a bridge to Neo4j in the ranking pipeline.

   **Pipeline B (Curriculum-side):** Two sub-signals computed independently and combined:
   - **B1 — Neo4j PLO match:** Student's RIASEC vector converted to a SkillCluster weight vector and matched against KU program PLO SkillCluster profiles via Neo4j graph query. B1-score is the cosine similarity between the student weight vector and each program's PLO skill profile.
   - **B2 — Semantic course content match:** Student's interest query matched against course description embeddings in Supabase pgvector via semantic search over ingested มคอ.2 course content. B2-score is the weighted mean similarity of the top retrieved course chunks per program.

   Combined B-score = 0.4 × B1 + 0.6 × B2.

   The two pipelines are independent — an error in Pipeline A does not propagate into Pipeline B.

3. **Score synthesis.** Programs ranked by final score = 0.35 × A-score + 0.65 × B-score. Top-N programs selected for display.

4. **Explanation generation.** Top-N ranked programs, together with their Pipeline A details (matched O\*NET occupations) and Pipeline B details (curriculum themes and matched PLOs), are passed to Gemini 2.5 Flash as structured context. Gemini generates a plain-language explanation for each program referencing both career alignment and curriculum fit. Explanations generated in Thai or English depending on the student's language setting.

5. **Behavioural re-ranking (registered users only).** For registered users with accumulated interaction data, the pipeline scores from Stage 3 are blended with a behavioural fit score derived from the individual student's own interaction history (not from other users — true collaborative filtering across students is deferred to Phase 2). The blend ratio is controlled by α: new users start at α = 1.0 (pure pipeline score); α decays toward 0.2 as interaction weight accumulates according to the threshold schedule documented in UC-07 (3–5 meaningful signals → α ≈ 0.5; regular user → α ≈ 0.2). Final ranking score = α × pipeline score + (1 − α) × behavioural fit. Guest interaction signals are session-scoped and do not update α; guests always begin a new session at α = 1.0. Fallback hierarchy when behavioural data is sparse: (1) sufficient interaction history → normal blended signal; (2) limited interaction history → α held higher; (3) no interaction history → pure pipeline score (α = 1.0). Interaction weights are documented in UC-07.

### 4.3 AI and Data Design

#### 4.3.1 Data Sources

- **KU curriculum documents (มคอ.2):** Provided directly by KU faculty advisors for all KU programs. Thai-language PDFs, typically 20–80 pages per program. Primary knowledge base for both the RAG pipeline and the PLO extraction pipeline. Version-tagged by academic year and re-ingested when updated.

- **O\*NET occupational database:** Publicly available from the US Department of Labor. Two data layers:
  - *Interests* — RIASEC profile for each occupation, derived from surveys of employed workers; used for career matching from the student's RIASEC vector.
  - *Skills* — 35 standardized skills per occupation with importance and level scores; used to derive the target skill set that drives Neo4j program queries.
  Downloaded as structured data (CSV/JSON). Occupation titles mapped to Thai equivalents for student-facing display; skill and interest data used directly as the underlying structure is language-independent.

- **TCAS admission data:** Ingested from three sources in priority order. (1) KU faculty-provided project PDFs received via Google Drive — each PDF may contain admission records for multiple programs. PDFs are classified as tcas/mko2/portfolio/unknown and TCAS PDFs are parsed by Gemini into per-program TCASRecord objects covering project name, round, faculty, program, quota, GPAX minimum, exam score criteria, portfolio requirements, and deadlines. (2) mytcas.com — scraped as a gap-filling layer for programs not covered by faculty PDFs. (3) Faculty portfolio criteria PDFs — processed separately for the Portfolio Readiness Checker. All sources are resolved against a canonical program registry using fuzzy name matching with PyThaiNLP normalization (threshold 0.85). A Supabase materialized view (programs_unified) joins มคอ.2 structured data, TCAS records, and portfolio criteria into a unified program record keyed on program_id.

- **Interaction log:** Generated by the system as registered users engage with KUru. Stored in Supabase PostgreSQL. Records program saves, card expansions, TCAS guide views, chatbot queries, and card views, each with a timestamp, interaction weight, and associated program identifier. Used to compute the behavioural fit score in Stage 5 of the recommendation pipeline. A background recomputation job updates collaborative scores periodically as new interaction data accumulates.

- **Faculty portfolio criteria documents:** Published by KU faculties for TCAS Round 1 and Round 2 applications. Ingested via the same PDF extraction pipeline as มคอ.2 using Gemini in structured extraction mode to produce a per-faculty, per-round criteria schema. Stored in Supabase PostgreSQL alongside TCAS admission data. Updated at the start of each TCAS cycle. Used by the Portfolio Readiness Checker (Feature 8).

- **Course structure data (extracted layer):** Extracted from มคอ.2 during ingestion as a structured layer stored separately from the embedding chunks. Fields extracted per program per year: course list, credit hour distribution, teaching method breakdown (lecture/lab/project ratios), assessment method types, and sample learning activity descriptions. Stored in Supabase PostgreSQL. Used by the Curriculum Timeline Visualiser (Feature 9).

**มคอ.2 ingestion pipeline (6 stages):**

1. **PDF classification** — pages classified by text density and Thai character density into born-digital, scanned, pure-image, or mixed types.
2. **Tiered text extraction** — born-digital pages via PyMuPDF; scanned pages via Typhoon OCR (opentyphoon.ai, primary fallback, purpose-built Thai/English OCR); Gemini Vision as secondary fallback. Failed pages flagged for manual review. Each page tagged with extraction method and confidence level.
3. **Section-aware chunking** — PLO, course, admission, and curriculum structure sections chunked separately (target 500 tokens, 50-token overlap), tagged by section type.
4. **Structured extraction** — PLOs extracted as typed JSON objects for Neo4j; curriculum structure extracted as per-year JSON for the Timeline Visualiser.
5. **Embedding generation** — Gemini text-embedding-001 in batches; chunks from failed OCR pages excluded.
6. **Neo4j population and quality reporting** — Program → PLO → SkillCluster graph populated; ingestion report flags documents where OCR ratio > 50% or PLO extraction returns zero results.

#### 4.3.2 Model Design

**Primary LLM:** Gemini 2.5 Flash — selected for strong Thai language performance, native PDF document understanding, 1M token context window, and cost efficiency relative to GPT-4o. Direct Gemini API calls used without LangChain or similar orchestration frameworks, to reduce latency and maintain explicit control over prompt structure.

**Embeddings:** Gemini text-embedding-001 — multilingual model producing consistent semantic representations for both Thai and English text, enabling cross-language retrieval.

**Neo4j knowledge graph schema:**
- Node types: `Faculty`, `PLO`, `SkillCluster`, `Career`
- Edges: `Faculty -[HAS_PLO]→ PLO`, `PLO -[DEVELOPS]→ SkillCluster`, `Career -[REQUIRES]→ SkillCluster`
- Supports multi-hop queries: given a student's SkillCluster profile, find Faculties whose PLOs develop those clusters.

**Interest elicitation design:** The interest discovery interface uses a twelve-step adaptive elicitation flow. Steps 1–6 present one RIASEC dimension per screen with 4 Likert statements each (5-point scale, max score 20 per dimension, color-coded per dimension). Step 7 applies a global confidence scalar (1.0 / 0.75 / 0.5). Step 8 presents adaptive pairwise questions targeting only dimension pairs where the score delta falls below a 3-point threshold (maximum 4–6 pairs). Steps 9–11 present three scenario questions with A–F role options mapped to RIASEC dimensions. Step 12 displays the profile summary with an optional dealbreaker filter that zeros out explicitly rejected dimensions before L2-normalisation. Full question bank documented in Appendix A.

**Baseline for comparison:** BM25 keyword retrieval over the same มคอ.2 corpus without embedding or LLM generation. This establishes a performance floor against which RAG improvement is measured.

#### 4.3.3 Evaluation

- **RAG pipeline quality (RAGAS framework):**
  - Faithfulness (proportion of claims in the answer supported by retrieved context) — Target: > 0.80
  - Answer Relevancy (semantic similarity between answer and question) — Target: > 0.75
  - Context Recall (proportion of relevant information retrieved)

- **Recommendation quality:**
  - MRR and NDCG@5 on a manually curated test set of 30–50 student interest profiles with ground-truth faculty matches validated by faculty advisors or senior students.
  - Target: MRR > 0.60

- **User experience:**
  - Task completion rate and SUS score from user testing with 10–15 high school students or KU first-year students.
  - Target: SUS score > 70 (acceptable)

---

## Chapter 5 — Software Development

### 5.1 Development Methodology

Agile-inspired iterative approach for a two-person team over one semester. Two-week sprints aligned with project schedule phases. Shared Kanban board (Notion) for task tracking; GitHub for version control with feature-branch workflow. Weekly check-ins with advisor. Data collection (มคอ.2 from faculty) gates feature development in the first two weeks.

### 5.2 Technology Stack

| Component | Technology | Notes |
|-----------|-----------|-------|
| Frontend | Next.js 14 (App Router), Tailwind CSS, Shadcn/UI | TypeScript, built-in i18n routing for Thai/English |
| Backend | Python FastAPI | Python ecosystem access (PyMuPDF, neo4j driver), async performance |
| Vector database | Supabase (PostgreSQL + pgvector) | Stores มคอ.2 document embeddings, precomputed O\*NET occupation interest profiles, user profiles, TCAS structured data, and the interaction log (program saves, card views, TCAS guide views, chatbot queries with weights and timestamps). A background job periodically recomputes collaborative scores from the interaction log. Supabase Auth handles authentication |
| Graph database | Neo4j on Railway | PLO–Skill–Career knowledge graph; queried via Cypher from FastAPI backend |
| AI | Gemini 2.5 Flash (generation), Gemini text-embedding-001 (embeddings) | Google AI SDK for Python |
| Data processing | PyMuPDF, Typhoon OCR v1.5 (primary OCR fallback), Gemini Vision (secondary OCR fallback), custom Python chunking pipeline | PyMuPDF for born-digital PDFs; Typhoon OCR purpose-built Thai/English bilingual OCR outperforms GPT-4o on Thai government documents; Gemini Vision fallback when Typhoon API unavailable |
| Thai NLP | PyThaiNLP | Thai text normalization for TCAS program name entity resolution (fuzzy matching, threshold 0.85) |
| Deployment | Vercel (frontend), Railway (FastAPI backend + Neo4j) | |

### 5.3 Coding Standards

- **Python:** PEP 8, type hints on all function signatures, docstrings for all public functions.
- **TypeScript:** ESLint with Next.js recommended config, Prettier.
- **Git:** Conventional commits (feat/fix/chore/docs), feature branches merged via PR with at least one review.
- **Secrets:** All secrets in .env files, never committed.

### 5.4 Project Schedule (Proposal Version)

**PROPOSAL TIMELINE:** The proposal focuses on April 2026 (P1 Foundation + P2 Core AI) and January–March 2027 (P3 Features + P4 Polish & Evaluation). The April 2026 period delivers proof-of-concept implementations of the core AI features (RAG chatbot for curriculum Q&A and hybrid recommendation engine with RIASEC-based interest discovery). **By end of April 2026, the first working demo integrating both core AI systems will be complete.**

| Period | Phase | Deliverables |
| ------ | ----- | ------------ |
| Apr 1–5, 2026 | P1 · Foundation — Set up Repo | Repository setup, project structure, development environment |
| Apr 1–5, 2026 | P1 · Foundation — Data Collection | Receive มคอ.2 and TCAS data from KU faculty, download O\*NET dataset |
| Apr 6–12, 2026 | P1 · Foundation — Data Ingestion | PDF extraction, chunking, embedding into Supabase pgvector; Neo4j schema + pilot data |
| Apr 6–30, 2026 | P2 · Core AI — RAG Chatbot PoC | RAG pipeline (retrieval + Gemini generation), TCAS Q&A support |
| Apr 6–30, 2026 | P2 · Core AI — RIASEC Recommendation PoC | Recommendation engine (Pipeline A + B, interest elicitation) |
| Apr 6–30, 2026 | P2 · Core AI — Basic Integration & First Demo | **End-to-end integration of RAG + Recommendation, first working demo (PROOF OF CONCEPT)** |
| Jan 1–31, 2027 | P3 · Features — Program Explorer | PLO Explorer with semantic search and pin tray |
| Jan 1–31, 2027 | P3 · Features — Program Detail Pages | Full program detail pages, curriculum timeline visualiser, PLO spider chart |
| Jan 1–31, 2027 | P3 · Features — Portfolio Coach | Portfolio readiness checker (top 10 programs) |
| Jan 31, 2027 | P3 · Features — Complete Recommendation | Complete recommendation feature integration |
| Feb 1–28, 2027 | P4 · Polish & Eval — UI/UX Polish | UI/UX polish, Thai/English language switching, mobile-first refinement |
| Feb 1–28, 2027 | P4 · Polish & Eval — Cross-feature Integration | Chatbot + Explorer + Portfolio connection |
| Feb 1–28, 2027 | P4 · Polish & Eval — User Testing | RAGAS evaluation, MRR/NDCG test set, SUS user testing with 10–15 students |
| Mar 1–31, 2027 | P4 · Polish & Eval — Performance Testing | Performance benchmarking against all success metric targets |
| Mar 1–31, 2027 | P4 · Polish & Eval — Bug Fixing & Optimization | Bug fixes, optimization, stability improvements |
| Mar 1–31, 2027 | P4 · Polish & Eval — Final Documentation | Final report, demo preparation, project documentation |

---

## Chapters 5.1–5.3 (Hidden in Proposal)

**Sections 5.1–5.3 are not included in the proposal version:**
- 5.1 Development Methodology
- 5.2 Technology Stack
- 5.3 Coding Standards

These full technical details remain in the complete SRS document but are omitted from the condensed proposal for brevity.

---

## Chapter 6 — Deliverables (Hidden in Proposal)

### 6.1 Software Solution

The delivered software will include:
- Deployed web application accessible at a public URL
- Data ingestion pipeline for มคอ.2 PDF processing
- Neo4j knowledge graph populated with all KU programs
- RAG pipeline and recommendation engine
- All ten core MVP features described in Chapter 1. Portfolio readiness checker (Feature 8) scoped to top 10 programs. Recommendation engine (Feature 2) covers all KU programs for which มคอ.2 documents are available; MVP targets the top 50 most popular programs across Engineering, Science, and Business faculties.

### 6.2 Test Report

Three testing levels:
- **Unit tests:** Core AI functions (chunking, embedding, retrieval, graph query) tested with pytest. Coverage target: 70% of backend functions.
- **Integration tests:** End-to-end API tests for each major user flow (interest discovery to recommendation, chatbot query to grounded response). Run automatically on each PR via GitHub Actions.
- **User tests:** Manual usability testing sessions with 10–15 participants, structured task script and SUS questionnaire.

**Note:** Chapter 6 (Deliverables) is not included in the proposal version. See the full SRS for complete details on deliverables and test reports.

---

## Chapter 7 — Conclusion and Discussion (Hidden in Proposal)

### 7.1 Summary of Achievements

*(To be completed at project conclusion.)*

**Note:** Chapter 7 (Conclusion and Discussion) is not included in the proposal version. The full SRS document contains limitations, known issues, and future work roadmap. See key points below that remain relevant to the proposal scope.

1. **TCAS data currency:** TCAS requirements change each academic year. Requires manual data updates at the start of each TCAS cycle; no automatic change detection.

2. **CLO-level mapping:** System uses program-level PLO data (มคอ.2) only. Course-level CLO data (มคอ.3) is not ingested, as features requiring CLO mapping (e.g., skill progress tracking for enrolled students) are out of scope.

3. **O\*NET Thai career mapping:** O\*NET data is in English and uses US career taxonomy. Occupation titles are mapped to Thai equivalents for student-facing display in the Career Explorer. O\*NET skill data is used for Career Explorer display only — the recommendation ranking pipeline uses direct curriculum-side matching via Neo4j and pgvector rather than routing through O\*NET skill taxonomy, eliminating the vocabulary mismatch that affected the previous design. Residual approximation exists in the RIASEC-to-SkillCluster weight mapping used in Pipeline B1.

4. **Portfolio checker scope:** The portfolio readiness checker is implemented for the top 10 most popular KU programs in the MVP. Full coverage of all KU programs accepting Round 1 or Round 2 portfolio applications is deferred to Phase 2 pending criteria document availability from all remaining faculties. The checker evaluates structured portfolio content — activity records, certificates, transcripts, and personal statement presence. It does not evaluate creative work quality. It provides preparation guidance, not admission probability prediction.

5. **Evaluation ground truth:** The MRR evaluation test set is manually curated with limited size (30–50 profiles), which constrains the statistical reliability of recommendation quality metrics.

6. **Interest profile validity:** The interest discovery interface uses a twelve-step adaptive elicitation process as a lightweight proxy for established vocational interest instruments such as Holland's Self-Directed Search. While the twelve-step design is substantially more reliable than a tile-selection approach, it remains shorter than a full validated instrument (42+ items for the Self-Directed Search). Meta-analytic research on validated interest inventories reports approximately 50% accuracy in predicting eventual career choice even with full assessments; the accuracy of KUru's abbreviated elicitation is expected to be lower. The system is designed accordingly — recommendations are framed as a starting point for exploration rather than a definitive match, with the α blending mechanism progressively shifting recommendation weight toward behavioural signals as the student interacts with the system.

7. **Behavioural blending cold start:** The α blending mechanism provides no benefit until sufficient interaction data has accumulated. For early users, collaborative signal is sparse or absent and the system falls back toward pure RIASEC recommendations. Fallback hierarchy: (1) sufficient similar-profile users exist → collaborative signal applied normally; (2) few similar users → α is held higher regardless of individual interaction count; (3) no similar users → pure RIASEC (α = 1.0). Logged-in users always receive better personalisation than guests, as guest interaction signals are session-scoped and do not persist.

8. **มคอ.2 data availability:** Full coverage of all 430+ KU programs is contingent on receiving curriculum documents from all faculties. Programs without ingested มคอ.2 documents fall back to metadata-only matching in Pipeline B1 and return no results in the curriculum chatbot. MVP coverage targets the top 50 most popular programs across Engineering, Science, and Business faculties; remaining programs are added incrementally as documents are received.

9. **OCR quality on scanned มคอ.2 documents:** The ingestion pipeline includes Typhoon OCR as primary fallback for scanned pages. Heavily degraded scans or documents with non-standard Thai font encodings may still produce extraction errors. Extraction method is logged per chunk; chunks extracted via OCR are monitored for RAG faithfulness score degradation in the RAGAS evaluation. Documents where OCR ratio exceeds 50% are flagged for manual review before embedding.

### 7.3 Future Work

1. **KU enrolled student features (Phase 2):** Extend scope to serve currently enrolled KU students. Requires มคอ.3 CLO ingestion, a course enrollment interface, and a skill gap dashboard. The current knowledge graph schema is designed to support this extension without architectural changes.

2. **Portfolio checker full coverage (Phase 2):** The MVP portfolio readiness checker covers the top 10 most popular KU programs. Extension to all KU programs accepting Round 1 or Round 2 portfolio applications requires criteria documents from all remaining faculties and is deferred to Phase 2.

3. **Automated TCAS data refresh:** Monitor mytcas.com for changes each TCAS cycle and automatically notify the data administrator when updates are detected, triggering a review and re-ingestion cycle with KU faculty.

4. **Thai career taxonomy alignment:** Develop a systematic mapping between O\*NET occupations and THACO (Thai Standard Occupational Classification) to improve career recommendation accuracy for Thai students.

5. **True collaborative filtering (Phase 2):** The current MVP implements single-user behavioural blending — the α mechanism in UC-07 weights each student's *own* interaction history against their initial RIASEC scores. True collaborative filtering — using interaction patterns of students with similar RIASEC profiles to inform each other's recommendations — requires a critical mass of user data and is deferred to Phase 2. The α integration point in Stage 5 of the recommendation pipeline is designed to accommodate this extension without architectural changes. A prerequisite is robust handling of *profile pollution*: a poor initial RIASEC vector clusters a student incorrectly, degrading the collaborative signal for all students in that cluster. The twelve-step adaptive elicitation in UC-01 is designed to reduce this risk before true collaborative filtering is introduced.

6. **Longitudinal evaluation:** Track recommendation quality by following up with admitted students after one year to assess whether their actual program experience matched the system's prediction.

---

## Appendix A — RIASEC Elicitation Question Bank and Scoring Logic

The twelve-step adaptive elicitation produces the RIASEC vector used across the recommendation pipeline. The full question bank is organised into three tables.

### Table A.1 — Likert Question Bank (Steps 1–6, 4 questions per dimension, 5-point scale)

Each screen presents one RIASEC dimension with 4 Likert statements in Thai. Maximum raw score per dimension: 20.

| Dimension | Q1 (Thai) | Q2 (Thai) | Q3 (Thai) | Q4 (Thai) |
| --------- | --------- | --------- | --------- | --------- |
| Realistic (R) | ฉันชอบทำงานกับเครื่องมือหรืออุปกรณ์จริงๆ | ฉันสนุกกับการซ่อมแซมหรือสร้างสิ่งของ | ฉันชอบงานที่ใช้ร่างกายหรือทักษะช่าง | ฉันชอบทำงานกลางแจ้งหรือใกล้ชิดธรรมชาติ |
| Investigative (I) | ฉันชอบวิเคราะห์ข้อมูลและหาคำตอบ | ฉันสนุกกับการทำการทดลองหรือวิจัย | ฉันชอบคิดแก้ปัญหาที่ซับซ้อน | ฉันอยากเข้าใจว่าสิ่งต่างๆ ทำงานอย่างไร |
| Artistic (A) | ฉันชอบสร้างสรรค์งานศิลปะหรือดนตรี | ฉันสนุกกับการเขียนหรือเล่าเรื่อง | ฉันชอบออกแบบและคิดสิ่งใหม่ | ฉันชอบแสดงออกผ่านงานสร้างสรรค์ |
| Social (S) | ฉันชอบช่วยเหลือและสอนผู้อื่น | ฉันสนุกกับการทำงานเป็นทีม | ฉันชอบฟังและให้คำปรึกษา | ฉันอยากทำงานที่สร้างผลดีต่อสังคม |
| Enterprising (E) | ฉันชอบชักจูงและโน้มน้าวผู้อื่น | ฉันสนุกกับการเป็นผู้นำและวางแผน | ฉันชอบงานที่มีการแข่งขันและความท้าทาย | ฉันชอบคิดธุรกิจและโอกาสใหม่ๆ |
| Conventional (C) | ฉันชอบทำงานที่มีขั้นตอนชัดเจน | ฉันสนุกกับการจัดระเบียบและจัดเก็บข้อมูล | ฉันชอบทำตามกฎระเบียบและมาตรฐาน | ฉันชอบงานที่ผลลัพธ์วัดได้ชัดเจน |

### Table A.2 — Pairwise Comparison Bank (Step 8, shown only when score delta < 3)

| Pair | Option A (Thai) | Option B (Thai) |
| ---- | --------------- | --------------- |
| R vs I | ทดสอบเครื่องจักรในโรงงาน | วิเคราะห์ข้อมูลจากการทดลอง |
| I vs A | ค้นคว้าทฤษฎีใหม่ทางวิทยาศาสตร์ | สร้างสรรค์ผลงานศิลปะดิจิทัล |
| A vs S | ออกแบบโปสเตอร์รณรงค์ | จัดกิจกรรมอาสาในชุมชน |
| S vs E | ให้คำปรึกษาแก่เพื่อนที่มีปัญหา | นำเสนอแผนธุรกิจต่อนักลงทุน |
| E vs C | บริหารโครงการสตาร์ทอัพ | วางระบบบัญชีและควบคุมงบประมาณ |
| R vs C | ซ่อมบำรุงระบบไฟฟ้าในอาคาร | ตรวจสอบเอกสารและจัดเก็บข้อมูล |

### Table A.3 — Scenario Questions (Steps 9–11, one scenario per step, options A–F)

Each scenario presents a real-world situation with six role options mapped to RIASEC dimensions. Student response adjusts the corresponding dimension score proportionally.

| Step | Scenario Setting | Role A (R) | Role B (I) | Role C (A) | Role D (S) | Role E (E) | Role F (C) |
| ---- | ---------------- | ---------- | ---------- | ---------- | ---------- | ---------- | ---------- |
| 9 | งานแฟร์อาชีพในโรงเรียน | ดูแลบูธสาธิตอุปกรณ์ | วิเคราะห์แนวโน้มตลาดแรงงาน | ออกแบบสื่อและป้ายโฆษณา | ให้คำแนะนำนักเรียนที่สนใจ | นำเสนอโอกาสด้านธุรกิจ | จัดทำข้อมูลและลงทะเบียน |
| 10 | โครงการพัฒนาแอปพลิเคชันชุมชน | ติดตั้งและดูแลระบบเซิร์ฟเวอร์ | ออกแบบอัลกอริทึมและทดสอบ | สร้าง UI/UX ที่สวยงาม | สัมภาษณ์ผู้ใช้และรวบรวม feedback | ระดมทุนและหาพาร์ทเนอร์ | เขียนเอกสารและจัดการ backlog |
| 11 | ค่ายอาสาพัฒนาโรงเรียนชนบท | ก่อสร้างและซ่อมแซมอาคาร | สำรวจและวิเคราะห์ความต้องการ | จัดกิจกรรมศิลปะให้นักเรียน | สอนและดูแลเด็กนักเรียน | ประสานงานและจัดการทีม | บันทึกข้อมูลและรายงานผล |

---

## Key Design Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Scope | Pre-admission only | Keeps MVP focused; enrolled student features deferred to Phase 2 |
| Interest elicitation | 12-step adaptive: 6 Likert screens (Steps 1–6) → confidence scalar (Step 7) → adaptive pairwise (Step 8) → 3 scenario questions (Steps 9–11) → dealbreaker filter + L2-normalise (Step 12) | More reliable than tile-selection; 2–4 min; grounded in Holland RIASEC theory with full scored dimensions |
| Career data | O\*NET (US DOL) | Structured RIASEC profiles + 35 standardized skills per occupation; language-independent |
| TCAS data source | KU faculty-provided | Authoritative; avoids scraping instability |
| LLM | Gemini 2.5 Flash (direct API) | Strong Thai performance, 1M context window, cost-efficient; no LangChain overhead |
| Embeddings | Gemini text-embedding-001 | Multilingual; consistent Thai/English semantic space |
| Vector store | Supabase pgvector | Unified store for document embeddings + O\*NET profiles + user data |
| Graph DB | Neo4j | Explicit typed relationships enable explainable multi-hop recommendation |
| Recommendation explainability | Full chain: interests → RIASEC → O\*NET careers → skills → crosswalk → Neo4j → PLOs → KU programs | Auditable; student can verify every step |
| Evaluation | RAGAS + MRR/NDCG@5 + SUS | Covers RAG quality, recommendation quality, and user experience |
