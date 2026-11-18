# Development guide

## Setup

```bash
cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
cd frontend && npm ci
```

```bash
./scripts/dev.sh
```

## Quality gates (same as CI)

```bash
cd backend && .venv/bin/ruff check app tests && .venv/bin/mypy app && .venv/bin/pytest -q
```

```bash
cd frontend && npm run lint && npm run typecheck && npm test && npm run build
```

```bash
./scripts/e2e.sh
```

## Testing without paid API access

- Unit/integration tests use `tests/conftest.py::FakeProvider` (in-process) and two protocol-faithful fake servers
  (OpenAI Chat Completions; Anthropic Messages streaming SSE).
- For manual UI testing run `python -m tests.fake_llm_server --port 9100` (optionally `FAKE_LLM_DELAY=1.5`) and set
  Settings → provider "OpenAI-compatible endpoint", base URL `http://127.0.0.1:9100/v1`. Its replies are placeholders.
- Live provider check: `CONTEXTFORGE_LIVE_PROVIDER=anthropic ANTHROPIC_API_KEY=... pytest -m live_provider`.

## Adding an LLM provider

Implement `LLMProvider` (`backend/app/services/ai/providers/base.py`): `complete()` must return `LLMResponse` and raise
`ProviderError(retryable=..., status=..., retry_after=...)` on failure. Register it:

```python
from app.services.ai.providers.registry import register_provider
register_provider("myprovider", lambda cfg: MyProvider(cfg), {"label": "My provider", "default_model": "m-1", "needs_key": True, "needs_base_url": False, "notes": ""})
```

Add the name to `PROVIDERS` in `services/settings_service.py` to expose it in the UI.

## Adding a language or framework

- New parser: return a `ParseResult` (`services/parsing/base.py`) and dispatch it in `services/parsing/registry.py`.
  Parser source changes automatically invalidate the parse cache.
- New route framework: add extraction to the relevant parser; set `resolved_prefix=True` for file-based routing or
  `router_var` + `router_prefixes`/`mounts` for router composition so `resolve_routes()` can join prefixes.
- New technology: extend `services/dependency/knowledge.py`.

## Samples

`samples/` holds three small projects with deliberate issues. `python3 scripts/make_sample_zips.py` writes ZIPs to
`samples/dist/` (git-ignored) for UI and e2e tests.
