# AI Library Agent Demo

A complete local demo for your AI Library project task:

- Business DB (`data/business.db`) - source of truth for rich book records
- Quick Query DB (`data/quick_query.db`) - read-optimized index for AI queries
- Optional scrapers to collect public book data (Open Library + HKPL Top 100)
- Sync process to transform Business DB data into Quick Query DB
- Demo AI agent that answers library questions from the Quick Query DB
- Optional LangChain wrapper (`--langchain-chat` or `--ollama-chat`) that uses an LLM to summarize DB results

## Deploy on Render (Gemini + full catalog)

This repo includes `render.yaml` for one-click Blueprint deploy.

1. Push this repo to GitHub.
2. In Render, create a new Blueprint from your repo.
3. Set secret `GEMINI_API_KEY` in Render environment variables.
4. Keep `DATA_DIR=/var/data` and attached disk enabled (defined in `render.yaml`).
5. Deploy and verify:
   - `GET /api/health` should show:
     - `gemini_configured: true`
     - `business_books` ~= `quick_index_books` (for this dataset: ~514)

Notes:
- Startup does **not** seed the tiny sample dataset unless `ALLOW_SAMPLE_SEED=1`.
- On first boot with an empty disk, app bootstraps DB files from repo `data/` into `DATA_DIR`.

## 1) Setup

```bash
cd ai-library-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### Important after schema upgrade
This project uses an upgraded (multi-table) schema. If you already ran it before, start fresh once:

```bash
python -m src.main --init --reset-db
```

## 2) Run full demo with sample dataset

```bash
python -m src.main --init --reset-db --seed-sample --sync --demo
```

## 3) Run with online scraping (optional)

Open Library topic scrape:

```bash
python -m src.main --init --reset-db --scrape --topic "computer science" --limit 40 --sync --demo
```

HKPL Top 100 Most Borrowed Books scrape (English pages):

```bash
python -m src.main --init --reset-db --scrape-hkpl --hkpl-year 2025 --hkpl-limit 50 --sync --demo
```

Note: scraping may be blocked by your network/proxy settings. If it fails, the app still runs with whatever data is already in the Business DB.

## 4) Interactive mode

```bash
python -m src.main --chat
```

## 5) LangChain-powered chat (optional)
You have two options:

### Option A: OpenAI (paid, if you provide a key)
Requires `OPENAI_API_KEY`.

```bash
export OPENAI_API_KEY="your_key_here"
python -m src.main --init --reset-db --seed-sample --sync --langchain-chat
```

### Option B: Free local chat with Ollama (recommended)
1) Install Ollama on your MacBook
2) Pull 1-2 models (recommended):

```bash
ollama pull qwen2.5:7b-instruct
ollama pull llama3.1:8b-instruct
```

Then run (this will try the default model list and pick the best):

```bash
python -m src.main --init --reset-db --seed-sample --sync --ollama-chat
```

To try different Ollama models:

```bash
python -m src.main --init --reset-db --seed-sample --sync --ollama-chat --ollama-models "qwen2.5:14b-instruct,llama3.1:8b-instruct"
```

Example questions:
- `find books about python`
- `recommend 5 books for beginner ai`
- `show books by andrew ng`
- `what are top rated machine learning books`
- `what are most borrowed books`

## Project structure

- `src/db.py` - DB engines and table creation
- `src/models.py` - SQLAlchemy models for both DBs
- `src/db_utils.py` - small “get or create / upsert” helpers
- `src/seed_sample_data.py` - local sample dataset generator
- `src/scraper.py` - Open Library scraper
- `src/hkpl.py` - HKPL Top 100 scraper (seeds Business DB)
- `src/sync.py` - Business DB -> Quick Query DB sync process
- `src/agent.py` - simple AI query agent logic
- `src/langchain_agent.py` - LangChain wrapper that summarizes DB results
- `src/main.py` - CLI entrypoint
- `src/web/app.py` - FastAPI web application
- `src/web/templates/index.html` - chat UI template
- `src/web/static/style.css` - CSS styles

## Notes

- If no existing Business DB is available, use `--seed-sample` or `--scrape`.
- Business DB and Quick Query DB are intentionally different schemas.
- Quick Query DB stores only useful query fields (denormalized) for fast reads.
- This is intentionally lightweight so it runs on any laptop without external AI APIs.

## Web UI (FastAPI)

A simple, modern chat interface that queries the library database and returns responses, powered by Ollama (free local LLM) via LangChain.

### Windows PowerShell — one-time setup

```powershell
# 1. Clone and enter the repo
git clone https://github.com/yrnrkv/ai-agents-library.git
cd ai-agents-library

# 2. Create and activate a virtual environment
py -m venv .venv
.\.venv\Scripts\activate

# 3. Install dependencies
py -m pip install -U pip
pip install -r requirements.txt
```

### Install Ollama (free local LLM)

1. Download and install Ollama from **https://ollama.com/download** (Windows installer).
2. Open a new terminal and pull a model:

```powershell
ollama pull qwen2.5:7b-instruct
```

> Other models to try: `llama3.1:8b-instruct`, `gemma3:4b`

### Start the web server

```powershell
# Make sure your venv is active first: .\.venv\Scripts\activate
uvicorn src.web.app:app --reload
```

The server auto-initializes DB schema on first run.  
Sample seed data is only inserted when `ALLOW_SAMPLE_SEED=1` (or via CLI `--seed-sample`).  
Open **http://127.0.0.1:8000** in your browser.

### Usage

- **Ollama mode** (default when Ollama is running): uses LangChain + Ollama for natural-language answers.
- **Rule-based mode**: fast deterministic answers directly from the DB — no LLM required.
- Use the **model selector** in the sidebar to choose between locally available Ollama models.
- The sidebar shows Ollama connection status and setup steps.

### API endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/` | Chat UI homepage |
| `POST` | `/api/chat` | `{ "message": "...", "mode": "ollama"\|"no_llm", "model": "..." }` |
| `GET` | `/api/health` | DB and Ollama status |
