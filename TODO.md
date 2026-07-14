# TODO — backlog

Additive follow-ups, roughly by priority. (The MVP works; these are improvements.)

## Correctness / hardening
- [ ] Migrate `src/web/app.py` off the deprecated `@app.on_event("startup")` to a
      `lifespan` handler (emits a DeprecationWarning today).
- [ ] Word-boundary / FTS5 matching so short topics (e.g. "ai") don't match inside
      unrelated words in `searchable_text`.
- [ ] Respect an explicit result count in more agent branches (top-rated / most-borrowed
      currently ignore "top 3 …").

## Retrieval quality
- [ ] Rank keyword matches by number of terms matched, not just rating.
- [ ] De-duplicate near-identical scraped titles during sync.

## Web UI
- [ ] Persist chat history across reloads.
- [ ] Stream LLM responses token-by-token.
- [ ] Light/dark theme toggle.

## Testing
- [ ] Adapter tests for `LangChainLibraryAgent` provider selection with each LLM mocked.
- [ ] Integration test against a containerized Ollama (optional CI job).
- [ ] Playwright smoke test of the chat + catalog UI states.

## Ops
- [ ] Pin dependency versions for reproducible installs.
- [ ] Add ruff/black + a lint job to CI.
