"""Download raw data from Google Drive using gdown."""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import gdown

TCAS1_FOLDER_ID      = "1-iOHS3P-iST3Fvbci3xjchcvY2rw8jpi"
CURRICULUM_FOLDER_ID = "1zmvMNmCYyzxLHjJWfHfqH0Yzoa6ZDYWC"

# Additional campus curriculum folder IDs — fill in once you have the Drive URLs.
# Format: { output_subdirectory: folder_id }
EXTRA_CAMPUS_FOLDERS: dict[str, str] = {
    # "data/native/curriculum/กำแพงแสน": "<KAMPHAENGSAEN_FOLDER_ID>",
    # "data/native/curriculum/ศรีราชา":   "<SRIRACHA_FOLDER_ID>",
}

_DRIVE_FOLDER_RE = re.compile(
    r"https://drive\.google\.com/drive/folders/([a-zA-Z0-9_-]+)"
)
_DRIVE_FILE_RE = re.compile(
    r"https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)"
)
_PDF_REDIRECT_MAX_CHARS = 200

# Google Drive file IDs that failed during folder download — add them here to retry.
# Format: {"output_directory": "file_id"}  — gdown will infer the original filename from Drive.
# These files need their Google Drive permission set to "Anyone with the link can view" first.
MANUAL_RETRY: dict[str, str] = {
    # 67BThai-19SKedit2-IUP สาขาวิชาวิศวกรรมซอฟต์แวร์และความรู้ (นานาชาติ).pdf
    "data/native/curriculum/บางเขน/วิศวฯ":  "1zy2vAAhxHd9qdFYZMYbxxCxAg2uIohlh",
    # 2.มคอ 2 หลักสูตรปรับปรุง พ.ศ.2565คอมฯ.pdf  (กพส campus)
    "data/native/curriculum/กพส/วิศว กพส":  "1Niev92NFiNylLFaa6XL3Mvu-aZJCmpcE",
    # 69_TCAS1_ STEAMs-Sci(1.1)_ประกาศรับสมัคร-ลงนาม.pdf
    "data/native/tcas":                      "1cRaZi1XcPlq2BXuN9UGdgJfHqymJGV8h",
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


def _follow_txt_redirects(base_dir: str) -> None:
    """Scan for .txt files containing a Google Drive folder URL and download those folders.

    Each .txt file acts as a pointer — its contents should be a single Drive folder URL.
    The linked folder is downloaded into a subdirectory named after the .txt file (no extension).
    """
    base_path = Path(base_dir)
    txt_files = list(base_path.rglob("*.txt"))
    found = [(p, m.group(1)) for p in txt_files
             if (m := _DRIVE_FOLDER_RE.search(p.read_text(encoding="utf-8", errors="ignore")))]
    if not found:
        return

    print(f"\nFollowing {len(found)} .txt redirect(s) …")
    for txt_path, folder_id in found:
        output_dir = str(txt_path.parent / txt_path.stem)
        print(f"  {txt_path.relative_to(base_path)} → folder {folder_id}")
        try:
            gdown.download_folder(
                id=folder_id,
                output=output_dir,
                quiet=False,
                use_cookies=False,
            )
        except Exception as exc:
            print(f"  WARNING: failed — {exc}")


def _is_pdf_redirect(pdf_path: Path) -> str | None:
    """Return the Drive URL if this PDF is a redirect notice, else None.

    A redirect PDF has < 200 chars of text and contains a drive.google.com URL.
    """
    try:
        import fitz  # noqa: PLC0415

        doc = fitz.open(str(pdf_path))
        text = "".join(page.get_text() for page in doc)
        doc.close()
        if len(text.strip()) > _PDF_REDIRECT_MAX_CHARS:
            return None
        m = _DRIVE_FOLDER_RE.search(text) or _DRIVE_FILE_RE.search(text)
        return m.group(0) if m else None
    except Exception:
        return None


def _follow_pdf_redirects(base_dir: str) -> None:
    """Scan all PDFs under base_dir for redirect notices and follow their Drive URLs.

    Handles two cases:
    - drive.google.com/file/d/<id>  → download single file into same directory
    - drive.google.com/drive/folders/<id> → download entire folder into same directory
    """
    base_path = Path(base_dir)
    pdfs = list(base_path.rglob("*.pdf"))
    if not pdfs:
        return

    redirects = [
        (p, url)
        for p in pdfs
        if (url := _is_pdf_redirect(p)) is not None
    ]
    if not redirects:
        return

    print(f"\nFound {len(redirects)} PDF redirect(s) — following Drive URLs …")
    for pdf_path, drive_url in redirects:
        output_dir = str(pdf_path.parent)
        print(f"  {pdf_path.name} → {drive_url}")
        folder_m = _DRIVE_FOLDER_RE.search(drive_url)
        file_m = _DRIVE_FILE_RE.search(drive_url)
        try:
            if folder_m:
                gdown.download_folder(
                    id=folder_m.group(1),
                    output=output_dir,
                    quiet=False,
                    use_cookies=False,
                )
            elif file_m:
                gdown.download(
                    id=file_m.group(1),
                    output=output_dir + "/",
                    quiet=False,
                    fuzzy=True,
                )
        except Exception as exc:
            print(f"  WARNING: redirect follow failed — {exc}")


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
    _download_folder(TCAS1_FOLDER_ID,      "data/native/tcas",      "TCAS PDFs + data")
    _download_folder(CURRICULUM_FOLDER_ID, "data/native/curriculum", "Curriculum (มคอ.2) — บางเขน + กพส")
    for output_dir, folder_id in EXTRA_CAMPUS_FOLDERS.items():
        campus = Path(output_dir).name
        _download_folder(folder_id, output_dir, f"Curriculum — {campus}")
    _retry_manual(MANUAL_RETRY)
    _follow_txt_redirects("data/native/curriculum")
    _follow_pdf_redirects("data/native/curriculum")

    tcas_count  = len(list(Path("data/native/tcas").rglob("*.pdf")))
    xlsx_count  = len(list(Path("data/native/tcas").rglob("*.xlsx")))
    curr_pdf    = len(list(Path("data/native/curriculum").rglob("*.pdf")))
    curr_docx   = len(list(Path("data/native/curriculum").rglob("*.docx")))
    print(
        f"\nDone.  TCAS: {tcas_count} PDF(s), {xlsx_count} xlsx   "
        f"Curriculum: {curr_pdf} PDF(s), {curr_docx} docx"
    )


if __name__ == "__main__":
    main()
