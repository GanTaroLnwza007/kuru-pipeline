"""One-shot migration: clean name_th for all existing program rows.

Safe to run multiple times — already-clean names pass through unchanged.

Usage:
    uv run python -m kuru.scripts.migrate_program_names
"""

from __future__ import annotations

import re

from dotenv import load_dotenv

from kuru.db import supabase_client as db

load_dotenv()

# Short-form degree abbreviations and filler words
_PREFIX_RE = re.compile(
    r"^(?:วศ\.บ\.|วท\.บ\.|น\.บ\.|ศ\.บ\.|บธ\.บ\.|รป\.บ\.|วท\.ม\.|วศ\.ม\.|ปร\.ด\.|ศศ\.บ\.|อ\.บ\.|ทล\.บ\.|กษ\.บ\.|สพ\.บ\.|พย\.บ\.|สต\.บ\.)\s*"
    r"|^(?:สาขาวิชา|หลักสูตร)\s*",
    re.UNICODE,
)

# Trailing track/edition noise
_SUFFIX_RE = re.compile(
    r"\s*\([^)]*(?:ปกติ|พิเศษ|นานาชาติ|ภาษาอังกฤษ|IDDP|IUP|Regular|Special|Intl)[^)]*\)\s*$"
    r"|\s*(?:ฉบับปร[ับ]+ปรุง|ฉบับ\s*\d+|พ\.ศ\.)\s*\d{4}.*$"
    r"|\s+(?:final|revised|version|v\d).*$",
    re.IGNORECASE | re.UNICODE,
)

# Document meta-name prefixes that indicate the string is a filename, not a program name
_GARBAGE_PREFIX_RE = re.compile(
    r"^(?:\d+[\.\s]|เล่ม|แผ่นพับ|แบบ(?:ใน|เสนอ)|curriculum)",
    re.IGNORECASE | re.UNICODE,
)


def _is_garbage(name: str) -> bool:
    """True if the string has too few Thai chars or is a known generic word."""
    thai = len(re.findall(r"[ก-๙]", name))
    generic = {"นานาชาติ", "international", "ภาษาอังกฤษ", "ภาษาไทย"}
    return thai < 3 or name.strip().lower() in generic


def _clean(name_th: str, name_en: str) -> str:
    s = name_th.strip()

    # 1. If "สาขาวิชา" appears anywhere, extract what's after it — the actual program name
    if "สาขาวิชา" in s:
        s = s.split("สาขาวิชา", 1)[1].strip()

    # 2. Strip garbage document meta-name prefixes (brochures, numbered forms, etc.)
    elif _GARBAGE_PREFIX_RE.match(s):
        return name_en

    # 3. Strip stacked degree/filler prefixes until stable
    while True:
        stripped = _PREFIX_RE.sub("", s).strip()
        if stripped == s:
            break
        s = stripped

    # 4. Strip trailing track info and edition/year noise
    s = _SUFFIX_RE.sub("", s).strip()

    # 5. Fall back to name_en if what's left is garbage or empty
    if not s or _is_garbage(s):
        return name_en

    return s


def main() -> None:
    client = db.get_client()
    rows = client.table("programs").select("id,name_th,name_en").execute().data or []

    updated = 0
    for row in rows:
        raw = row.get("name_th") or ""
        name_en = row.get("name_en") or ""
        cleaned = _clean(raw, name_en)
        if cleaned != raw:
            client.table("programs").update({"name_th": cleaned}).eq("id", row["id"]).execute()
            print(f"  {row['id']}: {repr(raw)[:60]} → {repr(cleaned)}")
            updated += 1

    print(f"\nDone — {updated}/{len(rows)} rows updated.")


if __name__ == "__main__":
    main()
