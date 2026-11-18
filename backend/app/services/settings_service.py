"""Server-side settings: provider configuration, encrypted API keys, analysis preferences.

API keys are never returned to clients. Keys come from environment variables
(preferred) or are stored encrypted (Fernet) in SQLite.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from app.core.config import DEFAULT_EXCLUSIONS, Settings
from app.core.crypto import decrypt, encrypt
from app.db.database import Database
from app.services.ai.providers.base import ProviderConfig
from app.services.ai.providers.registry import PROVIDER_INFO

PROVIDERS = ["none", "anthropic", "openai", "gemini", "openai_compatible"]


class ProviderSettings(BaseModel):
    provider: str = "none"
    model: str | None = None
    base_url: str | None = None
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=16000, ge=256, le=128000)
    timeout_s: float = Field(default=180.0, ge=10, le=1800)
    retries: int = Field(default=3, ge=0, le=10)

    @field_validator("provider")
    @classmethod
    def _known(cls, v: str) -> str:
        if v not in PROVIDERS:
            raise ValueError(f"provider must be one of {PROVIDERS}")
        return v

    @field_validator("base_url")
    @classmethod
    def _url(cls, v: str | None) -> str | None:
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not v.startswith(("https://", "http://")):
            raise ValueError("base_url must start with http:// or https://")
        return v.rstrip("/")


class AnalysisPreferences(BaseModel):
    depth: str = "standard"
    token_budget: int = Field(default=400_000, ge=5_000, le=20_000_000)
    max_file_kb: int = Field(default=1024, ge=16, le=20_480)
    max_concurrency: int = Field(default=4, ge=1, le=16)
    exclusions: list[str] = Field(default_factory=lambda: list(DEFAULT_EXCLUSIONS))
    send_source_to_ai: bool = True
    cache_ai_responses: bool = True
    keep_uploaded_archive: bool = False

    @field_validator("depth")
    @classmethod
    def _depth(cls, v: str) -> str:
        if v not in ("quick", "standard", "deep"):
            raise ValueError("depth must be quick, standard or deep")
        return v

    @field_validator("exclusions")
    @classmethod
    def _excl(cls, v: list[str]) -> list[str]:
        out = []
        for p in v:
            p = p.strip()
            if p and len(p) < 200 and p not in out:
                out.append(p)
        return out[:200]


OFFICIAL_PROVIDERS = {"openai", "anthropic", "gemini"}

ENV_KEY = {"openai": "openai_api_key", "anthropic": "anthropic_api_key", "gemini": "gemini_api_key", "openai_compatible": "custom_api_key"}


class SettingsService:
    def __init__(self, db: Database, settings: Settings) -> None:
        self.db = db
        self.settings = settings

    # ----------------------------------------------------------- provider
    def provider_settings(self) -> ProviderSettings:
        raw = self.db.get_setting("provider")
        if raw:
            return ProviderSettings.model_validate(raw)
        ps = ProviderSettings(provider=self.settings.default_provider if self.settings.default_provider in PROVIDERS else "none", model=self.settings.default_model)
        if ps.provider == "openai_compatible" and self.settings.custom_base_url:
            ps.base_url = self.settings.custom_base_url
        return ps

    def check_base_url(self, provider: str, base_url: str | None) -> None:
        if base_url and provider in OFFICIAL_PROVIDERS and not self.settings.allow_provider_base_url_override:
            raise ValueError("Base URL overrides for official providers are disabled because they would send the provider API key to that URL. "
                             "Set CONTEXTFORGE_ALLOW_PROVIDER_BASE_URL_OVERRIDE=true on the server to allow gateways/proxies.")

    def save_provider_settings(self, ps: ProviderSettings) -> None:
        self.check_base_url(ps.provider, ps.base_url)
        self.db.set_setting("provider", ps.model_dump())

    def _stored_keys(self) -> dict[str, str]:
        return self.db.get_setting("api_keys") or {}

    def set_api_key(self, provider: str, key: str | None) -> None:
        keys = self._stored_keys()
        if key:
            keys[provider] = encrypt(key.strip())
        else:
            keys.pop(provider, None)
        self.db.set_setting("api_keys", keys)

    def api_key(self, provider: str) -> tuple[str | None, str | None]:
        """Return (key, source) where source is 'environment' | 'stored' | None."""
        env_attr = ENV_KEY.get(provider)
        if env_attr and (v := getattr(self.settings, env_attr, None)):
            return v, "environment"
        enc = self._stored_keys().get(provider)
        if enc:
            dec = decrypt(enc)
            if dec:
                return dec, "stored"
        return None, None

    def key_status(self) -> dict[str, dict[str, Any]]:
        out = {}
        for p in PROVIDERS:
            if p == "none":
                continue
            _k, src = self.api_key(p)
            out[p] = {"api_key_set": src is not None, "source": src}
        return out

    def provider_config(self, override: dict[str, Any] | None = None, depth: str = "standard") -> ProviderConfig | None:
        ps = self.provider_settings()
        if override:
            base = ps.model_dump()
            if override.get("provider") and override["provider"] != ps.provider:
                # switching provider for one analysis: don't carry over another provider's model/base URL
                base["model"], base["base_url"] = None, None
            ps = ProviderSettings.model_validate({**base, **{k: v for k, v in override.items() if v is not None}})
        if ps.provider == "none":
            return None
        key, _src = self.api_key(ps.provider)
        base_url = ps.base_url
        if ps.provider in OFFICIAL_PROVIDERS and not self.settings.allow_provider_base_url_override:
            base_url = None
        if ps.provider == "openai_compatible" and not base_url:
            base_url = self.settings.custom_base_url
        effort = {"quick": "low", "standard": "medium", "deep": "high"}.get(depth, "medium")
        return ProviderConfig(provider=ps.provider, model=ps.model or str(PROVIDER_INFO.get(ps.provider, {}).get("default_model") or ""),
                              api_key=key, base_url=base_url, temperature=ps.temperature, max_output_tokens=ps.max_output_tokens,
                              timeout_s=ps.timeout_s, retries=ps.retries, effort=effort)

    # ----------------------------------------------------------- analysis prefs
    def analysis_preferences(self) -> AnalysisPreferences:
        raw = self.db.get_setting("analysis")
        if raw:
            return AnalysisPreferences.model_validate(raw)
        return AnalysisPreferences(token_budget=self.settings.default_token_budget, max_file_kb=self.settings.max_parse_file_kb,
                                   max_concurrency=self.settings.max_concurrent_ai_requests)

    def save_analysis_preferences(self, ap: AnalysisPreferences) -> None:
        self.db.set_setting("analysis", ap.model_dump())

    def public_view(self) -> dict[str, Any]:
        return {
            "provider": self.provider_settings().model_dump(),
            "keys": self.key_status(),
            "analysis": self.analysis_preferences().model_dump(),
            "providers": PROVIDER_INFO,
            "default_exclusions": DEFAULT_EXCLUSIONS,
            "allow_provider_base_url_override": self.settings.allow_provider_base_url_override,
            "limits": {
                "max_upload_mb": self.settings.max_upload_mb, "max_extracted_mb": self.settings.max_extracted_mb,
                "max_file_count": self.settings.max_file_count, "max_single_file_mb": self.settings.max_single_file_mb,
            },
        }
