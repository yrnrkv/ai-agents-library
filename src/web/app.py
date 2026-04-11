"""FastAPI web application for AI Library Agent."""
from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
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

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "ollama_ok": ollama_ok,
            "model_options": model_options,
            "ollama_url": _ollama_base_url(),
        },
    )


# ---------------------------------------------------------------------------
# API models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=500)
    mode: str = Field(default="ollama")   # "ollama" | "no_llm"
    model: str = Field(default="qwen2.5:7b-instruct")


class ChatResponse(BaseModel):
    reply: str
    books: List[dict] = []
    mode_used: str


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@app.post("/api/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
    message = body.message.strip()
    mode = body.mode if body.mode in {"ollama", "no_llm"} else "no_llm"
    model = body.model.strip() or "qwen2.5:7b-instruct"

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
        }
    )
