"""get_or_create / upsert helpers."""
from src.db_utils import (
    get_or_create_author,
    get_or_create_book,
    get_or_create_category,
    get_or_create_source,
    upsert_book_stat,
)
from src.models import BookStat


def test_get_or_create_author_is_idempotent(business_session):
    a1 = get_or_create_author(business_session, "Grace Hopper")
    a2 = get_or_create_author(business_session, "Grace Hopper")
    assert a1.id == a2.id


def test_get_or_create_book_is_idempotent(business_session):
    author = get_or_create_author(business_session, "Grace Hopper")
    category = get_or_create_category(business_session, "History")
    b1 = get_or_create_book(business_session, title="COBOL", author=author,
                            category=category, published_year=1959, isbn="x")
    b2 = get_or_create_book(business_session, title="COBOL", author=author,
                            category=category, published_year=1959, isbn="x")
    assert b1.id == b2.id


def test_upsert_book_stat_updates_in_place(business_session):
    author = get_or_create_author(business_session, "Grace Hopper")
    category = get_or_create_category(business_session, "History")
    source = get_or_create_source(business_session, "Src")
    book = get_or_create_book(business_session, title="COBOL", author=author,
                              category=category, published_year=1959, isbn="x")

    upsert_book_stat(business_session, book=book, source=source,
                     external_id="e1", rating=3.0, loans_count=5)
    upsert_book_stat(business_session, book=book, source=source,
                     external_id="e1", rating=4.5, loans_count=9)
    business_session.commit()

    stats = business_session.query(BookStat).filter(BookStat.book_id == book.id).all()
    assert len(stats) == 1          # same key updated, not duplicated
    assert stats[0].rating == 4.5
    assert stats[0].loans_count == 9
