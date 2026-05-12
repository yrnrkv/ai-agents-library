import json
import os
import re
from typing import List, Optional
import requests

from .agent import LibraryAgent


class LangChainLibraryAgent:
    """
    LangChain wrapper around the local rule/tooling logic.

    - We keep DB querying deterministic (LibraryAgent.search_structured).
    - LangChain/LLM turns structured results into a natural response.
    """

    def __init__(
        self,
        quick_query_session,
        provider: str = "auto",
        ollama_models: Optional[List[str]] = None,
        groq_model: Optional[str] = None,
        gemini_model: Optional[str] = None,
    ):
        self.rule_agent = LibraryAgent(quick_query_session)
        self.provider = provider
        self.openai_api_key = os.getenv("OPENAI_API_KEY")
        self.groq_api_key = os.getenv("GROQ_API_KEY")
        self.groq_model = groq_model or os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        self.google_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.gemini_model = gemini_model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_models = ollama_models or ["qwen2.5:7b-instruct", "llama3.1:8b-instruct"]

        self.llm = None
        self.selected_ollama_model: Optional[str] = None

        if provider == "ollama":
            self._init_ollama_if_requested()
        elif provider == "groq":
            self._init_groq()
        elif provider == "gemini":
            self._init_gemini()
        elif provider == "openai":
            self._init_openai()
        else:  # auto — prefer Gemini (works well in HK), then Groq, then OpenAI
            if self.google_api_key:
                self._init_gemini()
            elif self.groq_api_key:
                self._init_groq()
            elif self.openai_api_key:
                self._init_openai()
            self._init_ollama_if_requested()

    def _init_openai(self) -> None:
        if self.provider not in {"auto", "openai"}:
            return
        if not self.openai_api_key:
            return

        try:
            from langchain_openai import ChatOpenAI

            self.llm = ChatOpenAI(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0,
                api_key=self.openai_api_key,
            )
        except Exception:
            # If LangChain/OpenAI imports fail, we fallback.
            self.llm = None

    def _init_groq(self) -> None:
        if self.provider not in {"auto", "groq"}:
            return
        if not self.groq_api_key:
            return
        try:
            from langchain_openai import ChatOpenAI

            self.llm = ChatOpenAI(
                model=self.groq_model,
                temperature=0,
                openai_api_key=self.groq_api_key,
                openai_api_base="https://api.groq.com/openai/v1",
            )
        except Exception:
            self.llm = None

    def _init_gemini(self) -> None:
        if self.provider not in {"auto", "gemini"}:
            return
        if not self.google_api_key:
            return
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI

            self.llm = ChatGoogleGenerativeAI(
                model=self.gemini_model,
                temperature=0,
                google_api_key=self.google_api_key,
            )
        except Exception:
            self.llm = None

    def _init_ollama_if_requested(self) -> None:
        if self.llm is not None:
            return  # Cloud LLM already selected.

        if self.provider not in {"auto", "ollama"}:
            return

        # Lazily select model on first query; we may not have Ollama running yet.
        self.llm = None

    def answer(self, user_query: str) -> str:
        is_library_query = self._is_library_query(user_query)

        # If caller requested Ollama (free local models), do that first.
        if self.provider == "ollama":
            return self._answer_with_ollama(user_query, is_library_query=is_library_query)

        # If we have an OpenAI-backed LLM, use it.
        if self.llm is not None:
            candidates: List[dict] = []
            if is_library_query:
                limit = self._extract_limit(user_query, default=5)
                candidates = self.rule_agent.search_structured(user_query, limit=limit)
            prompt = self._build_prompt(user_query=user_query, candidates=candidates)

            resp = self.llm.invoke(prompt)
            return resp.content if hasattr(resp, "content") else str(resp)

        # Auto mode: no OpenAI, so try Ollama for free.
        if self.provider == "auto":
            return self._answer_with_ollama(user_query, is_library_query=is_library_query)

        return self.rule_agent.answer(user_query)

    def _answer_with_ollama(self, user_query: str, *, is_library_query: bool) -> str:
        limit = self._extract_limit(user_query, default=5)
        candidates = self.rule_agent.search_structured(user_query, limit=limit) if is_library_query else []

        try:
            from langchain_ollama import ChatOllama
        except Exception:
            # If langchain-ollama isn't available, try Ollama HTTP API directly.
            return self._answer_with_ollama_http(user_query=user_query, candidates=candidates)

        # Pick the best model by a simple overlap score on candidate titles.
        best_model = self.selected_ollama_model
        if not best_model:
            best_model, _ = self._choose_best_ollama_model(
                user_query=user_query,
                candidates=candidates,
                models=self.ollama_models,
                llm_factory=lambda m: ChatOllama(
                    model=m,
                    temperature=0,
                    base_url=self.ollama_base_url,
                ),
            )
            self.selected_ollama_model = best_model

        llm = ChatOllama(
            model=best_model,
            temperature=0,
            base_url=self.ollama_base_url,
        )

        prompt = self._build_prompt(user_query=user_query, candidates=candidates)
        resp = llm.invoke(prompt)
        return resp.content if hasattr(resp, "content") else str(resp)

    def _answer_with_ollama_http(self, *, user_query: str, candidates: List[dict]) -> str:
        model = self.selected_ollama_model or (self.ollama_models[0] if self.ollama_models else "llama3.1:8b-instruct")
        prompt = self._build_prompt(user_query=user_query, candidates=candidates)

        try:
            resp = requests.post(
                f"{self.ollama_base_url.rstrip('/')}/api/chat",
                json={
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                },
                timeout=30,
            )
            resp.raise_for_status()
            payload = resp.json()
            message = payload.get("message", {})
            content = message.get("content", "")
            if content:
                self.selected_ollama_model = model
                return content
        except Exception:
            pass

        # Final fallback if no LLM backend is reachable.
        return self.rule_agent.answer(user_query)

    @staticmethod
    def _build_prompt(*, user_query: str, candidates: List[dict]) -> str:
        if candidates:
            return (
                "You are a helpful AI assistant.\n"
                "You have library database candidates and a user question.\n"
                "If the question is about books/library topics, prioritize these candidates.\n"
                "For each recommended book from the list, include the EXACT title string and its numeric catalog id (field id).\n"
                "Readers will match titles to the in-app catalog using that id.\n"
                "If the question is not related to library/books, answer normally as a general assistant.\n"
                "Keep responses concise and clear.\n\n"
                f"User question: {user_query}\n\n"
                f"Library candidates (JSON): {json.dumps(candidates, ensure_ascii=False)}\n\n"
                "Answer:"
            )

        return (
            "You are a helpful general AI assistant.\n"
            "Answer the user question directly and clearly.\n"
            "If the question needs live/real-time data, say you need a connected external data tool.\n\n"
            f"User question: {user_query}\n\n"
            "Answer:"
        )

    def _choose_best_ollama_model(self, *, user_query: str, candidates: List[dict], models: List[str], llm_factory):
        title_list = [c.get("title", "") for c in candidates if c.get("title")]

        best_model = models[0] if models else None
        best_score = -1

        for model in models:
            try:
                llm = llm_factory(model)
                prompt = self._build_prompt(user_query=user_query, candidates=candidates)
                resp = llm.invoke(prompt)
                text = resp.content if hasattr(resp, "content") else str(resp)

                # Score: count how many candidate titles appear in the response.
                score = 0
                text_lower = text.lower()
                for t in title_list:
                    if t and t.lower() in text_lower:
                        score += 1

                if score > best_score:
                    best_score = score
                    best_model = model
            except Exception:
                continue

        # If everything fails, fall back to deterministic behavior.
        if not best_model:
            return models[0], -1
        return best_model, best_score

    @staticmethod
    def _extract_limit(query: str, default: int = 5) -> int:
        q = query.strip().lower()
        m = re.search(r"\b(\d{1,2})\b", q)
        if not m:
            return default
        value = int(m.group(1))
        return max(1, min(value, 20))

    @staticmethod
    def _is_library_query(query: str) -> bool:
        q = query.strip().lower()
        if not q:
            return False
        library_terms = (
            "book",
            "books",
            "author",
            "library",
            "borrow",
            "borrowed",
            "rating",
            "novel",
            "isbn",
            "call number",
            "category",
            "title",
            "top rated",
            "most borrowed",
        )
        return any(term in q for term in library_terms)
