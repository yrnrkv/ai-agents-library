import argparse

import requests
from sqlalchemy.orm import Session

from .agent import LibraryAgent
from .db import get_business_engine, get_quick_query_engine, init_databases
from .db_utils import get_or_create_author, get_or_create_book, get_or_create_category, get_or_create_source, upsert_book_stat
from .scraper import scrape_books
from .seed_sample_data import seed_business_sample_data
from .sync import sync_business_to_quick_query
from .hkpl import scrape_hkpl_top100_most_borrowed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AI Library Agent demo")
    parser.add_argument("--init", action="store_true", help="Create DBs and tables")
    parser.add_argument("--reset-db", action="store_true", help="Delete existing DB files before init")
    parser.add_argument("--seed-sample", action="store_true", help="Seed sample books into Business DB")
    parser.add_argument("--scrape", action="store_true", help="Scrape books from Open Library into Business DB")
    parser.add_argument("--topic", type=str, default="artificial intelligence", help="Scrape topic")
    parser.add_argument("--limit", type=int, default=30, help="Scrape/result limit")
    parser.add_argument("--scrape-hkpl", action="store_true", help="Scrape HKPL Top 100 Most Borrowed Books into Business DB")
    parser.add_argument("--hkpl-year", type=int, default=2025, help="HKPL year for Top 100 pages")
    parser.add_argument("--hkpl-limit", type=int, default=30, help="Max HKPL items to ingest")
    parser.add_argument("--sync", action="store_true", help="Sync Business DB to Quick Query DB")
    parser.add_argument("--demo", action="store_true", help="Run a small demo query set")
    parser.add_argument("--chat", action="store_true", help="Run interactive chat mode")
    parser.add_argument("--langchain-chat", action="store_true", help="Run LangChain-powered chat using OpenAI (requires OPENAI_API_KEY)")
    parser.add_argument("--ollama-chat", action="store_true", help="Run LangChain-powered chat using local Ollama (free)")
    parser.add_argument(
        "--ollama-models",
        type=str,
        default="qwen2.5:7b-instruct,llama3.1:8b-instruct",
        help="Comma-separated Ollama models to try and pick the best",
    )
    return parser.parse_args()


def run_demo(agent: LibraryAgent) -> None:
    prompts = [
        "find books about python",
        "show books by aurelien",
        "what are top rated ai books",
    ]
    for q in prompts:
        print(f"\n> {q}")
        print(agent.answer(q))


def run_chat(agent: LibraryAgent) -> None:
    print("AI Library Agent chat mode. Type 'exit' to quit.")
    while True:
        user_query = input("\nYou: ").strip()
        if user_query.lower() in {"exit", "quit"}:
            print("Goodbye.")
            break
        print(agent.answer(user_query))


def main() -> None:
    args = parse_args()

    if args.init:
        init_databases(reset=bool(args.reset_db))
        print("Initialized Business DB and Quick Query DB.")

    business_engine = get_business_engine()
    quick_engine = get_quick_query_engine()

    with Session(business_engine) as business_session, Session(quick_engine) as quick_session:
        if args.seed_sample:
            inserted = seed_business_sample_data(business_session)
            if inserted:
                print(f"Inserted {inserted} sample books into Business DB.")
            else:
                print("Business DB already has data. Skipped sample seed.")

        if args.scrape:
            try:
                books = scrape_books(args.topic, args.limit)
                source = get_or_create_source(business_session, name="OpenLibrary", base_url="https://openlibrary.org/")
                inserted = 0
                for book in books:
                    author = get_or_create_author(business_session, book["author"])
                    category = get_or_create_category(business_session, book["category"])
                    b = get_or_create_book(
                        business_session,
                        title=book["title"],
                        author=author,
                        category=category,
                        published_year=book.get("published_year"),
                        summary=book.get("summary"),
                        isbn=book.get("isbn"),
                    )
                    upsert_book_stat(
                        business_session,
                        book=b,
                        source=source,
                        external_id=book.get("isbn"),
                        rating=None,
                        loans_count=None,
                        call_number=None,
                        source_url=None,
                    )
                    inserted += 1
                business_session.commit()
                print(f"Scraped and inserted {inserted} books for topic '{args.topic}'.")
            except requests.RequestException as exc:
                print(f"Scrape skipped due to network error: {exc}")

        if args.scrape_hkpl:
            try:
                source = get_or_create_source(business_session, name="HKPL Top 100 Most Borrowed", base_url="https://www.hkpl.gov.hk/")
                items = scrape_hkpl_top100_most_borrowed(
                    year=args.hkpl_year,
                    limit=args.hkpl_limit,
                )

                inserted = 0
                for item in items:
                    author = get_or_create_author(business_session, item["author"])
                    category = get_or_create_category(business_session, item["category"])
                    b = get_or_create_book(
                        business_session,
                        title=item["title"],
                        author=author,
                        category=category,
                        published_year=None,
                        summary=None,
                        isbn=None,
                    )
                    upsert_book_stat(
                        business_session,
                        book=b,
                        source=source,
                        external_id=str(item["bib_id"]),
                        rating=None,
                        loans_count=item.get("loans_count"),
                        call_number=item.get("call_number"),
                        source_url=item.get("source_url"),
                    )
                    inserted += 1

                business_session.commit()
                print(f"HKPL scrape inserted/updated {inserted} items into Business DB.")
            except requests.RequestException as exc:
                print(f"HKPL scrape skipped due to network error: {exc}")

        if args.sync:
            count = sync_business_to_quick_query(business_session, quick_session)
            print(f"Synced {count} books into Quick Query DB.")

        if args.demo or args.chat:
            agent = LibraryAgent(quick_session)
            if args.demo:
                run_demo(agent)
            if args.chat:
                run_chat(agent)

        if args.langchain_chat:
            from .langchain_agent import LangChainLibraryAgent

            agent = LangChainLibraryAgent(quick_session)
            run_chat(agent)

        if args.ollama_chat:
            from .langchain_agent import LangChainLibraryAgent

            models = [m.strip() for m in args.ollama_models.split(",") if m.strip()]
            agent = LangChainLibraryAgent(quick_session, provider="ollama", ollama_models=models)
            run_chat(agent)


if __name__ == "__main__":
    main()
