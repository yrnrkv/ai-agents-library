from __future__ import annotations

import shutil
from pathlib import Path

from sqlalchemy import create_engine, text

from .config import BUSINESS_DB_PATH, QUICK_QUERY_DB_PATH, DATA_DIR, ROOT_DIR
from .models import BaseBusiness, BaseQuickQuery

# Shared engines (FastAPI runs blocking chat/catalog in thread pool workers).
_business_engine = None
_quick_engine = None


def _copy_if_missing(src: Path, dst: Path) -> bool:
    """Copy a DB file only when destination does not already exist."""
    if dst.exists() or not src.exists():
        return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True


def _bootstrap_data_dir_from_repo_snapshot() -> int:
    """
    First Render boot can start with an empty persistent disk.
    If repo-shipped DB snapshots exist, copy them once into DATA_DIR.
    """
    bundled_dir = ROOT_DIR / "data"
    if bundled_dir.resolve() == DATA_DIR.resolve():
        return 0

    copied = 0
    copied += int(_copy_if_missing(bundled_dir / "business.db", Path(BUSINESS_DB_PATH)))
    copied += int(_copy_if_missing(bundled_dir / "quick_query.db", Path(QUICK_QUERY_DB_PATH)))
    return copied


def dispose_engines() -> None:
    """Close pooled connections (call before unlinking DB files on reset)."""
    global _business_engine, _quick_engine
    for eng in (_business_engine, _quick_engine):
        if eng is not None:
            eng.dispose()
    _business_engine = None
    _quick_engine = None


def get_business_engine():
    global _business_engine
    if _business_engine is None:
        _business_engine = create_engine(
            f"sqlite:///{BUSINESS_DB_PATH}",
            future=True,
            connect_args={"check_same_thread": False},
        )
    return _business_engine


def get_quick_query_engine():
    global _quick_engine
    if _quick_engine is None:
        _quick_engine = create_engine(
            f"sqlite:///{QUICK_QUERY_DB_PATH}",
            future=True,
            connect_args={"check_same_thread": False},
        )
    return _quick_engine


def migrate_quick_query_schema(quick_engine) -> None:
    """SQLite: add columns introduced after first deploy."""
    with quick_engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(book_search_index)")).fetchall()
        cols = {r[1] for r in rows}
        if "sources_json" not in cols:
            conn.execute(text("ALTER TABLE book_search_index ADD COLUMN sources_json TEXT"))
        if "primary_source_url" not in cols:
            conn.execute(text("ALTER TABLE book_search_index ADD COLUMN primary_source_url VARCHAR(1000)"))
        if "cover_image_url" not in cols:
            conn.execute(text("ALTER TABLE book_search_index ADD COLUMN cover_image_url VARCHAR(1000)"))


def init_databases(reset: bool = False) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _bootstrap_data_dir_from_repo_snapshot()

    if reset:
        dispose_engines()
        for db_path in (BUSINESS_DB_PATH, QUICK_QUERY_DB_PATH):
            try:
                Path(db_path).unlink(missing_ok=True)
            except Exception:
                # Keep demo robust even if unlink fails for some reason.
                pass

    business_engine = get_business_engine()
    quick_query_engine = get_quick_query_engine()

    BaseBusiness.metadata.create_all(business_engine)
    BaseQuickQuery.metadata.create_all(quick_query_engine)
    migrate_quick_query_schema(quick_query_engine)
