"""FastAPI web application for AI Library Agent."""
from __future__ import annotations

import json
import os

from .. import config as _config  # noqa: F401 — loads `.env` via config.py
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from sqlalchemy import desc, or_
from sqlalchemy.orm import Session

# Resolve paths relative to this file so the app works regardless of cwd.
_WEB_DIR = Path(__file__).parent
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"

app = FastAPI(title="AI Library Agent", version="1.0.0")
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ensure_dbs_ready() -> None:
    """Auto-initialize and seed DBs if they are missing or empty."""
    from ..db import get_business_engine, get_quick_query_engine, init_databases
    from ..models import BookSearchIndex
    from ..seed_sample_data import seed_business_sample_data
    from ..sync import sync_business_to_quick_query

    init_databases(reset=False)

    business_engine = get_business_engine()
    quick_engine = get_quick_query_engine()

    with Session(business_engine) as biz_sess, Session(quick_engine) as quick_sess:
        # If Quick Query DB is empty, seed sample data and sync.
        count = quick_sess.query(BookSearchIndex).count()
        if count == 0:
            seed_business_sample_data(biz_sess)
            sync_business_to_quick_query(biz_sess, quick_sess)


def _get_quick_session():
    """Return a new SQLAlchemy session for the Quick Query DB."""
    from ..db import get_quick_query_engine
    engine = get_quick_query_engine()
    return Session(engine)


def _ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")


def _is_ollama_reachable() -> bool:
    try:
        resp = httpx.get(_ollama_base_url(), timeout=2.0)
        return resp.status_code < 500
    except Exception:
        return False


def _list_ollama_models() -> List[str]:
    """Return list of locally available Ollama model names."""
    try:
        resp = httpx.get(f"{_ollama_base_url()}/api/tags", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        pass
    return []


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def _startup() -> None:
    """Ensure DBs exist and are seeded on first run."""
    try:
        _ensure_dbs_ready()
    except Exception as exc:
        # Log but don't crash the server — health endpoint will surface the error.
        import traceback
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    ollama_ok = _is_ollama_reachable()
    ollama_models = _list_ollama_models()
    default_models = ["qwen2.5:7b-instruct", "llama3.1:8b-instruct", "gemma3:4b"]
    # Show locally available models first, then defaults as suggestions.
    model_options = ollama_models if ollama_models else default_models
    groq_configured = bool(os.getenv("GROQ_API_KEY"))
    gemini_configured = bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    groq_models = [
        os.getenv("GROQ_MODEL", "llama-3.1-8b-instant"),
        "llama-3.3-70b-versatile",
        "mixtral-8x7b-32768",
    ]
    gemini_models = [
        os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        "gemini-2.0-flash-lite",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]
    boot = {
        "groq_configured": groq_configured,
        "gemini_configured": gemini_configured,
        "ollama_ok": ollama_ok,
        "groq_models": groq_models,
        "gemini_models": gemini_models,
        "ollama_models": model_options,
    }

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "ollama_ok": ollama_ok,
            "model_options": model_options,
            "ollama_url": _ollama_base_url(),
            "groq_configured": groq_configured,
            "gemini_configured": gemini_configured,
            "groq_models": groq_models,
            "gemini_models": gemini_models,
            "boot_json": json.dumps(boot),
        },
    )


# ---------------------------------------------------------------------------
# API models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    mode: str = Field(default="gemini")   # "gemini" | "ollama" | "groq" | "no_llm"
    model: str = Field(default="gemini-2.0-flash")


class ChatResponse(BaseModel):
    reply: str
    books: List[dict] = Field(default_factory=list)
    mode_used: str


class CatalogBook(BaseModel):
    id: int
    title: str
    author: str
    category: str
    published_year: Optional[int] = None
    rating: Optional[float] = None
    loans_count: Optional[int] = None
    sources: List[dict] = Field(default_factory=list)
    primary_source_url: Optional[str] = None
    cover_image_url: Optional[str] = None


class CatalogResponse(BaseModel):
    total: int
    offset: int
    limit: int
    books: List[CatalogBook]


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.get("/api/catalog/books", response_model=CatalogResponse)
async def catalog_books(
    q: str = "",
    source: str = "",
    limit: int = 48,
    offset: int = 0,
) -> CatalogResponse:
    from ..models import BookSearchIndex

    _ensure_dbs_ready()
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    with _get_quick_session() as session:
        query = session.query(BookSearchIndex)
        if q.strip():
            term = f"%{q.strip()}%"
            query = query.filter(
                or_(
                    BookSearchIndex.searchable_text.ilike(term),
                    BookSearchIndex.title.ilike(term),
                    BookSearchIndex.author_name.ilike(term),
                )
            )
        if source.strip():
            query = query.filter(BookSearchIndex.sources_json.ilike(f"%{source.strip()}%"))

        total = query.count()
        rows = (
            query.order_by(desc(BookSearchIndex.rating), BookSearchIndex.title)
            .offset(offset)
            .limit(limit)
            .all()
        )

        books: List[CatalogBook] = []
        for b in rows:
            sources: List[dict] = []
            if b.sources_json:
                try:
                    sources = json.loads(b.sources_json)
                except json.JSONDecodeError:
                    sources = []
            books.append(
                CatalogBook(
                    id=b.business_book_id,
                    title=b.title,
                    author=b.author_name,
                    category=b.category_name,
                    published_year=b.published_year,
                    rating=b.rating,
                    loans_count=b.loans_count,
                    sources=sources,
                    primary_source_url=b.primary_source_url,
                    cover_image_url=b.cover_image_url,
                )
            )

    return CatalogResponse(total=total, offset=offset, limit=limit, books=books)


@app.get("/api/catalog/books/{business_book_id}", response_model=CatalogBook)
async def catalog_book_detail(business_book_id: int) -> CatalogBook:
    from ..models import BookSearchIndex

    _ensure_dbs_ready()

    with _get_quick_session() as session:
        b = (
            session.query(BookSearchIndex)
            .filter(BookSearchIndex.business_book_id == business_book_id)
            .first()
        )
        if b is None:
            raise HTTPException(status_code=404, detail="Book not found")

        sources: List[dict] = []
        if b.sources_json:
            try:
                sources = json.loads(b.sources_json)
            except json.JSONDecodeError:
                sources = []

        return CatalogBook(
            id=b.business_book_id,
            title=b.title,
            author=b.author_name,
            category=b.category_name,
            published_year=b.published_year,
            rating=b.rating,
            loans_count=b.loans_count,
            sources=sources,
            primary_source_url=b.primary_source_url,
            cover_image_url=b.cover_image_url,
        )


@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    message = body.message.strip()
    mode = body.mode if body.mode in {"gemini", "ollama", "groq", "no_llm"} else "no_llm"
    _default_models = {
        "gemini": "gemini-2.0-flash",
        "ollama": "qwen2.5:7b-instruct",
        "groq": "llama-3.1-8b-instant",
        "no_llm": "n/a",
    }
    model = body.model.strip() or _default_models.get(mode, "gemini-2.0-flash")

    try:
        _ensure_dbs_ready()
    except Exception as exc:
        return ChatResponse(
            reply=f"Database error: {exc}. Run `python -m src.main --init --reset-db --seed-sample --sync` to initialize.",
            books=[],
            mode_used="error",
        )

    with _get_quick_session() as session:
        from ..agent import LibraryAgent

        rule_agent = LibraryAgent(session)

        if mode == "gemini":
            if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
                reply = rule_agent.answer(message)
                return ChatResponse(
                    reply=(
                        "⚠️ Set `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) with your Google AI Studio key. "
                        "Create one at https://aistudio.google.com/apikey — meanwhile showing rule-based results.\n\n"
                        + reply
                    ),
                    books=rule_agent.search_structured(message),
                    mode_used="no_llm_fallback",
                )
            try:
                from ..langchain_agent import LangChainLibraryAgent

                lc_agent = LangChainLibraryAgent(session, provider="gemini", gemini_model=model)
                if lc_agent.llm is None:
                    raise RuntimeError("Gemini client failed to initialize (check langchain-google-genai install)")
                reply = lc_agent.answer(message)
                books = rule_agent.search_structured(message)
                return ChatResponse(reply=reply, books=books, mode_used=f"gemini:{model}")
            except Exception as exc:
                reply = rule_agent.answer(message)
                return ChatResponse(
                    reply=f"⚠️ Gemini error ({exc}). Showing rule-based results.\n\n{reply}",
                    books=rule_agent.search_structured(message),
                    mode_used="no_llm_fallback",
                )

        if mode == "groq":
            if not os.getenv("GROQ_API_KEY"):
                reply = rule_agent.answer(message)
                return ChatResponse(
                    reply=(
                        "⚠️ Set `GROQ_API_KEY` for cloud LLM (free tier on Groq). "
                        "Get a key at https://console.groq.com — meanwhile showing rule-based results.\n\n"
                        + reply
                    ),
                    books=rule_agent.search_structured(message),
                    mode_used="no_llm_fallback",
                )
            try:
                from ..langchain_agent import LangChainLibraryAgent

                lc_agent = LangChainLibraryAgent(session, provider="groq", groq_model=model)
                if lc_agent.llm is None:
                    raise RuntimeError("Groq client failed to initialize")
                reply = lc_agent.answer(message)
                books = rule_agent.search_structured(message)
                return ChatResponse(reply=reply, books=books, mode_used=f"groq:{model}")
            except Exception as exc:
                reply = rule_agent.answer(message)
                return ChatResponse(
                    reply=f"⚠️ Groq error ({exc}). Showing rule-based results.\n\n{reply}",
                    books=rule_agent.search_structured(message),
                    mode_used="no_llm_fallback",
                )

        if mode == "ollama":
            if not _is_ollama_reachable():
                # Graceful fallback to rule-based agent with explanation.
                reply = rule_agent.answer(message)
                return ChatResponse(
                    reply=(
                        f"⚠️ Ollama is not running at {_ollama_base_url()}. "
                        "Showing rule-based results instead.\n\n" + reply
                    ),
                    books=rule_agent.search_structured(message),
                    mode_used="no_llm_fallback",
                )

            try:
                from ..langchain_agent import LangChainLibraryAgent

                lc_agent = LangChainLibraryAgent(
                    session,
                    provider="ollama",
                    ollama_models=[model],
                )
                reply = lc_agent.answer(message)
                books = rule_agent.search_structured(message)
                return ChatResponse(reply=reply, books=books, mode_used=f"ollama:{model}")
            except Exception as exc:
                reply = rule_agent.answer(message)
                return ChatResponse(
                    reply=f"⚠️ LLM error ({exc}). Showing rule-based results.\n\n{reply}",
                    books=rule_agent.search_structured(message),
                    mode_used="no_llm_fallback",
                )

        # mode == "no_llm"
        reply = rule_agent.answer(message)
        books = rule_agent.search_structured(message)
        return ChatResponse(reply=reply, books=books, mode_used="no_llm")


@app.get("/api/health")
async def health() -> JSONResponse:
    from ..config import BUSINESS_DB_PATH, QUICK_QUERY_DB_PATH

    biz_exists = Path(BUSINESS_DB_PATH).exists()
    qq_exists = Path(QUICK_QUERY_DB_PATH).exists()
    ollama_ok = _is_ollama_reachable()
    ollama_models = _list_ollama_models()

    status = "ok" if (biz_exists and qq_exists) else "degraded"
    return JSONResponse(
        {
            "status": status,
            "business_db": biz_exists,
            "quick_query_db": qq_exists,
            "ollama_reachable": ollama_ok,
            "ollama_models": ollama_models,
            "ollama_url": _ollama_base_url(),
            "groq_configured": bool(os.getenv("GROQ_API_KEY")),
            "gemini_configured": bool(os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")),
            "openai_configured": bool(os.getenv("OPENAI_API_KEY")),
        }
    )
