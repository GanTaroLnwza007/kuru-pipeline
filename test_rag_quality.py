"""Batch RAG quality test — runs queries across all 20 sampled faculties."""

import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

from kuru.rag.query_engine import query

TESTS = [
    # (label, question)
    # Engineering
    ("eng  ", "What courses will I take in Computer Engineering?"),
    ("eng  ", "What is Software and Knowledge Engineering about?"),
    ("eng  ", "หลักสูตรวิศวกรรมโยธา-ชลประทาน มี PLO อะไรบ้าง"),
    # Agriculture / Agronomy
    ("agri ", "หลักสูตรเกษตรศาสตร์มีรายวิชาอะไรบ้าง"),
    ("agro ", "What is the Agronomy program about?"),
    # Veterinary / VetTech
    ("vet  ", "เล่มหลักสูตรพยาบาลสัตว์มี PLO อะไรบ้าง"),
    ("vet  ", "What are the objectives of the Veterinary Science program?"),
    # Science / Environment / Fishery
    ("envi ", "What does the Environmental Science program cover?"),
    ("fish ", "What courses are in the Fishery Science program?"),
    ("sci  ", "หลักสูตรวิทยาศาสตร์มีรายวิชาอะไรบ้าง"),
    # Business / Social / Humanities
    ("bus  ", "What is the Business Administration program about?"),
    ("soc  ", "What are the learning outcomes of the Economics program?"),
    ("hum  ", "หลักสูตรมนุษยศาสตร์มีรายวิชาอะไรบ้าง"),
    # Education / Nursing / Pharmacy
    ("edu  ", "What is the Education program's structure?"),
    ("nur  ", "What does the Nursing program teach?"),
    ("pharma", "What does the Pharmacy program teach?"),
    # Architecture / Forestry
    ("arch ", "What are the courses in the Architecture program?"),
    ("forest", "อธิบายหลักสูตรวนศาสตร์ให้หน่อย"),
    # Cross-cutting
    ("tcas ", "What are the TCAS3 score requirements for Computer Engineering?"),
    ("list ", "What programs are available at KU?"),
]

SEP = "─" * 80

def sim_label(s):
    if s >= 0.50: return f"✓ {s:.3f}"
    if s >= 0.35: return f"~ {s:.3f}"
    return f"✗ {s:.3f}"

print(f"\n{'KUru RAG Quality Test':^80}")
print(SEP)

from kuru.ingestion.embedder import _get_model
print("Loading embedding model…")
_get_model()
print("Ready.\n")

for i, (label, question) in enumerate(TESTS, 1):
    print(f"\n[{i:02d}/{len(TESTS)}] [{label}] {question}")
    try:
        result = query(question, debug=True)
        d = result.debug_info

        # Top chunk info
        chunks_used = d.get("chunks_used", [])
        if chunks_used:
            top = chunks_used[0]
            print(f"     Top chunk : {sim_label(top['similarity'])}  [{top['section_type']}]  {top['source_file'][:60]}")
        else:
            print("     Top chunk : (none above threshold)")

        # Stats line
        above = d.get("above_threshold", 0)
        fetched = d.get("fetched", 0)
        tcas_found = d.get("tcas_records_found")
        flags = []
        if d.get("is_tcas_query"): flags.append("TCAS")
        if d.get("is_plo_query"):  flags.append("PLO")
        if d.get("is_listing_query"): flags.append("LIST")
        flag_str = " ".join(flags) if flags else "—"
        tcas_str = f"  tcas_records={tcas_found}" if tcas_found is not None else ""
        print(f"     Chunks    : {above}/{fetched} above threshold{tcas_str}  flags=[{flag_str}]")

        # Answer (first 300 chars)
        ans = result.answer.replace("\n", " ")
        print(f"     Answer    : {ans[:300]}{'…' if len(ans) > 300 else ''}")
    except Exception as exc:
        print(f"     ERROR: {exc}")

print(f"\n{SEP}")
print("Done.")
