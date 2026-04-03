from typing import List, Dict, Optional

import requests

from .config import SCRAPER_MAX_BOOKS


OPEN_LIBRARY_SEARCH = "https://openlibrary.org/search.json"


def scrape_books(topic: str, limit: Optional[int] = None) -> List[Dict]:
    max_books = min(limit or SCRAPER_MAX_BOOKS, SCRAPER_MAX_BOOKS)
    response = requests.get(
        OPEN_LIBRARY_SEARCH,
        params={"q": topic, "limit": max_books},
        timeout=20,
    )
    response.raise_for_status()

    payload = response.json()
    docs = payload.get("docs", [])

    books: List[Dict] = []
    for doc in docs:
        title = doc.get("title")
        author_list = doc.get("author_name") or []
        year = doc.get("first_publish_year")
        isbn_list = doc.get("isbn") or []

        if not title or not author_list:
            continue

        books.append(
            {
                "title": title,
                "author": author_list[0],
                "category": topic.title(),
                "published_year": year if isinstance(year, int) else None,
                "rating": None,
                "summary": f"Scraped from Open Library for topic: {topic}.",
                "isbn": isbn_list[0] if isbn_list else None,
            }
        )

    return books
