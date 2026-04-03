from __future__ import annotations

from typing import Dict, List, Optional

import requests
from bs4 import BeautifulSoup


# Only English pages for now (simpler parsing).
HKPL_COLLECTION_PAGES = [
    ("Adult Lending Fiction", "en-adult-lending-fiction.html"),
    ("Adult Lending Non-Fiction", "en-adult-lending-non-fiction.html"),
    ("Junior Lending Fiction", "en-junior-lending-fiction.html"),
    ("Junior Lending Non-Fiction", "en-junior-lending-non-fiction.html"),
]


def _parse_int(value: str) -> Optional[int]:
    value = value.strip()
    if not value:
        return None
    # Example cells sometimes contain footnote markers; keep digits only.
    digits = "".join(ch for ch in value if ch.isdigit())
    if not digits:
        return None
    return int(digits)


def scrape_hkpl_top100_most_borrowed(*, year: int = 2025, limit: int = 30) -> List[Dict]:
    """
    Fetch HKPL "Top 100 Most Borrowed Books" pages and return a normalized list.

    This is meant to seed the Business DB. The sync step transforms into Quick Query DB.
    """
    if limit <= 0:
        return []

    base = f"https://www.hkpl.gov.hk/en/collections/top-100-most-borrowed/{year}"
    collected: List[Dict] = []

    for category_name, page in HKPL_COLLECTION_PAGES:
        if len(collected) >= limit:
            break

        url = f"{base}/{page}"
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")

        # Find the first table that looks like the "Top 100" list.
        table = soup.find("table")
        if table is None:
            continue

        # Each row is: Item | BIB ID | Title | Author | Call Number | Number of Loans | Notes
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 6:
                continue

            # Sometimes the title link has extra whitespace; use text.
            bib_id = cells[1].get_text(strip=True)
            title = cells[2].get_text(strip=True)
            author = cells[3].get_text(strip=True)
            call_number = cells[4].get_text(strip=True)
            loans_count = _parse_int(cells[5].get_text())

            if not bib_id or not title or not author:
                continue

            item = {
                "bib_id": bib_id,
                "title": title,
                "author": author,
                "category": category_name,
                "published_year": None,
                "rating": None,
                "summary": None,
                "isbn": None,
                "loans_count": loans_count,
                "call_number": call_number or None,
                "source_url": url,
            }
            collected.append(item)

            if len(collected) >= limit:
                break

    return collected

