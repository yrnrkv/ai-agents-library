import re
from typing import List, Optional

from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

from .models import BookSearchIndex


class LibraryAgent:
    def __init__(self, quick_query_session: Session):
        self.quick_query_session = quick_query_session

    def answer(self, user_query: str) -> str:
        q = user_query.strip().lower()

        if not q:
            return "Please ask a library question."

        limit = self._extract_limit(q, default=5)

        if "top rated" in q or "best rated" in q:
            books = (
                self.quick_query_session.query(BookSearchIndex)
                .filter(BookSearchIndex.rating.isnot(None))
                .order_by(desc(BookSearchIndex.rating))
                .limit(limit)
                .all()
            )
            return self._format_books("Top rated books", books)

        if "most borrowed" in q or "top borrowed" in q or "most loans" in q:
            books = (
                self.quick_query_session.query(BookSearchIndex)
                .filter(BookSearchIndex.loans_count.isnot(None))
                .order_by(desc(BookSearchIndex.loans_count))
                .limit(limit)
                .all()
            )
            return self._format_books("Most borrowed books", books)

        if "by " in q:
            author_hint = q.split("by ", 1)[1].strip()
            books = (
                self.quick_query_session.query(BookSearchIndex)
                .filter(BookSearchIndex.author_name.ilike(f"%{author_hint}%"))
                .limit(limit)
                .all()
            )
            return self._format_books(f"Books by '{author_hint}'", books)

        keywords = [w for w in re.split(r"\W+", q) if len(w) > 2]
        if not keywords:
            return "I could not detect useful keywords. Try adding topic words like 'python' or 'ai'."

        conditions = [BookSearchIndex.searchable_text.ilike(f"%{kw}%") for kw in keywords]
        books = (
            self.quick_query_session.query(BookSearchIndex)
            .filter(or_(*conditions))
            .order_by(desc(BookSearchIndex.rating))
            .limit(limit)
            .all()
        )
        return self._format_books("Matching books", books)

    @staticmethod
    def _extract_limit(query: str, default: int = 5) -> int:
        m = re.search(r"\b(\d{1,2})\b", query)
        if not m:
            return default
        value = int(m.group(1))
        return max(1, min(value, 20))

    @staticmethod
    def _format_books(title: str, books: List[BookSearchIndex]) -> str:
        if not books:
            return f"{title}: no results found."

        lines = [f"{title}:"]
        for idx, b in enumerate(books, start=1):
            rating = f" | rating {b.rating}" if b.rating is not None else ""
            loans = f" | loans {b.loans_count}" if b.loans_count is not None else ""
            year = f" ({b.published_year})" if b.published_year else ""
            lines.append(
                f"{idx}. {b.title}{year} - {b.author_name} [{b.category_name}]{rating}{loans}"
            )
        return "\n".join(lines)

    def search_structured(self, user_query: str, limit: int = 5) -> List[dict]:
        """
        For LangChain integration: return structured candidates for the LLM to summarize.
        """
        q = user_query.strip().lower()
        if not q:
            return []

        # Reuse the same routing logic as answer(), but return dicts.
        if "top rated" in q or "best rated" in q:
            books = (
                self.quick_query_session.query(BookSearchIndex)
                .filter(BookSearchIndex.rating.isnot(None))
                .order_by(desc(BookSearchIndex.rating))
                .limit(limit)
                .all()
            )
        elif "most borrowed" in q or "top borrowed" in q or "most loans" in q:
            books = (
                self.quick_query_session.query(BookSearchIndex)
                .filter(BookSearchIndex.loans_count.isnot(None))
                .order_by(desc(BookSearchIndex.loans_count))
                .limit(limit)
                .all()
            )
        elif "by " in q:
            author_hint = q.split("by ", 1)[1].strip()
            books = (
                self.quick_query_session.query(BookSearchIndex)
                .filter(BookSearchIndex.author_name.ilike(f"%{author_hint}%"))
                .limit(limit)
                .all()
            )
        else:
            keywords = [w for w in re.split(r"\W+", q) if len(w) > 2]
            if not keywords:
                return []
            conditions = [BookSearchIndex.searchable_text.ilike(f"%{kw}%") for kw in keywords]
            books = (
                self.quick_query_session.query(BookSearchIndex)
                .filter(or_(*conditions))
                .order_by(desc(BookSearchIndex.rating))
                .limit(limit)
                .all()
            )

        results: List[dict] = []
        for b in books:
            results.append(
                {
                    "title": b.title,
                    "author": b.author_name,
                    "category": b.category_name,
                    "published_year": b.published_year,
                    "rating": b.rating,
                    "loans_count": b.loans_count,
                    "call_number": b.call_number,
                }
            )
        return results
