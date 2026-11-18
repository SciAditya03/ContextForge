"""Settings API: provider configuration, API keys (write-only), analysis preferences."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import get_settings_service
from app.services.ai.orchestrator import _parse_json
from app.services.ai.providers.base import LLMRequest, ProviderError
from app.services.ai.providers.registry import build_provider
from app.services.settings_service import PROVIDERS, AnalysisPreferences, ProviderSettings, SettingsService

router = APIRouter(prefix="/api/settings", tags=["settings"])


class ApiKeyBody(BaseModel):
    api_key: str = Field(min_length=8, max_length=512)


class TestBody(BaseModel):
    provider: str | None = None
    model: str | None = None
    base_url: str | None = None


@router.get("")
def read_settings(svc: SettingsService = Depends(get_settings_service)) -> dict[str, Any]:
    return svc.public_view()


@router.put("/provider")
def update_provider(body: ProviderSettings, svc: SettingsService = Depends(get_settings_service)) -> dict[str, Any]:
    try:
        svc.save_provider_settings(body)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return svc.public_view()


@router.put("/analysis")
def update_analysis(body: AnalysisPreferences, svc: SettingsService = Depends(get_settings_service)) -> dict[str, Any]:
    svc.save_analysis_preferences(body)
    return svc.public_view()


@router.put("/keys/{provider}")
def set_key(provider: str, body: ApiKeyBody, svc: SettingsService = Depends(get_settings_service)) -> dict[str, Any]:
    if provider not in PROVIDERS or provider == "none":
        raise HTTPException(status_code=400, detail="Unknown provider")
    svc.set_api_key(provider, body.api_key)
    return {"provider": provider, **svc.key_status()[provider]}  # never echoes the key


@router.delete("/keys/{provider}")
def delete_key(provider: str, svc: SettingsService = Depends(get_settings_service)) -> dict[str, Any]:
    if provider not in PROVIDERS or provider == "none":
        raise HTTPException(status_code=400, detail="Unknown provider")
    svc.set_api_key(provider, None)
    return {"provider": provider, **svc.key_status()[provider]}


def _config_for(svc: SettingsService, body: TestBody):  # type: ignore[no-untyped-def]
    override = {k: v for k, v in body.model_dump().items() if v}
    try:
        svc.check_base_url(body.provider or svc.provider_settings().provider, body.base_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    cfg = svc.provider_config(override)
    if cfg is None:
        raise HTTPException(status_code=400, detail="Provider is 'none' — nothing to test")
    cfg.retries = 0
    cfg.timeout_s = min(cfg.timeout_s, 60)
    return cfg


@router.post("/test")
async def test_provider(body: TestBody, svc: SettingsService = Depends(get_settings_service)) -> dict[str, Any]:
    """Send one tiny real request to the configured provider and report the outcome."""
    cfg = _config_for(svc, body)
    started = time.monotonic()
    try:
        provider = build_provider(cfg)
    except ProviderError as exc:
        return {"ok": False, "provider": cfg.provider, "model": cfg.model, "error": str(exc)}
    try:
        resp = await provider.complete(LLMRequest(system="You are a connectivity check. Reply with JSON only.",
                                                  prompt='Return exactly this JSON object: {"ok": true}', max_output_tokens=1024, stage="test"))
        parsed = _parse_json(resp.text)
        return {"ok": bool(parsed and parsed.get("ok") is True), "provider": cfg.provider, "model": resp.model,
                "latency_ms": int((time.monotonic() - started) * 1000), "input_tokens": resp.input_tokens, "output_tokens": resp.output_tokens,
                "reply_preview": resp.text[:120]}
    except ProviderError as exc:
        return {"ok": False, "provider": cfg.provider, "model": cfg.model, "error": str(exc), "status": exc.status}
    finally:
        await provider.aclose()


@router.post("/models")
async def list_models(body: TestBody, svc: SettingsService = Depends(get_settings_service)) -> dict[str, Any]:
    cfg = _config_for(svc, body)
    try:
        provider = build_provider(cfg)
    except ProviderError as exc:
        return {"ok": False, "models": [], "error": str(exc)}
    try:
        return {"ok": True, "models": await provider.list_models()}
    except ProviderError as exc:
        return {"ok": False, "models": [], "error": str(exc)}
    finally:
        await provider.aclose()
