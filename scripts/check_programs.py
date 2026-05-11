# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
from dotenv import load_dotenv; load_dotenv()
from kuru.db import supabase_client as db
client = db.get_client()
rows = client.table('programs').select('id,name_th,name_en').ilike('id', '%bangkhen%').execute()
for r in sorted(rows.data, key=lambda x: x['id']):
    print(f"{r['id']:42s}  th={r['name_th']}  en={r['name_en']}")
