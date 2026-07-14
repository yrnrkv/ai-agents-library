# Project Handoff — AI Library Agent

> Written after auditing the codebase; reflects what the code on `main` **actually**
> does. Where an intake brief and the code disagreed, the code wins.

## What this is

A local-first assistant that answers natural-language questions about a book catalog.
It runs on a laptop with no paid APIs (rule-based mode), and optionally uses a cloud or
local LLM to phrase answers. It also deploys to Render.

Entry points share one core:

- **Web UI** (`uvicorn src.web.app:app`) — chat + a browsable catalog. Primary surface.
- **CLI** (`python -m src.main …`) — init/seed/scrape/sync, demo and chat modes.

## Architecture

```
 scrapers (Open Library / HKPL)   sample seed (gated by ALLOW_SAMPLE_SEED)
              \                       /
               v                     v
        Business DB (business.db)  — normalized source of truth
               │  sync_business_to_quick_query()
               v
        Quick Query DB (quick_query.db) — denormalized read index
          (+ sources_json / primary_source_url / cover_image_url)
               │
        LibraryAgent (rule-based, intent-gated)  ── search_structured() ──┐
               │                                                          v
               └────────────────────────────────►  LangChainLibraryAgent (adapter)
                                                    Gemini / Groq / Ollama / OpenAI
```

### Key design decisions (as implemented on `main`)

- **Two databases.** Business DB is the normalized write model; Quick Query DB is a
  denormalized read model rebuilt by the sync step (which clears and repopulates it).
- **`data/*.db` are committed on purpose** as a *deployment seed snapshot*. On first
  Render boot, `db._bootstrap_data_dir_from_repo_snapshot()` copies them into `DATA_DIR`
  (e.g. `/var/data`) so production starts with a full catalog. **Do not untrack them** —
  it would break production seeding. (Locally they may show as modified after a `--reset-db`
  run; restore with `git restore data/*.db` rather than committing your regenerated copy.)
- **Intent gating.** `intent.user_wants_book_catalog_results()` decides whether a message
  is a catalog request. General questions ("what is machine learning?") skip the DB search
  and don't get book cards; the LLM answers them directly.
- **Deterministic retrieval, optional generation.** `LibraryAgent` always does the lookup;
  the LLM only rephrases the structured candidates. LLM providers are a swappable adapter
  (`LangChainLibraryAgent`) and every mode falls back to rule-based output, visibly, when a
  key is missing or the provider errors.
- **Shared, thread-safe engines.** `db.py` caches engines with `check_same_thread=False`;
  FastAPI runs blocking chat/catalog work in a thread pool so health checks stay responsive.
- **PaaS-aware probes.** `SKIP_OLLAMA_PROBE` / `RENDER` skip localhost Ollama probes so
  health checks don't wait on TCP timeouts in the cloud.

## Module map

| File | Responsibility |
|------|----------------|
| `src/config.py` | Paths (+ `DATA_DIR` override) and env config |
| `src/models.py` | SQLAlchemy models for both DBs |
| `src/db.py` | Cached engines, `init_databases`, snapshot bootstrap, schema migration |
| `src/db_utils.py` | `get_or_create_*` / `upsert_book_stat` helpers |
| `src/intent.py` | Catalog-vs-general intent detection |
| `src/seed_sample_data.py` | Offline 6-book sample dataset |
| `src/scraper.py`, `src/hkpl.py` | Open Library / HKPL scrapers (best-effort, network) |
| `src/sync.py` | Business → Quick Query transform (+ provenance/cover) |
| `src/agent.py` | Rule-based, intent-gated routing |
| `src/langchain_agent.py` | LLM adapter: Gemini / Groq / Ollama / OpenAI |
| `src/main.py` | CLI entrypoint |
| `src/web/app.py` | FastAPI: `/`, `/api/chat`, `/api/catalog/books[/{id}]`, `/api/health` |
| `Procfile`, `render.yaml` | Render deployment |

## MVP scope

**Working:** seed → sync → query; web chat + catalog; rule-based answers with intent gating;
optional Gemini/Groq/Ollama/OpenAI with graceful, visible fallback; Render deploy.

**Out of scope (see `TODO.md`):** auth, multi-user, persistent history, semantic search.

## Changes made in this handoff (additive; main's core kept)

This branch was reconciled onto a `main` that had independently advanced (Gemini/Groq,
Render, intent gating, catalog UI). To avoid clobbering that work, only additive value was
layered on top:

- **Critical bug fix — `src/agent.py`:** `answer()` referenced an undefined `limit`
  (`NameError`) after the intent refactor, so **every rule-based book query crashed** —
  including the fallback path used when no LLM key is set. Added the missing
  `limit = self._extract_limit(q)`. Covered by `tests/test_agent.py::test_book_query_does_not_crash`.
- **Test suite + CI:** `tests/` (pytest, temp DBs, no network, Ollama/keys neutralized) and
  `.github/workflows/ci.yml` (Python 3.9 & 3.11) — the repo previously had none.
- **Release hygiene:** removed the stale `zip/` upload artifact and an empty `src/readme.md`;
  added `LICENSE` (MIT), this handoff, and `TODO.md`. `data/*.db` were **deliberately kept**
  tracked (deployment snapshot — see above).

## Known limitations / needs real environment

- **Gemini/Groq/OpenAI** need API keys; **Ollama** needs a local server + pulled model.
  All are covered indirectly via the visible-fallback tests but not against live providers.
- **Scrapers** depend on live sites/network; best-effort, not tested against live pages.
- Rule search is SQL substring matching (short topics can match inside longer words).

## Decision log

- 2026-07-14 — Reconciled the MVP-polish branch onto the advanced `main`: kept main's
  Gemini/Render/intent/catalog core; added tests, CI, LICENSE, docs; fixed the `limit`
  crash. Did **not** re-apply the polish branch's alternate UI/app/agent rewrites, and did
  **not** untrack `data/*.db` (they are main's Render seed snapshot).
