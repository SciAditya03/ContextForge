"""Standalone fake OpenAI-compatible server for local UI testing without paid API access.

    python -m tests.fake_llm_server --port 9100
Then set provider "openai_compatible" with base URL http://127.0.0.1:9100/v1 in Settings.
Responses are deterministic placeholders (see tests/conftest.py::fake_llm_reply) — never present them as real AI output.
"""

import argparse
import asyncio
import json
import os

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from tests.conftest import fake_llm_reply

app = FastAPI()


@app.post("/v1/chat/completions")
async def chat(request: Request) -> JSONResponse:
    body = await request.json()
    await asyncio.sleep(float(os.environ.get("FAKE_LLM_DELAY", "0")))  # simulate model latency for UI testing
    prompt = body["messages"][-1]["content"]
    content = json.dumps(fake_llm_reply(prompt))
    return JSONResponse({"id": "fake", "model": body.get("model", "fake"), "choices": [{"index": 0, "message": {"role": "assistant", "content": content}, "finish_reason": "stop"}],
                         "usage": {"prompt_tokens": len(prompt) // 4, "completion_tokens": len(content) // 4}})


@app.get("/v1/models")
async def models() -> dict:  # type: ignore[type-arg]
    return {"data": [{"id": "fake-local-model"}]}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9100)
    uvicorn.run(app, host="127.0.0.1", port=ap.parse_args().port, log_level="warning")
