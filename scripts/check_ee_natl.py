# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()
from kuru.db import supabase_client as db

client = db.get_client()
ee_ids = ["bangkhen_57bbf1ac", "bangkhen_5a8d741f"]

keywords = ["ต่างชาติ", "ต่างประเทศ", "นิสิตไทย", "คุณสมบัติ", "รับนิสิต", "รับเฉพาะ"]

for pid in ee_ids:
    rows = client.table("chunks").select("content,section_type,source_file").eq("program_id", pid).execute()
    print(f"\n=== {pid} ({len(rows.data)} chunks) ===")
    for kw in keywords:
        hits = [r for r in rows.data if kw in r["content"]]
        if hits:
            print(f"  '{kw}' found in {len(hits)} chunk(s):")
            for h in hits[:2]:
                idx = h["content"].find(kw)
                print(f"    [{h['section_type']}] ...{h['content'][max(0,idx-60):idx+100]}...")
