"""Scrape curriculum (มคอ.2) PDFs from registrar.ku.ac.th — Bangkhen campus."""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://registrar.ku.ac.th"
OUTPUT_DIR = Path("data/raw/curriculum/บางเขน")

# Bangkhen campus faculty slugs discovered from /cur/all
BANGKHEN_SLUGS = [
    "/agri", "/bus", "/fish", "/hum", "/forest", "/sci", "/eng",
    "/edu", "/econ", "/arch", "/soc", "/vet", "/agro", "/vettech",
    "/envi", "/med", "/sis", "/inter", "/cur/all/nur", "/combo",
    "/cur/all/interdisciplinary", "/cur/all/pharma",
]

_YEAR_RE = re.compile(r"^(25\d\d)$")        # Buddhist calendar years 2500-2599
_INVALID_CHARS = re.compile(r'[\\/:*?"<>|]')


def _safe_filename(program_name: str, year: int) -> str:
    name = _INVALID_CHARS.sub("_", program_name.strip())
    name = re.sub(r"\s+", "_", name)
    return f"{name}_{year}"


def _faculty_key(slug: str) -> str:
    return slug.rstrip("/").split("/")[-1]


def _fetch(client: httpx.Client, url: str) -> BeautifulSoup | None:
    try:
        r = client.get(url, timeout=30, follow_redirects=True)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"  [ERROR] fetch {url}: {e}", file=sys.stderr)
        return None


def _parse_faculty_page(soup: BeautifulSoup, base_url: str) -> list[tuple[str, int, str]]:
    """Return (program_name, latest_year, pdf_url) for each program on the page."""
    results: list[tuple[str, int, str]] = []

    for row in soup.find_all("tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        program_name = cells[0].get_text(strip=True)
        if not program_name:
            continue

        # Walk remaining cells; track the most recently seen year and collect
        # (year, url) pairs — multiple PDFs per year are deduplicated (first wins).
        current_year: int | None = None
        year_to_url: dict[int, str] = {}

        for cell in cells[1:]:
            text = cell.get_text(strip=True)
            m = _YEAR_RE.match(text)
            if m:
                current_year = int(m.group(1))
                continue

            link = cell.find("a", href=True)
            if link and current_year is not None:
                href = str(link["href"])
                if href.lower().endswith(".pdf"):
                    abs_url = urljoin(base_url, href)
                    year_to_url.setdefault(current_year, abs_url)

        if not year_to_url:
            continue

        best_year = max(year_to_url)
        results.append((program_name, best_year, year_to_url[best_year]))

    return results


def main() -> None:
    # Ensure UTF-8 output on Windows terminals that default to CP1252
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    dry_run = "--dry-run" in sys.argv
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    downloaded = skipped = 0
    failures: list[tuple[str, str]] = []  # (description, reason)

    headers = {"User-Agent": "KUruPipeline/1.0 curriculum-scraper (educational use)"}
    with httpx.Client(headers=headers) as client:
        for slug in BANGKHEN_SLUGS:
            key = _faculty_key(slug)
            url = BASE_URL + slug
            print(f"\n[{key}] {url}")

            soup = _fetch(client, url)
            if soup is None:
                failures.append((f"[{key}] faculty page", url))
                continue

            programs = _parse_faculty_page(soup, BASE_URL)
            if not programs:
                print("  no programs found")
                continue

            print(f"  found {len(programs)} program(s)")

            out_dir = OUTPUT_DIR / key
            out_dir.mkdir(parents=True, exist_ok=True)

            for program_name, year, pdf_url in programs:
                dest = out_dir / f"{_safe_filename(program_name, year)}.pdf"

                if dest.exists():
                    print(f"  [skip]  {dest.name}")
                    skipped += 1
                    continue

                if dry_run:
                    print(f"  [dry]   {dest.name}")
                    print(f"          {pdf_url}")
                    downloaded += 1
                    continue

                print(f"  [dl]    {dest.name}")
                try:
                    r = client.get(pdf_url, timeout=60, follow_redirects=True)
                    r.raise_for_status()
                    dest.write_bytes(r.content)
                    downloaded += 1
                    time.sleep(0.5)
                except httpx.HTTPStatusError as e:
                    if e.response.status_code == 404:
                        print(f"  [dead]  {pdf_url}")
                        skipped += 1
                    else:
                        print(f"  [ERROR] download {pdf_url}: {e}", file=sys.stderr)
                        if dest.exists():
                            dest.unlink()
                        failures.append((f"[{key}] {program_name} ({year})", pdf_url))
                except Exception as e:
                    print(f"  [ERROR] download {pdf_url}: {e}", file=sys.stderr)
                    if dest.exists():
                        dest.unlink()
                    failures.append((f"[{key}] {program_name} ({year})", pdf_url))

            time.sleep(1.0)

    verb = "would download" if dry_run else "downloaded"
    print(f"\nDone — {verb}: {downloaded}, skipped: {skipped} (dead links counted in skipped), failed: {len(failures)}")
    if failures:
        print("\nFailed:")
        for desc, url in failures:
            print(f"  {desc}")
            print(f"    {url}")
