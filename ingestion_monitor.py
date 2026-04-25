"""Poll Supabase every 30s and print ingestion progress."""

import time
from datetime import datetime

from kuru.db.supabase_client import get_client

TOTAL = 50   # change to 260 for full run
POLL  = 30   # seconds between checks

db = get_client()

print(f"Monitoring ingestion — polling every {POLL}s. Ctrl+C to stop.\n")

prev_chunks = 0
prev_files  = 0

while True:
    count  = db.table("chunks").select("id", count="exact").execute()
    rows   = db.table("chunks").select("source_file").execute()
    chunks = count.count or 0
    files  = len(set(r["source_file"] for r in rows.data))

    new_chunks = chunks - prev_chunks
    new_files  = files  - prev_files
    ts = datetime.now().strftime("%H:%M:%S")

    status = "DONE" if files >= TOTAL else "running"
    print(
        f"[{ts}]  Files: {files}/{TOTAL}  |  Chunks: {chunks:,}"
        + (f"  (+{new_files} files, +{new_chunks:,} chunks)" if prev_chunks else "")
        + f"  [{status}]"
    )

    if files >= TOTAL:
        break

    prev_chunks = chunks
    prev_files  = files
    time.sleep(POLL)
