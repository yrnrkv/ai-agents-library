import os
from pathlib import Path

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


def _resolve_data_dir() -> Path:
    configured = os.getenv("DATA_DIR", "").strip()
    if configured:
        return Path(configured).expanduser()
    return ROOT_DIR / "data"


DATA_DIR = _resolve_data_dir()
BUSINESS_DB_PATH = DATA_DIR / "business.db"
QUICK_QUERY_DB_PATH = DATA_DIR / "quick_query.db"

SCRAPER_MAX_BOOKS = int(os.getenv("SCRAPER_MAX_BOOKS", "50"))
