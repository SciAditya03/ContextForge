# Security

## Threat model

ContextForge ingests **untrusted archives** and may forward derived text to **third-party LLM providers**. The goals are:
never execute uploaded content, never escape the extraction directory, never leak credentials (from uploads or from the
operator's provider keys), and keep the service available under hostile input.

## Archive handling (`backend/app/services/extraction/safe_zip.py`)

| Risk | Control |
|---|---|
| Path traversal / zip-slip | Member names normalised; absolute paths, drive letters, `..` and NUL rejected; resolved target must stay under the extraction root. |
| Symlinks | Never created; recorded as skipped. |
| ZIP bombs | Declared-size sanity check, per-entry compression-ratio limit, streamed byte accounting against per-file and total limits. |
| Resource exhaustion | Upload size limit (streamed), file-count limit, extraction timeout, per-file parse size limit, bounded AI concurrency, max 2 parallel analyses. |
| Encrypted entries | Skipped. |
| Execution | Nothing is executed: no installs, scripts, migrations, builds or binaries. Extracted files are written `0600`. |
| Parser attacks | XML with DTD/entities refused; YAML `safe_load`; JSON/TOML stdlib parsers; tree-sitter for JS/TS. |
| Cleanup | Extracted sources and the uploaded archive are deleted after analysis (configurable). |

## Secrets

- Detection (`services/security/secrets.py`): provider key formats (AWS, GitHub, OpenAI, Anthropic, Google, Slack,
  Stripe, Twilio, SendGrid), private-key blocks, JWTs, credentials in connection URLs, high-entropy secret assignments;
  placeholders and templates are ignored.
- Redaction happens at parse time (symbol signatures, docstrings, SQL snippets, URLs), on every outgoing AI request, and
  on every generated file. Findings show only a redacted prefix and length.
- Committed `.env` files are reported (high severity only when they contain non-placeholder secret values).

## Operator credentials

- Provider keys come from environment variables (preferred) or are stored Fernet-encrypted in SQLite (key from
  `CONTEXTFORGE_SECRET_KEY` or a generated `0600` key file). The settings API is write-only for keys.
- Gemini keys are sent in the `x-goog-api-key` header, never in URLs. Logs pass through a secret-scrubbing filter.
- Custom base URLs for OpenAI/Anthropic/Gemini are refused unless `CONTEXTFORGE_ALLOW_PROVIDER_BASE_URL_OVERRIDE=true`,
  so whoever can reach the settings API cannot redirect the operator's key to another host. OpenAI-compatible endpoints
  always use their own key.

## Web/API

- CORS allow-list, no credentials mode; `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` headers.
- Optional shared-secret API token (`CONTEXTFORGE_API_TOKEN`); for multi-user deployments put ContextForge behind an
  authenticating reverse proxy.
- Document downloads resolve paths inside the project's output directory only.
- Docker: non-root users; the API container runs with a read-only root filesystem and `no-new-privileges`; compose
  publishes ports on 127.0.0.1 only. Set `CONTEXTFORGE_API_TOKEN` (and TLS via a reverse proxy) before exposing it.

## Reporting

Please report vulnerabilities privately via GitHub security advisories on this repository.
