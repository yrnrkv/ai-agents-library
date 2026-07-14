"""Rule-based agent routing and intent gating (matches main's behavior)."""
from src.agent import LibraryAgent


def test_book_query_does_not_crash(seeded_quick_session):
    """Regression: answer() referenced an undefined `limit`, crashing every
    book query with NameError. It must return real results now."""
    agent = LibraryAgent(seeded_quick_session)
    reply = agent.answer("find books about python")
    assert "Python Crash Course" in reply


def test_empty_query(seeded_quick_session):
    agent = LibraryAgent(seeded_quick_session)
    assert agent.answer("") == "Please ask a question."
    assert agent.search_structured("") == []


def test_non_catalog_intent_is_gated(seeded_quick_session):
    """General questions should not trigger a catalog search."""
    agent = LibraryAgent(seeded_quick_session)
    assert "Rule-based mode only searches the catalog" in agent.answer("what is machine learning?")
    assert agent.search_structured("what is machine learning?") == []


def test_top_rated_orders_by_rating(seeded_quick_session):
    agent = LibraryAgent(seeded_quick_session)
    results = agent.search_structured("top rated books", limit=5)
    ratings = [r["rating"] for r in results]
    assert ratings == sorted(ratings, reverse=True)
    assert results[0]["rating"] == 4.8


def test_by_author(seeded_quick_session):
    agent = LibraryAgent(seeded_quick_session)
    # "find books" satisfies the catalog intent; "by <name>" routes to author search.
    results = agent.search_structured("find books by Martin Kleppmann")
    assert len(results) == 1
    assert results[0]["author"] == "Martin Kleppmann"


def test_keyword_search(seeded_quick_session):
    agent = LibraryAgent(seeded_quick_session)
    results = agent.search_structured("find books about python")
    assert len(results) == 1
    assert results[0]["title"] == "Python Crash Course"


def test_most_borrowed_empty_when_no_loans(seeded_quick_session):
    agent = LibraryAgent(seeded_quick_session)
    assert "no results found" in agent.answer("most borrowed books")
    assert agent.search_structured("most borrowed books") == []


def test_limit_extraction_and_clamp():
    assert LibraryAgent._extract_limit("recommend 3 books") == 3
    assert LibraryAgent._extract_limit("no number here", default=5) == 5
    assert LibraryAgent._extract_limit("give me 99 books") == 20   # clamped
    assert LibraryAgent._extract_limit("show 0 books") == 1        # floored
