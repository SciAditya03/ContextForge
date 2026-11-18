# Example output

`fullstack-notes.CONTEXTFORGE_PROJECT_CONTEXT.md` is the master document ContextForge generated for
[`samples/fullstack-notes`](../../samples/fullstack-notes) in **deterministic mode** (no LLM provider configured), so
sections that need AI interpretation are explicitly marked `UNKNOWN`. With a provider configured, those sections are
filled with `AI_INTERPRETED` claims carrying validated source references.

Reproduce:

```bash
cd backend && .venv/bin/python -m app.cli analyze ../samples/fullstack-notes --out /tmp/notes-context --name "Notes (sample)"
```
