from __future__ import annotations

from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

from .models import Author, Book, BookStat, Category, Source


def get_or_create_author(session: Session, name: str) -> Author:
    existing = session.query(Author).filter(Author.name == name).one_or_none()
    if existing is not None:
        return existing
    author = Author(name=name)
    session.add(author)
    session.flush()  # Get PK without committing.
    return author


def get_or_create_category(session: Session, name: str) -> Category:
    existing = session.query(Category).filter(Category.name == name).one_or_none()
    if existing is not None:
        return existing
    category = Category(name=name)
    session.add(category)
    session.flush()
    return category


def get_or_create_source(session: Session, name: str, base_url: Optional[str] = None) -> Source:
    existing = session.query(Source).filter(Source.name == name).one_or_none()
    if existing is not None:
        # Keep any existing base_url; don't overwrite it.
        return existing
    source = Source(name=name, base_url=base_url)
    session.add(source)
    session.flush()
    return source


def get_or_create_book(
    session: Session,
    *,
    title: str,
    author: Author,
    category: Category,
    published_year: Optional[int],
    summary: Optional[str] = None,
    isbn: Optional[str] = None,
) -> Book:
    existing = (
        session.query(Book)
        .filter(
            Book.title == title,
            Book.author_id == author.id,
            Book.category_id == category.id,
            Book.isbn == isbn,
        )
        .one_or_none()
    )
    if existing is not None:
        return existing

    book = Book(
        title=title,
        author_id=author.id,
        category_id=category.id,
        published_year=published_year,
        summary=summary,
        isbn=isbn,
    )
    session.add(book)
    session.flush()
    return book


def upsert_book_stat(
    session: Session,
    *,
    book: Book,
    source: Source,
    external_id: Optional[str],
    rating: Optional[float] = None,
    loans_count: Optional[int] = None,
    call_number: Optional[str] = None,
    source_url: Optional[str] = None,
    fetched_at: Optional[datetime] = None,
) -> BookStat:
    fetched_at = fetched_at or datetime.utcnow()

    existing = (
        session.query(BookStat)
        .filter(
            BookStat.book_id == book.id,
            BookStat.source_id == source.id,
            BookStat.external_id == external_id,
        )
        .one_or_none()
    )
    if existing is not None:
        existing.rating = rating
        existing.loans_count = loans_count
        existing.call_number = call_number
        existing.source_url = source_url
        existing.fetched_at = fetched_at
        return existing

    stat = BookStat(
        book_id=book.id,
        source_id=source.id,
        external_id=external_id,
        rating=rating,
        loans_count=loans_count,
        call_number=call_number,
        source_url=source_url,
        fetched_at=fetched_at,
    )
    session.add(stat)
    session.flush()
    return stat

