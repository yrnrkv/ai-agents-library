import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import List, Optional

import requests

from .agent import LibraryAgent
from .intent import user_wants_book_catalog_results


def _env_float(name: str, default: float, *, min_value: Optional[float] = None, max_value: Optional[float] = None) -> float:
    value = default
    raw = os.getenv(name, "")
    if raw.strip():
        try:
            value = float(raw)
        except ValueError:
            value = default
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value


def _invoke_llm_with_timeout(llm, prompt: str, timeout_s: float) -> str:
    """
    Hard wall-clock cap on llm.invoke — avoids hanging forever when the HTTP
    client ignores shorter timeouts (important for Render/proxy limits).
    """
    timeout_s = max(1.0, float(timeout_s))

    def _call():
        return llm.invoke(prompt)

    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(_call)
    try:
        resp = fut.result(timeout=timeout_s)
    except FuturesTimeout:
        fut.cancel()
        raise TimeoutError(
            f"LLM did not finish within {timeout_s:.0f}s "
            "(the request may have been cut off by the host or network)."
        ) from None
    finally:
        # Do not wait for long-running LLM calls after timeout.
        ex.shutdown(wait=False, cancel_futures=True)
    return resp.content if hasattr(resp, "content") else str(resp)


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
        # Default to models that often have separate free-tier quotas from gemini-2.0-flash.
        self.gemini_model = gemini_model or os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")

        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.ollama_models = ollama_models or ["qwen2.5:7b-instruct", "llama3.1:8b-instruct"]

        self.llm = None
        self.selected_ollama_model: Optional[str] = None
        self._uses_gemini = False

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

            tout = _env_float("CLOUD_LLM_PER_CALL_TIMEOUT", 40.0, min_value=10.0, max_value=120.0)
            kwargs = dict(
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                temperature=0,
                api_key=self.openai_api_key,
                timeout=tout,
            )
            try:
                self.llm = ChatOpenAI(**kwargs)
            except TypeError:
                kwargs.pop("timeout", None)
                self.llm = ChatOpenAI(**kwargs)
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

            tout = _env_float("CLOUD_LLM_PER_CALL_TIMEOUT", 40.0, min_value=10.0, max_value=120.0)
            kwargs = dict(
                model=self.groq_model,
                temperature=0,
                openai_api_key=self.groq_api_key,
                openai_api_base="https://api.groq.com/openai/v1",
                timeout=tout,
            )
            try:
                self.llm = ChatOpenAI(**kwargs)
            except TypeError:
                kwargs.pop("timeout", None)
                self.llm = ChatOpenAI(**kwargs)
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
            self._uses_gemini = True
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
        wants_books = user_wants_book_catalog_results(user_query)

        # If caller requested Ollama (free local models), do that first.
        if self.provider == "ollama":
            return self._answer_with_ollama(user_query, wants_books=wants_books)

        # If we have a cloud / OpenAI-compatible LLM, use it.
        if self.llm is not None:
            candidates: List[dict] = []
            if wants_books:
                limit = self._extract_limit(user_query, default=5)
                candidates = self.rule_agent.search_structured(user_query, limit=limit)
            prompt = self._build_prompt(user_query=user_query, candidates=candidates)
            return self._invoke_cloud_llm(prompt)

        # Auto mode: no OpenAI, so try Ollama for free.
        if self.provider == "auto":
            return self._answer_with_ollama(user_query, wants_books=wants_books)

        return self.rule_agent.answer(user_query)

    def _invoke_cloud_llm(self, prompt: str) -> str:
        """Invoke LLM; Gemini gets retries, backoff, and model fallbacks on 429."""
        if self._uses_gemini and self.google_api_key:
            return self._invoke_gemini_with_retries_and_fallbacks(prompt)

        tout = _env_float("CLOUD_LLM_PER_CALL_TIMEOUT", 40.0, min_value=10.0, max_value=120.0)
        return _invoke_llm_with_timeout(self.llm, prompt, tout)

    def _invoke_gemini_with_retries_and_fallbacks(self, prompt: str) -> str:
        from langchain_google_genai import ChatGoogleGenerativeAI

        budget = _env_float("GEMINI_TOTAL_BUDGET_SEC", 55.0, min_value=20.0, max_value=180.0)
        per_call = _env_float("CLOUD_LLM_PER_CALL_TIMEOUT", 40.0, min_value=10.0, max_value=120.0)
        min_call = _env_float("GEMINI_MIN_CALL_TIMEOUT", 20.0, min_value=8.0, max_value=60.0)
        deadline = time.monotonic() + max(15.0, budget)

        preferred = [self.gemini_model]
        # Short list: each extra model multiplies worst-case wait under quota errors.
        fallbacks = ["gemini-2.0-flash-lite", "gemini-1.5-flash"]
        models: List[str] = []
        for m in preferred + fallbacks:
            if m and m not in models:
                models.append(m)

        last_err: Optional[Exception] = None
        for model_name in models:
            if time.monotonic() >= deadline:
                break
            llm = ChatGoogleGenerativeAI(
                model=model_name,
                temperature=0,
                google_api_key=self.google_api_key,
            )
            for attempt in range(2):
                if time.monotonic() >= deadline:
                    break
                remaining = deadline - time.monotonic()
                usable = max(4.0, remaining - 0.5)
                target = max(min_call, per_call)
                call_timeout = min(usable, target)
                try:
                    return _invoke_llm_with_timeout(llm, prompt, call_timeout)
                except TimeoutError as e:
                    last_err = e
                    break
                except Exception as e:
                    last_err = e
                    err_text = str(e)
                    if "429" in err_text or "RESOURCE_EXHAUSTED" in err_text:
                        delay_m = re.search(r"retry in ([\d.]+)s", err_text, re.I)
                        base = float(delay_m.group(1)) + 1.0 if delay_m else 4.0
                        delay = min(15.0, base, max(0.0, deadline - time.monotonic() - 2.0))
                        if delay > 0.5:
                            time.sleep(delay)
                        continue
                    break
        if last_err:
            raise last_err
        raise RuntimeError("Gemini invocation failed with no exception detail")

    def _answer_with_ollama(self, user_query: str, *, wants_books: bool) -> str:
        limit = self._extract_limit(user_query, default=5)
        candidates = self.rule_agent.search_structured(user_query, limit=limit) if wants_books else []

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
        tout = _env_float("OLLAMA_INVOKE_TIMEOUT", 60.0, min_value=10.0, max_value=180.0)
        return _invoke_llm_with_timeout(llm, prompt, tout)

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
                "The user asked for book recommendations or to find books in the library.\n"
                "Use ONLY the provided candidates; recommend from this list when appropriate.\n"
                "For each recommended book, include the EXACT title string and its numeric catalog id (field id).\n"
                "Keep the answer focused on these books; do not invent titles not in the JSON.\n\n"
                f"User question: {user_query}\n\n"
                f"Library candidates (JSON): {json.dumps(candidates, ensure_ascii=False)}\n\n"
                "Answer:"
            )

        return (
            "You are a helpful general AI assistant.\n"
            "The user did NOT ask for book recommendations or a library search — answer their question directly.\n"
            "Do not suggest books or a reading list unless they clearly ask for books in this same message.\n"
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
                tout = _env_float("OLLAMA_INVOKE_TIMEOUT", 45.0, min_value=8.0, max_value=120.0)
                text = _invoke_llm_with_timeout(llm, prompt, tout)

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
