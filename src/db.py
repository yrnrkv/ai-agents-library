from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine

from .config import BUSINESS_DB_PATH, QUICK_QUERY_DB_PATH, DATA_DIR
from .models import BaseBusiness, BaseQuickQuery


def get_business_engine():
    return create_engine(f"sqlite:///{BUSINESS_DB_PATH}", future=True)


def get_quick_query_engine():
    return create_engine(f"sqlite:///{QUICK_QUERY_DB_PATH}", future=True)


def init_databases(reset: bool = False) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    if reset:
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
