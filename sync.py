from __future__ import annotations

from sqlalchemy import delete
from sqlalchemy.orm import Session
from typing import Optional

from .models import (
    Author,
    Book,
    BookSearchIndex,
    BookStat,
    Category,
    CategorySearchIndex,
    Source,
    SourceSearchIndex,
    AuthorSearchIndex,
)


def _build_searchable_text(
    *,
    title: str,
    author_name: str,
    category_name: str,
    summary: Optional[str],
    call_number: Optional[str],
    isbn: Optional[str],
) -> str:
    parts = [
        title or "",
        author_name or "",
        category_name or "",
        summary or "",
        call_number or "",
        isbn or "",
    ]
    return " ".join(p.strip().lower() for p in parts if p)


def sync_business_to_quick_query(business_session: Session, quick_session: Session) -> int:
    """
    Transform Business DB data into a read-optimized Quick Query DB.
    Only keep the fields needed for fast AI/agent queries.
    """
    # Clear quick tables (demo-oriented; safe because quick DB is derived).
    for table_cls in (BookSearchIndex, AuthorSearchIndex, CategorySearchIndex, SourceSearchIndex):
        quick_session.execute(delete(table_cls))

    # Populate small lookup indexes.
    authors = business_session.query(Author).all()
    categories = business_session.query(Category).all()
    sources = business_session.query(Source).all()

    quick_session.add_all(
        [AuthorSearchIndex(business_author_id=a.id, author_name=a.name, searchable_text=a.name.lower()) for a in authors]
    )
    quick_session.add_all(
        [
            CategorySearchIndex(business_category_id=c.id, category_name=c.name)
            for c in categories
        ]
    )
    quick_session.add_all(
        [SourceSearchIndex(business_source_id=s.id, source_name=s.name) for s in sources]
    )

    # Build the main search index.
    quick_rows = []
    books = business_session.query(Book).all()

    for b in books:
        author = business_session.query(Author).filter(Author.id == b.author_id).one()
        category = business_session.query(Category).filter(Category.id == b.category_id).one()
        stats = business_session.query(BookStat).filter(BookStat.book_id == b.id).all()

        best_rating = None
        best_loans = None
        best_call = None

        if stats:
            rating_values = [s.rating for s in stats if s.rating is not None]
            if rating_values:
                best_rating = max(rating_values)

            loans_values = [s.loans_count for s in stats if s.loans_count is not None]
            if loans_values:
                best_loans = max(loans_values)
                # Prefer call number from the stat with highest loans.
                top_stat = next((s for s in stats if s.loans_count == best_loans), None)
                if top_stat is not None:
                    best_call = top_stat.call_number

        quick_rows.append(
            BookSearchIndex(
                business_book_id=b.id,
                title=b.title,
                author_name=author.name,
                category_name=category.name,
                published_year=b.published_year,
                rating=best_rating,
                loans_count=best_loans,
                call_number=best_call,
                searchable_text=_build_searchable_text(
                    title=b.title,
                    author_name=author.name,
                    category_name=category.name,
                    summary=b.summary,
                    call_number=best_call,
                    isbn=b.isbn,
                ),
            )
        )

    quick_session.add_all(quick_rows)
    quick_session.commit()
    return len(quick_rows)
