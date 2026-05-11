# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()
from kuru.db import supabase_client as db

client = db.get_client()

# Find EE program IDs
ee_ids = ["bangkhen_57bbf1ac", "bangkhen_5a8d741f"]

for pid in ee_ids:
    rows = (
        client.table("chunks")
        .select("content,source_file,section_type")
        .eq("program_id", pid)
        .execute()
    )
    hits = [r for r in rows.data if "ต่างชาติ" in r["content"]]
    print(f"\n=== {pid} ({len(rows.data)} chunks total, {len(hits)} mention ต่างชาติ) ===")
    for h in hits[:3]:
        print(f"  [{h['section_type']}] {h['content'][:300]}")
        print()
