"""Shared fixtures. Every test runs against throwaway temp databases so the
real files in `data/` (shipped as a deployment seed snapshot) are never touched."""
from __future__ import annotations

import pytest
from sqlalchemy.orm import Session


@pytest.fixture
def db_paths(tmp_path, monkeypatch):
    """Point the DB engines and config at a temp data dir for one test.

    Also sets ROOT_DIR so ``_bootstrap_data_dir_from_repo_snapshot`` sees
    bundled_dir == DATA_DIR and skips copying the repo's shipped DBs in.
    """
    data_dir = tmp_path / "data"
    biz = data_dir / "business.db"
    qq = data_dir / "quick_query.db"

    import src.config as config
    import src.db as db

    for mod in (db, config):
        monkeypatch.setattr(mod, "BUSINESS_DB_PATH", biz, raising=False)
        monkeypatch.setattr(mod, "QUICK_QUERY_DB_PATH", qq, raising=False)
        monkeypatch.setattr(mod, "DATA_DIR", data_dir, raising=False)
    monkeypatch.setattr(db, "ROOT_DIR", tmp_path, raising=False)

    db.dispose_engines()  # drop any cached engine pointing at the real paths
    yield biz, qq
    db.dispose_engines()  # and don't leak a temp-pointing engine to later code


@pytest.fixture
def business_session(db_paths):
    """Empty, initialized Business DB session."""
    from src.db import get_business_engine, init_databases

    init_databases(reset=True)
    with Session(get_business_engine()) as sess:
        yield sess


@pytest.fixture
def seeded_quick_session(db_paths):
    """Quick Query DB session seeded with the sample dataset (6 books)."""
    from src.db import get_business_engine, get_quick_query_engine, init_databases
    from src.seed_sample_data import seed_business_sample_data
    from src.sync import sync_business_to_quick_query

    init_databases(reset=True)
    with Session(get_business_engine()) as biz, Session(get_quick_query_engine()) as qq:
        seed_business_sample_data(biz)
        sync_business_to_quick_query(biz, qq)

    sess = Session(get_quick_query_engine())
    yield sess
    sess.close()


@pytest.fixture
def client(db_paths, monkeypatch):
    """FastAPI test client with temp DBs, sample seeding on, Ollama probes skipped,
    and no cloud LLM keys — so every mode degrades to visible rule-based fallback."""
    monkeypatch.setenv("ALLOW_SAMPLE_SEED", "1")
    monkeypatch.setenv("SKIP_OLLAMA_PROBE", "1")
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GROQ_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)

    import src.web.app as webapp
    from fastapi.testclient import TestClient

    with TestClient(webapp.app) as c:  # context manager runs startup (seeds temp DBs)
        yield c
