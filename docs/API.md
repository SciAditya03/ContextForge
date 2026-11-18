# HTTP API

Base URL `http://localhost:8000`. Interactive OpenAPI docs at `/docs`. If `CONTEXTFORGE_API_TOKEN` is set, send
`Authorization: Bearer <token>` (or `?token=` for downloads/SSE).

| Method | Path | Description |
|---|---|---|
| GET | `/api/health` | Liveness, version, whether a token is required |
| POST | `/api/projects` | Multipart upload: `file` (.zip), optional `name`, `description`, `depth` (`quick`/`standard`/`deep`), `provider`, `model`. Returns `202 {id}` |
| GET | `/api/projects` | List analyses |
| GET | `/api/projects/{id}` | Project, stats and stage snapshot |
| GET | `/api/projects/{id}/events` | Server-Sent Events (`stage`, `status`); supports `Last-Event-ID` / `?after=` replay |
| POST | `/api/projects/{id}/cancel` | Cancel a running analysis |
| DELETE | `/api/projects/{id}` | Delete an analysis and its outputs |
| GET | `/api/projects/{id}/intelligence` | Dashboard data (overview, stack, routes, models, findings, coverage, AI run, synthesis) |
| GET | `/api/projects/{id}/graph?view=modules\|files\|api\|database&limit=` | Graph nodes/edges for the explorer |
| GET | `/api/projects/{id}/files` | Analysis manifest per file |
| GET | `/api/projects/{id}/documents` | Generated documents index |
| GET | `/api/projects/{id}/documents/{path}` | Document content (Markdown/JSON) |
| GET | `/api/projects/{id}/search?q=` | Full-text search across Markdown documents |
| GET | `/api/projects/{id}/download/master` | Master Markdown file |
| GET | `/api/projects/{id}/download/package` | Complete context package (ZIP) |
| GET | `/api/projects/{id}/download/doc/{path}` | Any single document |
| GET | `/api/settings` | Provider settings, key status (never values), analysis preferences, limits |
| PUT | `/api/settings/provider` | Provider, model, base URL, temperature, max tokens, timeout, retries |
| PUT | `/api/settings/analysis` | Depth, token budget, parse size, concurrency, exclusions, privacy switches |
| PUT / DELETE | `/api/settings/keys/{provider}` | Store (encrypted) / remove an API key — write-only |
| POST | `/api/settings/test` | Send one tiny real request to the configured provider |
| POST | `/api/settings/models` | List models available to the configured key |
