import json
import os
import re
from typing import List, Optional

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
    ):
        self.rule_agent = LibraryAgent(quick_query_session)
        self.provider = provider
        self.openai_api_key = os.getenv("OPENAI_API_KEY")

        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_models = ollama_models or ["qwen2.5:7b-instruct", "llama3.1:8b-instruct"]

        self.llm = None
        self.selected_ollama_model: Optional[str] = None

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

    def _init_ollama_if_requested(self) -> None:
        if self.llm is not None:
            return  # OpenAI selected.

        if self.provider not in {"auto", "ollama"}:
            return

        # Lazily select model on first query; we may not have Ollama running yet.
        self.llm = None

    def answer(self, user_query: str) -> str:
        # If caller requested Ollama (free local models), do that first.
        if self.provider == "ollama":
            return self._answer_with_ollama(user_query)

        # If we have an OpenAI-backed LLM, use it.
        if self.llm is not None:
            limit = self._extract_limit(user_query, default=5)
            candidates = self.rule_agent.search_structured(user_query, limit=limit)
            prompt = self._build_prompt(user_query=user_query, candidates=candidates)

            resp = self.llm.invoke(prompt)
            return resp.content if hasattr(resp, "content") else str(resp)

        # Auto mode: no OpenAI, so try Ollama for free.
        if self.provider == "auto":
            return self._answer_with_ollama(user_query)

        return self.rule_agent.answer(user_query)

    def _answer_with_ollama(self, user_query: str) -> str:
        try:
            from langchain_ollama import ChatOllama
        except Exception:
            # If langchain-ollama isn't installed, fall back to deterministic answers.
            return self.rule_agent.answer(user_query)

        limit = self._extract_limit(user_query, default=5)
        candidates = self.rule_agent.search_structured(user_query, limit=limit)

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

    @staticmethod
    def _build_prompt(*, user_query: str, candidates: List[dict]) -> str:
        if candidates:
            return (
                "You are a helpful AI assistant.\n"
                "You have library database candidates and a user question.\n"
                "If the question is about books/library topics, prioritize these candidates.\n"
                "For each recommended book, include the exact title from the candidate list.\n"
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
