from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import declarative_base


BaseBusiness = declarative_base()
BaseQuickQuery = declarative_base()


class Author(BaseBusiness):
    __tablename__ = "authors"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True, index=True)


class Category(BaseBusiness):
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False, unique=True, index=True)


class Source(BaseBusiness):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=False, unique=True, index=True)
    base_url = Column(String(1000), nullable=True)


class Book(BaseBusiness):
    __tablename__ = "books"

    id = Column(Integer, primary_key=True)
    title = Column(String(255), nullable=False, index=True)
    author_id = Column(Integer, ForeignKey("authors.id"), nullable=False, index=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=False, index=True)
    published_year = Column(Integer, nullable=True)
    summary = Column(Text, nullable=True)
    isbn = Column(String(40), nullable=True, index=True)

    __table_args__ = (UniqueConstraint("title", "author_id", "category_id", "isbn", name="uq_book_key"),)


class BookStat(BaseBusiness):
    """
    Per-source / per-collection metadata.

    For Open Library, we may store rating+summary.
    For HKPL Top 100, we store loans_count and call_number.
    """

    __tablename__ = "book_stats"

    id = Column(Integer, primary_key=True)
    book_id = Column(Integer, ForeignKey("books.id"), nullable=False, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False, index=True)

    # Stable external identifier from the source (e.g., HKPL BIB ID).
    external_id = Column(String(80), nullable=True, index=True)

    rating = Column(Float, nullable=True)
    loans_count = Column(Integer, nullable=True)
    call_number = Column(String(80), nullable=True)

    source_url = Column(String(1000), nullable=True)
    fetched_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class BookSearchIndex(BaseQuickQuery):
    __tablename__ = "book_search_index"

    id = Column(Integer, primary_key=True)
    business_book_id = Column(Integer, nullable=False, index=True)

    title = Column(String(255), nullable=False, index=True)
    author_name = Column(String(255), nullable=False, index=True)
    category_name = Column(String(100), nullable=False, index=True)

    published_year = Column(Integer, nullable=True, index=True)
    rating = Column(Float, nullable=True, index=True)
    loans_count = Column(Integer, nullable=True, index=True)
    call_number = Column(String(80), nullable=True)

    searchable_text = Column(Text, nullable=False)


class AuthorSearchIndex(BaseQuickQuery):
    __tablename__ = "author_search_index"

    id = Column(Integer, primary_key=True)
    business_author_id = Column(Integer, nullable=False, unique=True, index=True)
    author_name = Column(String(255), nullable=False, unique=True, index=True)
    searchable_text = Column(Text, nullable=False)


class CategorySearchIndex(BaseQuickQuery):
    __tablename__ = "category_search_index"

    id = Column(Integer, primary_key=True)
    business_category_id = Column(Integer, nullable=False, unique=True, index=True)
    category_name = Column(String(100), nullable=False, unique=True, index=True)


class SourceSearchIndex(BaseQuickQuery):
    __tablename__ = "source_search_index"

    id = Column(Integer, primary_key=True)
    business_source_id = Column(Integer, nullable=False, unique=True, index=True)
    source_name = Column(String(255), nullable=False, unique=True, index=True)
