# Contributing to ContextForge

1. Read [`docs/development/DEVELOPMENT.md`](docs/development/DEVELOPMENT.md) and set up both apps.
2. Create a branch, keep changes focused, and add tests: parsers and detectors need unit tests with small fixtures;
   UI flows that change need the Playwright spec updated.
3. Run the quality gates before opening a pull request: backend `ruff`, `mypy`, `pytest`; frontend `lint`, `typecheck`,
   `test`, `build`; and `./scripts/e2e.sh`.
4. Principles that reviews enforce:
   - never execute uploaded code; treat every archive and file as hostile input;
   - extract facts deterministically when possible — the LLM interprets, it does not discover;
   - every claim in generated documents must carry a source reference or an explicit `UNKNOWN`;
   - never log, persist or send secrets; never return API keys to the browser;
   - no fake data in the UI: everything shown comes from the backend.
5. Do not commit uploaded archives, generated packages, `data/`, `.env` files or keys.
