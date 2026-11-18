"""Optional: run against a REAL provider. Skipped unless credentials are supplied.

    CONTEXTFORGE_LIVE_PROVIDER=anthropic ANTHROPIC_API_KEY=... pytest -m live_provider
    CONTEXTFORGE_LIVE_PROVIDER=openai OPENAI_API_KEY=... CONTEXTFORGE_LIVE_MODEL=gpt-4.1-mini pytest -m live_provider
"""

import json
import os

import pytest

from app.services.ai.providers.base import LLMRequest, ProviderConfig
from app.services.ai.providers.registry import build_provider

PROVIDER = os.environ.get("CONTEXTFORGE_LIVE_PROVIDER")
KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY", "openai_compatible": "CUSTOM_LLM_API_KEY"}

pytestmark = [pytest.mark.live_provider, pytest.mark.skipif(not PROVIDER, reason="set CONTEXTFORGE_LIVE_PROVIDER to run live provider tests")]


@pytest.mark.asyncio
async def test_live_json_roundtrip():
    assert PROVIDER is not None
    cfg = ProviderConfig(provider=PROVIDER, model=os.environ.get("CONTEXTFORGE_LIVE_MODEL", ""), api_key=os.environ.get(KEYS.get(PROVIDER, ""), None),
                         base_url=os.environ.get("CUSTOM_LLM_BASE_URL"), max_output_tokens=2048, effort="low")
    p = build_provider(cfg)
    try:
        resp = await p.complete(LLMRequest(system="Reply with JSON only.", prompt='Return exactly: {"ok": true, "n": 2}', max_output_tokens=2048))
    finally:
        await p.aclose()
    data = json.loads(resp.text.strip().removeprefix("```json").removesuffix("```").strip())
    assert data.get("ok") is True
