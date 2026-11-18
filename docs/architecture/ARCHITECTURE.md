# ContextForge architecture

## Components

| Component | Technology | Responsibility |
|---|---|---|
| Web UI | Next.js 16 (App Router), React 19, Tailwind CSS 4, shadcn-style components, Lucide, React Flow + dagre, react-markdown + Mermaid | Upload, live progress (SSE), dashboards, context/architecture explorers, settings |
| API | FastAPI, Pydantic v2 | Upload validation, job control, intelligence/document/graph/search endpoints, settings |
| Pipeline | asyncio task per analysis; CPU-bound work in threads | 12 observable stages, cancellation, cleanup |
| Persistence | SQLite (WAL) + filesystem | Projects, stage events (replayable SSE), settings, encrypted keys; outputs under `DATA_DIR/projects/<id>/` |
| Caches | Filesystem, content-addressed | Parse results (keyed by parser version + path + sha256), AI responses (keyed by prompt hash) |

Service boundaries live in `backend/app/services/*` — extraction, scanning, dependency, parsing, architecture,
security, issues, ai, context, export, pipeline — and communicate only through the `ProjectFacts` model
(`backend/app/schemas/facts.py`). The compiler renders only from `ProjectFacts`; the AI layer only adds fields to it.

## Pipeline stages (UI stage keys)

1. `uploading` – archive streamed to disk with a size limit and ZIP magic check.
2. `extracting` – `services/extraction/safe_zip.py`.
3. `scanning` – Layer 0 (`services/scanning`).
4. `stack` – Layer 1 (`services/dependency`).
5. `parsing` – Layer 2 (`services/parsing`), in 40-file chunks with progress.
6. `mapping` – Layers 3–5 (`services/architecture`): import resolution, graph, routes, client calls, models, env, layers.
   Deterministic facts are persisted here (`deterministic_facts.json`) before any AI call.
7. `architecture` – AI stages B (file), C (module), D (cross-module), E1 (system synthesis).
8. `business_logic` – AI stage E2 (business logic, workflows, AI-proposed issues).
9. `issues` – Layer 7 security + issue detectors; AI issues overlapping static findings are dropped.
10. `markdown` – context compiler.
11. `validating` – completeness + reference integrity, package ZIP.
12. `complete`.

## Evidence model

`Claim{text, classification, sources[file,line_start,line_end], layer, confidence, verified}` with classifications
`DETECTED | INFERRED | AI_INTERPRETED | UNKNOWN`. Deterministic sections render with `DETECTED`/`INFERRED`; AI
sections render claims with their validated references. Stage F (`services/ai/evidence.py`) repairs unambiguous
paths, drops references to files that do not exist, clamps line ranges to real file lengths, flags prose that
mentions non-existent paths and lowers confidence for unsupported claims. The compiler's final validation re-checks
every `` `path:line` `` reference in every generated Markdown file.

## AI orchestration

- **Provider abstraction** – `LLMProvider.complete(LLMRequest) -> LLMResponse`, `list_models()`; adapters for Anthropic
  (official SDK, streaming, `output_config.effort`, server-side refusal fallback), OpenAI, Gemini and OpenAI-compatible
  endpoints. `register_provider()` adds new ones without touching the pipeline.
- **Prioritisation** – entry points, routes, auth, models, services, middleware and highly imported files first; tests
  and generated code last.
- **Dependency-aware batching** – batches are seeded by the highest-priority file and filled with same-module files and
  import neighbours up to the depth profile's token target.
- **Hierarchical summarisation** – file summaries feed module summaries, which feed cross-module and system synthesis.
- **Budgets** – a global token budget with reservations for later stages; requests that would exceed it are skipped and
  recorded (never silently).
- **Resilience** – bounded concurrency (semaphore), retries with exponential backoff and `Retry-After`, auth errors stop
  AI stages, malformed JSON gets one repair attempt, partial failures keep the rest, cancellation between requests.
- **Privacy** – secrets are redacted before sending; a "structure only" mode sends symbols/signatures without source.

## Data flow (web)

Browser → `POST /api/projects` (multipart) → job → SSE `GET /api/projects/{id}/events` (stage events replayed from
SQLite, then live) → on completion the UI loads `/intelligence`, `/documents`, `/graph`, `/files`, `/search` and
downloads `/download/master` or `/download/package`.
