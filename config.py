from pathlib import Path
import os

from dotenv import load_dotenv


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
BUSINESS_DB_PATH = DATA_DIR / "business.db"
QUICK_QUERY_DB_PATH = DATA_DIR / "quick_query.db"

load_dotenv(ROOT_DIR / ".env")

SCRAPER_MAX_BOOKS = int(os.getenv("SCRAPER_MAX_BOOKS", "50"))
