"""FastAPI endpoints. Ollama probes are skipped and no cloud keys are set, so
every LLM mode degrades to visible rule-based fallback — no network needed."""


def test_health_ok_after_startup(client):
    data = client.get("/api/health").json()
    assert data["business_db"] is True
    assert data["quick_query_db"] is True
    assert data["ollama_reachable"] is False   # probes skipped in tests


def test_chat_no_llm_returns_books(client):
    resp = client.post("/api/chat", json={"message": "top rated books", "mode": "no_llm"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode_used"] == "no_llm"
    assert len(data["books"]) > 0
    assert "Top rated books" in data["reply"]


def test_chat_gemini_without_key_falls_back(client):
    """Default cloud mode with no key degrades visibly, not with a 500."""
    resp = client.post("/api/chat", json={"message": "find books about python", "mode": "gemini"})
    data = resp.json()
    assert data["mode_used"] == "no_llm_fallback"
    assert "GEMINI_API_KEY" in data["reply"]
    assert len(data["books"]) > 0


def test_chat_ollama_offline_falls_back(client):
    resp = client.post("/api/chat", json={"message": "find python books", "mode": "ollama"})
    data = resp.json()
    assert data["mode_used"] == "no_llm_fallback"
    assert "not running" in data["reply"]


def test_chat_validation_rejects_empty_message(client):
    assert client.post("/api/chat", json={"message": "", "mode": "no_llm"}).status_code == 422


def test_chat_validation_rejects_overlong_message(client):
    assert client.post("/api/chat", json={"message": "x" * 501, "mode": "no_llm"}).status_code == 422


def test_catalog_lists_books(client):
    data = client.get("/api/catalog/books").json()
    assert data["total"] > 0
    assert len(data["books"]) > 0
    assert "title" in data["books"][0]


def test_catalog_detail_404_for_missing(client):
    assert client.get("/api/catalog/books/999999").status_code == 404
