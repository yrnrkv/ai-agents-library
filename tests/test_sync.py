"""Business DB -> Quick Query DB transform (best-stat selection + searchable text)."""
from sqlalchemy.orm import Session

from src.db import get_quick_query_engine
from src.db_utils import (
    get_or_create_author,
    get_or_create_book,
    get_or_create_category,
    get_or_create_source,
    upsert_book_stat,
)
from src.models import BookSearchIndex
from src.sync import sync_business_to_quick_query


def _make_book_with_two_stats(biz: Session):
    author = get_or_create_author(biz, "Ada Lovelace")
    category = get_or_create_category(biz, "Computing")
    book = get_or_create_book(
        biz, title="Notes", author=author, category=category,
        published_year=1843, summary="On the Analytical Engine.", isbn="123",
    )
    src_a = get_or_create_source(biz, "SourceA")
    src_b = get_or_create_source(biz, "SourceB")
    upsert_book_stat(biz, book=book, source=src_a, external_id="a",
                     rating=4.1, loans_count=10, call_number="CALL-A")
    upsert_book_stat(biz, book=book, source=src_b, external_id="b",
                     rating=4.9, loans_count=42, call_number="CALL-B")
    biz.commit()
    return book


def test_sync_picks_best_stats(business_session):
    _make_book_with_two_stats(business_session)
    with Session(get_quick_query_engine()) as qq:
        count = sync_business_to_quick_query(business_session, qq)
        assert count == 1
        row = qq.query(BookSearchIndex).one()
        assert row.rating == 4.9            # max rating
        assert row.loans_count == 42        # max loans
        assert row.call_number == "CALL-B"  # call number from top-loans stat


def test_searchable_text_is_lowercased_and_joined(business_session):
    _make_book_with_two_stats(business_session)
    with Session(get_quick_query_engine()) as qq:
        sync_business_to_quick_query(business_session, qq)
        row = qq.query(BookSearchIndex).one()
        assert "notes" in row.searchable_text
        assert "ada lovelace" in row.searchable_text
        assert "analytical engine" in row.searchable_text
        assert row.searchable_text == row.searchable_text.lower()


def test_sync_is_idempotent(business_session):
    _make_book_with_two_stats(business_session)
    with Session(get_quick_query_engine()) as qq:
        sync_business_to_quick_query(business_session, qq)
        sync_business_to_quick_query(business_session, qq)  # re-run clears + rebuilds
        assert qq.query(BookSearchIndex).count() == 1
