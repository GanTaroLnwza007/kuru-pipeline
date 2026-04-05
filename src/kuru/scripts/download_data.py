"""Download raw data from Google Drive using gdown."""

from __future__ import annotations

import os
import time
from pathlib import Path

import gdown

TCAS1_FOLDER_ID      = "1-iOHS3P-iST3Fvbci3xjchcvY2rw8jpi"
CURRICULUM_FOLDER_ID = "1zmvMNmCYyzxLHjJWfHfqH0Yzoa6ZDYWC"

# Google Drive file IDs that failed during folder download — add them here to retry.
# Format: {"output_directory": "file_id"}  — gdown will infer the original filename from Drive.
# These files need their Google Drive permission set to "Anyone with the link can view" first.
MANUAL_RETRY: dict[str, str] = {
    # 67BThai-19SKedit2-IUP สาขาวิชาวิศวกรรมซอฟต์แวร์และความรู้ (นานาชาติ).pdf
    "data/raw/curriculum/บางเขน/วิศวฯ":  "1zy2vAAhxHd9qdFYZMYbxxCxAg2uIohlh",
    # 2.มคอ 2 หลักสูตรปรับปรุง พ.ศ.2565คอมฯ.pdf  (กพส campus)
    "data/raw/curriculum/กพส/วิศว กพส":  "1Niev92NFiNylLFaa6XL3Mvu-aZJCmpcE",
    # 69_TCAS1_ STEAMs-Sci(1.1)_ประกาศรับสมัคร-ลงนาม.pdf
    "data/raw/tcas1":                     "1cRaZi1XcPlq2BXuN9UGdgJfHqymJGV8h",
}


def _download_folder(folder_id: str, output: str, label: str) -> bool:
    """Download a Drive folder, returning True on full success."""
    os.makedirs(output, exist_ok=True)
    print(f"\nDownloading {label} …")
    try:
        gdown.download_folder(
            id=folder_id,
            output=output,
            quiet=False,
            use_cookies=False,
        )
        return True
    except Exception as exc:
        print(f"\n  WARNING: folder download interrupted — {exc}")
        already = list(Path(output).rglob("*.pdf"))
        print(f"  {len(already)} PDF(s) already saved to {output}/")
        print(
            "  To retry a specific failed file, add its file ID to MANUAL_RETRY "
            "in download_data.py and re-run."
        )
        return False


def _retry_manual(entries: dict[str, str]) -> None:
    """Download individual files by ID for any that failed during folder sync.

    Keys are output directories — gdown infers the original filename from Drive metadata.
    """
    if not entries:
        return
    print(f"\nRetrying {len(entries)} manually listed file(s) …")
    for output_dir, file_id in entries.items():
        os.makedirs(output_dir, exist_ok=True)
        print(f"  {file_id} → {output_dir}/")
        try:
            time.sleep(3)  # brief pause to avoid rate limit
            gdown.download(id=file_id, output=output_dir + "/", quiet=False, fuzzy=True)
        except Exception as exc:
            print(f"  FAILED: {exc}")


def main() -> None:
    _download_folder(TCAS1_FOLDER_ID,      "data/raw/tcas1",      "TCAS Round 1 PDFs")
    _download_folder(CURRICULUM_FOLDER_ID, "data/raw/curriculum", "Curriculum (มคอ.2) PDFs")
    _retry_manual(MANUAL_RETRY)

    tcas_count = len(list(Path("data/raw/tcas1").rglob("*.pdf")))
    curr_count  = len(list(Path("data/raw/curriculum").rglob("*.pdf")))
    print(f"\nDone.  TCAS: {tcas_count} file(s)   Curriculum: {curr_count} file(s)")


if __name__ == "__main__":
    main()
