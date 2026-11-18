#!/usr/bin/env bash
# Start backend + fake OpenAI-compatible LLM + production frontend, run Playwright, then stop everything.
# Requires: backend deps installed (python), `npm ci` done in frontend/, Playwright chromium available.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="${PYTHON:-python3}"
[ -x "$ROOT/backend/.venv/bin/python" ] && PY="$ROOT/backend/.venv/bin/python"
DATA="$(mktemp -d)"
PIDS=()
# each service runs in its own process group so cleanup also stops grandchildren (npx -> next-server, uvicorn workers)
cleanup() { for p in "${PIDS[@]}"; do kill -- "-$p" 2>/dev/null || kill "$p" 2>/dev/null || true; done; rm -rf "$DATA"; }
trap cleanup EXIT

for port in 8000 9100 3000; do
  if curl -s -o /dev/null "http://127.0.0.1:$port/"; then echo "port $port is already in use; stop the process using it first" >&2; exit 1; fi
done

"$PY" "$ROOT/scripts/make_sample_zips.py"

(cd "$ROOT/frontend" && npm run build >/dev/null)
setsid bash -c "cd '$ROOT/backend' && CONTEXTFORGE_DATA_DIR='$DATA' exec '$PY' -m uvicorn app.main:app --host 127.0.0.1 --port 8000" >"$DATA/api.log" 2>&1 & PIDS+=($!)
setsid bash -c "cd '$ROOT/backend' && exec '$PY' -m tests.fake_llm_server --port 9100" >"$DATA/llm.log" 2>&1 & PIDS+=($!)
setsid bash -c "cd '$ROOT/frontend' && CONTEXTFORGE_PUBLIC_API_URL=http://127.0.0.1:8000 exec npx next start --port 3000" >"$DATA/web.log" 2>&1 & PIDS+=($!)

for i in $(seq 1 180); do
  if curl -sf http://127.0.0.1:8000/api/health >/dev/null && curl -sf -o /dev/null http://127.0.0.1:3000/ && curl -sf -o /dev/null http://127.0.0.1:9100/v1/models; then break; fi
  sleep 1
done

(cd "$ROOT/frontend" && npx playwright test --trace off)
