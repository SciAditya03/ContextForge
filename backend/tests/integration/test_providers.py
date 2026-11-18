"""Provider adapters exercised over real HTTP against protocol-faithful fake servers (no paid API needed)."""

import json

import httpx
import pytest

from app.services.ai.providers.base import LLMRequest, ProviderConfig, ProviderError
from app.services.ai.providers.registry import PROVIDER_INFO, build_provider, register_provider

REQ = LLMRequest(system="sys", prompt='Return exactly this JSON object: {"ok": true}', max_output_tokens=512)


@pytest.mark.asyncio
async def test_openai_compatible_roundtrip(fake_openai_server):
    cfg = ProviderConfig(provider="openai_compatible", model="local-model", api_key="k-test", base_url=fake_openai_server["base_url"], temperature=0.1)
    p = build_provider(cfg)
    resp = await p.complete(REQ)
    await p.aclose()
    assert json.loads(resp.text) == {"ok": True} and resp.input_tokens and resp.model == "local-model"
    body = fake_openai_server["state"]["requests"][-1]
    assert body["max_tokens"] == 512 and body["temperature"] == 0.1 and body["response_format"] == {"type": "json_object"}
    assert fake_openai_server["state"]["auth"][-1] == "Bearer k-test"
    p2 = build_provider(cfg)
    assert await p2.list_models() == ["fake-model-a", "fake-model-b"]
    await p2.aclose()


@pytest.mark.asyncio
async def test_openai_official_uses_max_completion_tokens(fake_openai_server):
    p = build_provider(ProviderConfig(provider="openai", model="gpt-test", api_key="k", base_url=fake_openai_server["base_url"]))
    await p.complete(REQ)
    await p.aclose()
    body = fake_openai_server["state"]["requests"][-1]
    assert "max_completion_tokens" in body and "max_tokens" not in body


@pytest.mark.asyncio
async def test_anthropic_streaming_request_shape(fake_anthropic_server):
    st = fake_anthropic_server["state"]
    st["mode"] = "ok"
    cfg = ProviderConfig(provider="anthropic", model="", api_key="sk-ant-test-key-000000000000", base_url=fake_anthropic_server["base_url"], effort="high")
    p = build_provider(cfg)
    assert cfg.model == "claude-opus-5-5"  # default model
    resp = await p.complete(REQ)
    await p.aclose()
    assert json.loads(resp.text) == {"ok": True}
    assert resp.input_tokens == 42 and resp.output_tokens == 17 and resp.finish_reason == "end_turn"
    body, headers = st["requests"][-1], st["headers"][-1]
    assert body["model"] == "claude-opus-5-5" and body["stream"] is True
    assert "temperature" not in body and "thinking" not in body
    assert body["output_config"] == {"effort": "high"}
    assert body["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in headers.get("anthropic-beta", "")
    # the SDK chooses the auth header (x-api-key or Authorization: Bearer depending on version)
    assert "sk-ant-test-key-000000000000" in (headers.get("x-api-key", "") + headers.get("authorization", ""))


@pytest.mark.asyncio
async def test_anthropic_error_mapping(fake_anthropic_server):
    st = fake_anthropic_server["state"]
    cfg = ProviderConfig(provider="anthropic", model="claude-opus-5-5", api_key="sk-ant-x-000000000000000000", base_url=fake_anthropic_server["base_url"])
    for mode, retryable, status in (("rate_limit", True, 429), ("auth", False, 401), ("refusal", False, None)):
        st["mode"] = mode
        p = build_provider(cfg)
        with pytest.raises(ProviderError) as ei:
            await p.complete(REQ)
        await p.aclose()
        assert ei.value.retryable is retryable and ei.value.status == status, mode
        if mode == "rate_limit":
            assert ei.value.retry_after == 1.0
    st["mode"] = "ok"


@pytest.mark.asyncio
async def test_gemini_request_shape_and_key_in_header():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"], seen["headers"], seen["body"] = str(request.url), dict(request.headers), json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": '{"ok": true}'}]}, "finishReason": "STOP"}],
                                         "usageMetadata": {"promptTokenCount": 9, "candidatesTokenCount": 3}})

    p = build_provider(ProviderConfig(provider="gemini", model="gemini-test", api_key="AIza-test-key"))
    p.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))  # type: ignore[attr-defined]
    resp = await p.complete(REQ)
    await p.aclose()
    assert json.loads(resp.text) == {"ok": True} and resp.input_tokens == 9
    assert seen["url"].endswith("/models/gemini-test:generateContent") and "key=" not in seen["url"]
    assert seen["headers"]["x-goog-api-key"] == "AIza-test-key"
    assert seen["body"]["generationConfig"]["responseMimeType"] == "application/json"
    assert seen["body"]["systemInstruction"]["parts"][0]["text"] == "sys"


@pytest.mark.asyncio
async def test_gemini_safety_block_is_error():
    p = build_provider(ProviderConfig(provider="gemini", model="m", api_key="k"))
    p.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"candidates": [{"finishReason": "SAFETY"}]})))  # type: ignore[attr-defined]
    with pytest.raises(ProviderError, match="SAFETY"):
        await p.complete(REQ)
    await p.aclose()


@pytest.mark.asyncio
async def test_http_status_mapping():
    p = build_provider(ProviderConfig(provider="openai", model="m", api_key="k"))
    p.http = httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(503, json={"error": {"message": "overloaded"}}, headers={"retry-after": "2"})))  # type: ignore[attr-defined]
    with pytest.raises(ProviderError) as ei:
        await p.complete(REQ)
    await p.aclose()
    assert ei.value.retryable and ei.value.retry_after == 2.0 and "overloaded" in str(ei.value)


def test_missing_key_and_unknown_provider():
    with pytest.raises(ProviderError, match="key"):
        build_provider(ProviderConfig(provider="openai", model="m"))
    with pytest.raises(ProviderError, match="base URL"):
        build_provider(ProviderConfig(provider="openai_compatible", model="m"))
    with pytest.raises(ProviderError, match="Unknown provider"):
        build_provider(ProviderConfig(provider="nope", model="m"))


def test_registering_a_new_provider():
    class Echo:
        def __init__(self, c):  # type: ignore[no-untyped-def]
            self.config = c

    register_provider("echo", lambda c: Echo(c), {"label": "Echo", "default_model": "e1"})  # type: ignore[arg-type,return-value]
    p = build_provider(ProviderConfig(provider="echo", model=""))
    assert p.config.model == "e1" and PROVIDER_INFO["echo"]["label"] == "Echo"
