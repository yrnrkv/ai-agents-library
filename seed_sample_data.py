from sqlalchemy.orm import Session
from sqlalchemy import text

from .db_utils import get_or_create_author, get_or_create_book, get_or_create_category, get_or_create_source, upsert_book_stat


SAMPLE_BOOKS = [
    {
        "title": "Hands-On Machine Learning with Scikit-Learn, Keras, and TensorFlow",
        "author": "Aurelien Geron",
        "category": "AI",
        "published_year": 2019,
        "rating": 4.7,
        "summary": "Practical guide to machine learning and deep learning.",
        "isbn": "9781492032649",
    },
    {
        "title": "Deep Learning",
        "author": "Ian Goodfellow",
        "category": "AI",
        "published_year": 2016,
        "rating": 4.6,
        "summary": "Comprehensive deep learning textbook.",
        "isbn": "9780262035613",
    },
    {
        "title": "Python Crash Course",
        "author": "Eric Matthes",
        "category": "Programming",
        "published_year": 2023,
        "rating": 4.8,
        "summary": "Fast-paced intro to Python for beginners.",
        "isbn": "9781718502703",
    },
    {
        "title": "Clean Code",
        "author": "Robert C. Martin",
        "category": "Software Engineering",
        "published_year": 2008,
        "rating": 4.7,
        "summary": "How to write maintainable, readable code.",
        "isbn": "9780132350884",
    },
    {
        "title": "Artificial Intelligence: A Modern Approach",
        "author": "Stuart Russell",
        "category": "AI",
        "published_year": 2020,
        "rating": 4.5,
        "summary": "Classic AI theory and algorithms textbook.",
        "isbn": "9780134610993",
    },
    {
        "title": "Designing Data-Intensive Applications",
        "author": "Martin Kleppmann",
        "category": "Data Engineering",
        "published_year": 2017,
        "rating": 4.8,
        "summary": "Reliable and scalable data systems design patterns.",
        "isbn": "9781449373320",
    },
]


def seed_business_sample_data(session: Session) -> int:
    """
    Seeds a small offline dataset into Business DB.
    """
    source = get_or_create_source(session, name="SampleDataset", base_url=None)

    existing_count = session.execute(
        text(
            "SELECT COUNT(*) FROM book_stats WHERE source_id = (SELECT id FROM sources WHERE name = :n)"
        ),
        {"n": source.name},
    ).scalar()
    if existing_count and existing_count > 0:
        return 0

    created = 0
    for book in SAMPLE_BOOKS:
        author = get_or_create_author(session, book["author"])
        category = get_or_create_category(session, book["category"])
        b = get_or_create_book(
            session,
            title=book["title"],
            author=author,
            category=category,
            published_year=book.get("published_year"),
            summary=book.get("summary"),
            isbn=book.get("isbn"),
        )
        upsert_book_stat(
            session,
            book=b,
            source=source,
            external_id=book.get("isbn"),
            rating=book.get("rating"),
            loans_count=None,
            call_number=None,
            source_url=None,
        )
        created += 1

    session.commit()
    return created
