"""Detect when the user wants book/catalog results vs general Q&A."""

from __future__ import annotations

import re


def user_wants_book_catalog_results(query: str) -> bool:
    """
    True only when the user is asking for books to browse, recommend, or find.

    General questions like "what is machine learning?" should be False so we
    do not inject DB candidates into the LLM or attach book cards to the reply.
    """
    q = (query or "").strip().lower()
    if not q:
        return False

    # Pure definitional / explanation without asking for titles.
    if re.match(
        r"^(what is|what are|who is|who was|who are|define|definition of|explain|how does|how do|why does|why do|when did|where is)\b",
        q,
    ):
        # Unless they also explicitly ask for books in the same message.
        if not any(
            t in q
            for t in (
                "book",
                "books",
                "novel",
                "read",
                "recommend",
                "suggest",
                "title",
                "author",
                "library",
            )
        ):
            return False

    triggers = (
        "suggest",
        "recommend",
        "recommendation",
        "find book",
        "find books",
        "give me book",
        "give me books",
        "books about",
        "book about",
        "books on",
        "book on",
        "good books",
        "best books",
        "top books",
        "what books",
        "which books",
        "show me book",
        "show me books",
        "list book",
        "list books",
        "titles about",
        "read about",
        "borrow",
        "most borrowed",
        "top rated",
        "best rated",
        "in the library",
        "from the library",
        "library has",
        "catalog",
    )
    if any(t in q for t in triggers):
        return True

    # "books" / "book" plus topic-seeking phrasing (not "what is X book")
    if ("book" in q or "books" in q) and any(
        x in q for x in (" about ", " for ", " on ", " related to ", " with topic", "similar to")
    ):
        return True

    # Topic + "books" / "book" at end (e.g. "python books", "machine learning books")
    if re.search(r"\bbooks?\s*$", q.strip()) and len(q.split()) >= 2:
        return True

    return False
