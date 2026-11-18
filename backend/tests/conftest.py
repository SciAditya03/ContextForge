"""Shared fixtures: isolated settings, sample archives, fake LLM providers and a fake OpenAI-compatible server."""

from __future__ import annotations

import json
import re
import socket
import threading
import time
import zipfile
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "samples"


@pytest.fixture(autouse=True)
def isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Every test gets its own data directory and no provider keys from the host environment."""
    data = tmp_path / "data"
    monkeypatch.setenv("CONTEXTFORGE_DATA_DIR", str(data))
    for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "CUSTOM_LLM_API_KEY", "CUSTOM_LLM_BASE_URL", "CONTEXTFORGE_API_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    from app.core.config import get_settings

    get_settings.cache_clear()
    yield data
    get_settings.cache_clear()


def make_zip(src: Path, dest: Path, prefix: str | None = None) -> Path:
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(src.rglob("*")):
            if p.is_file():
                rel = p.relative_to(src).as_posix()
                zf.write(p, f"{prefix}/{rel}" if prefix else rel)
    return dest


@pytest.fixture
def sample_zip(tmp_path: Path):  # type: ignore[no-untyped-def]
    def _make(name: str) -> Path:
        return make_zip(SAMPLES / name, tmp_path / f"{name}.zip", prefix=name)

    return _make


# ----------------------------------------------------------------------------- fake LLM
def _files_in_prompt(prompt: str) -> list[tuple[str, int]]:
    return [(m.group(1), int(m.group(2))) for m in re.finditer(r"=== FILE: (\S+) \([^,]+, (\d+) lines", prompt)]


def _paths_in_json(prompt: str) -> list[str]:
    return sorted(set(re.findall(r'"(?:file|path)":"([^":]+?\.[A-Za-z]{1,5})(?::\d+(?:-\d+)?)?"', prompt)))


def fake_llm_reply(prompt: str) -> dict[str, Any]:
    """Deterministic, schema-correct replies that cite real files (plus one bogus reference to exercise validation)."""
    if "TASK: File-level analysis" in prompt:
        files = _files_in_prompt(prompt)
        return {"files": [{"path": p, "purpose": f"Implements logic in {p.rsplit('/', 1)[-1]}.", "responsibilities": ["primary responsibility"],
                           "key_symbols": [], "notes": ["note"],
                           "claims": [{"text": f"{p} defines its main behaviour near the top.", "sources": [{"file": p, "line_start": 1, "line_end": min(3, n)}], "confidence": 0.8},
                                      {"text": "This references a file that does not exist.", "sources": [{"file": "does/not/exist.py", "line_start": 1, "line_end": 2}], "confidence": 0.9}]}
                          for p, n in files]}
    if "TASK: Module-level analysis" in prompt:
        mods = re.findall(r'"module":"([^"]+)"', prompt)
        return {"modules": [{"module": m, "purpose": f"Module {m}", "responsibilities": ["r1"], "interactions": ["uses other modules"]} for m in dict.fromkeys(mods)]}
    paths = _paths_in_json(prompt) or ["README.md"]
    p0 = paths[0]
    claim = {"text": f"Requests enter through `{p0}`.", "sources": [{"file": p0, "line_start": 1, "line_end": 2}], "confidence": 0.7}
    if "TASK: Cross-module" in prompt:
        return {"module_interactions": [claim], "frontend_backend": [claim], "data_flow": [claim], "integrations": []}
    if "TASK: System-level synthesis" in prompt:
        return {"purpose": claim, "executive_summary": [claim], "architecture": [claim], "authentication": [claim], "architectural_decisions": [],
                "technical_debt": [], "debugging_entry_points": [claim], "open_questions": ["What is the deployment target?"]}
    if "TASK: Business-logic" in prompt:
        return {"business_logic": [claim], "core_functionality": [claim],
                "workflows": [{"name": "Main request", "trigger": "HTTP request", "handler": p0, "steps": [f"{p0}:1"], "input_data": "JSON",
                               "transformations": "validation", "output": "JSON", "dependencies": [], "errors": ["404"],
                               "sources": [{"file": p0, "line_start": 1, "line_end": 2}]}],
                "potential_issues": [{"title": "AI-suspected issue", "severity": "medium", "category": "logic", "file": p0, "line_start": 1, "line_end": 1,
                                      "explanation": "explanation", "evidence": "evidence", "impact": "impact", "suggestion": "fix", "confidence": 0.5},
                                     {"title": "Issue without location", "severity": "high", "file": "ghost.py", "line_start": 3}]}
    if "connectivity check" in prompt or '{"ok": true}' in prompt:
        return {"ok": True}
    return {}


class FakeProvider:
    """In-process provider implementing the LLMProvider interface."""

    name = "fake"

    def __init__(self, fail_times: int = 0, retryable: bool = True, reply=fake_llm_reply) -> None:  # type: ignore[no-untyped-def]
        from app.services.ai.providers.base import ProviderConfig

        self.config = ProviderConfig(provider="fake", model="fake-1", api_key="test", retries=2)
        self.prompts: list[str] = []
        self.fail_times = fail_times
        self.retryable = retryable
        self.reply = reply

    async def complete(self, req):  # type: ignore[no-untyped-def]
        from app.services.ai.providers.base import LLMResponse, ProviderError

        self.prompts.append(req.prompt)
        if self.fail_times > 0:
            self.fail_times -= 1
            raise ProviderError("temporary failure", retryable=self.retryable, status=503 if self.retryable else 400, retry_after=0)
        text = json.dumps(self.reply(req.prompt))
        return LLMResponse(text=text, model="fake-1", input_tokens=len(req.prompt) // 4, output_tokens=len(text) // 4, finish_reason="stop")

    async def list_models(self) -> list[str]:
        return ["fake-1"]

    async def aclose(self) -> None:
        pass


# ----------------------------------------------------------------------------- fake OpenAI-compatible HTTP server
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.fixture(scope="session")
def fake_openai_server() -> Iterator[dict[str, Any]]:
    """A real HTTP server speaking the OpenAI Chat Completions protocol (used for provider + end-to-end tests)."""
    import uvicorn

    app = FastAPI()
    state: dict[str, Any] = {"requests": [], "auth": []}

    @app.post("/v1/chat/completions")
    async def chat(request: Request):  # type: ignore[no-untyped-def]
        body = await request.json()
        state["requests"].append(body)
        state["auth"].append(request.headers.get("authorization"))
        prompt = body["messages"][-1]["content"]
        content = json.dumps(fake_llm_reply(prompt))
        return JSONResponse({"id": "x", "model": body["model"], "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                             "usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": len(content) // 4}})

    @app.get("/v1/models")
    async def models():  # type: ignore[no-untyped-def]
        return {"data": [{"id": "fake-model-a"}, {"id": "fake-model-b"}]}

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield {"base_url": f"http://127.0.0.1:{port}/v1", "state": state}
    server.should_exit = True
    t.join(timeout=5)


@pytest.fixture(scope="session")
def fake_anthropic_server() -> Iterator[dict[str, Any]]:
    """A real HTTP server speaking the Anthropic Messages streaming (SSE) protocol."""
    import uvicorn

    app = FastAPI()
    state: dict[str, Any] = {"requests": [], "headers": [], "mode": "ok"}

    def sse(event: str, data: dict[str, Any]) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    @app.post("/v1/messages")
    async def messages(request: Request):  # type: ignore[no-untyped-def]
        body = await request.json()
        state["requests"].append(body)
        state["headers"].append(dict(request.headers))
        mode = state["mode"]
        if mode == "rate_limit":
            return JSONResponse({"type": "error", "error": {"type": "rate_limit_error", "message": "slow down"}}, status_code=429, headers={"retry-after": "1"})
        if mode == "auth":
            return JSONResponse({"type": "error", "error": {"type": "authentication_error", "message": "bad key"}}, status_code=401)
        text = json.dumps(fake_llm_reply(body["messages"][-1]["content"]))
        stop = "refusal" if mode == "refusal" else "end_turn"

        def gen():  # type: ignore[no-untyped-def]
            yield sse("message_start", {"type": "message_start", "message": {"id": "msg_1", "type": "message", "role": "assistant", "model": body["model"],
                                                                         "content": [], "stop_reason": None, "stop_sequence": None,
                                                                         "usage": {"input_tokens": 42, "output_tokens": 1}}})
            yield sse("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}})
            for i in range(0, len(text), 50):
                yield sse("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text[i : i + 50]}})
            yield sse("content_block_stop", {"type": "content_block_stop", "index": 0})
            yield sse("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop, "stop_sequence": None}, "usage": {"output_tokens": 17}})
            yield sse("message_stop", {"type": "message_stop"})

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/v1/models")
    async def models():  # type: ignore[no-untyped-def]
        return {"data": [{"id": "claude-opus-5-5", "type": "model", "display_name": "Claude Opus 5.5", "created_at": "2026-01-01T00:00:00Z"}],
                "has_more": False, "first_id": "claude-opus-5-5", "last_id": "claude-opus-5-5"}

    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    yield {"base_url": f"http://127.0.0.1:{port}", "state": state}
    server.should_exit = True
    t.join(timeout=5)
