# -*- coding: utf-8 -*-
"""Copy 20 diverse PDFs from data/raw to data/native for batch ingestion test."""
import shutil
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

raw_base = Path("data/raw/curriculum/บางเขน")
native_base = Path("data/native/curriculum/บางเขน")

already_copied = {
    "วศ.บ._วิศวกรรมไฟฟ้า_2565.pdf",
    "ปร.ด._วิศวกรรมเคมี_2566.pdf",
}
SKIP_WORDS = ["ปิดหลักสูตร", "อนุมัติปิด"]
BACHELOR = ["วท.บ.", "วศ.บ.", "ศษ.บ.", "บธ.บ.", "ภ.สถ.บ.", "สถ.บ."]

picks = {
    "agri":   ["วท.บ._สัตวศาสตร์อุตสาหกรรม_2568.pdf",
               "วท.บ._อาหาร_โภชนาการ_และการกำหนดอาหาร_2566.pdf"],
    "agro":   ["วท.บ._นวัตกรรมและเทคโนโลยีอุตสาหกรรมเกษตร_(นานาชาติ)_2568.pdf",
               "วท.บ._เทคโนโลยีการบรรจุ_2565.pdf"],
    "arch":   ["วท.บ._สถาปัตยกรรม_2569.pdf",
               "วท.บ._นวัตกรรมการออกแบบผลิตภัณฑ์เชิงบูรณาการ_2567.pdf"],
    "bus":    ["บธ.บ._บริหารธุรกิจ_(นานาชาติ)_2568.pdf"],
    "edu":    ["ศษ.บ._การสอนวิทยาศาสตร์_(5_ปี)_2558.pdf",
               "ศษ.บ._พลศึกษา_(5_ปี)_2558.pdf"],
    "envi":   None,
    "fish":   None,
    "forest": None,
    "hum":    None,
    "sci":    None,
    "vet":    None,
}

copied = []

for faculty, filenames in picks.items():
    src_dir = raw_base / faculty
    dst_dir = native_base / faculty
    if not src_dir.exists():
        print(f"  [skip] {faculty} not found in raw")
        continue
    dst_dir.mkdir(parents=True, exist_ok=True)

    if filenames is None:
        candidates = sorted(src_dir.glob("*.pdf"), key=lambda f: -f.stat().st_size)
        filenames = []
        for f in candidates:
            if any(s in f.name for s in SKIP_WORDS):
                continue
            if f.name in already_copied:
                continue
            if any(p in f.name for p in BACHELOR):
                filenames.append(f.name)
            if len(filenames) >= 2:
                break
        if not filenames:
            for f in candidates[:2]:
                if f.name not in already_copied and not any(s in f.name for s in SKIP_WORDS):
                    filenames.append(f.name)

    for fname in filenames:
        if len(copied) >= 20:
            break
        src = src_dir / fname
        dst = dst_dir / fname
        if not src.exists():
            print(f"  MISSING: {faculty}/{fname}")
            continue
        if dst.exists():
            print(f"  exists:  {faculty}/{fname}")
            continue
        shutil.copy2(src, dst)
        size_mb = src.stat().st_size // (1024 * 1024)
        copied.append(f"{faculty}/{fname}")
        print(f"  {size_mb:>3}MB  {faculty}/{fname}")

    if len(copied) >= 20:
        break

print(f"\nTotal copied: {len(copied)} files — ready to ingest")
