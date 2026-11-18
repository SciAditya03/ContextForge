"""Application configuration loaded from environment variables."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_EXCLUSIONS: list[str] = [
    ".git/",
    "node_modules/",
    ".venv/",
    "venv/",
    "env/",
    "dist/",
    "build/",
    ".next/",
    "out/",
    "coverage/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".tox/",
    "vendor/",
    "target/",
    ".idea/",
    ".vscode/",
    ".gradle/",
    ".terraform/",
    "*.min.js",
    "*.map",
    ".DS_Store",
]

ANALYSIS_VERSION = "1.0.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CONTEXTFORGE_", env_file=".env", extra="ignore")

    data_dir: Path = Field(default=Path("./data"))
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    secret_key: str | None = None  # Fernet key used to encrypt API keys stored in SQLite
    log_level: str = "INFO"
    api_token: str | None = None  # optional shared secret required on /api/* (Authorization: Bearer <token>)
    # Base-URL overrides for official providers (OpenAI/Anthropic/Gemini) would send their API keys to that URL,
    # so they are opt-in. OpenAI-compatible endpoints always take a base URL (with their own key).
    allow_provider_base_url_override: bool = False

    # ZIP limits
    max_upload_mb: int = 200
    max_extracted_mb: int = 1024
    max_file_count: int = 50_000
    max_single_file_mb: int = 50
    max_compression_ratio: int = 200
    extraction_timeout_s: int = 120

    # Analysis limits
    max_parse_file_kb: int = 1024
    max_concurrent_ai_requests: int = 4
    default_token_budget: int = 400_000
    keep_extracted_sources: bool = False

    # Default provider (may be overridden by UI settings)
    default_provider: str = "none"
    default_model: str | None = None

    # Provider keys from the environment (never sent to the frontend)
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    gemini_api_key: str | None = Field(default=None, validation_alias="GEMINI_API_KEY")
    custom_api_key: str | None = Field(default=None, validation_alias="CUSTOM_LLM_API_KEY")
    custom_base_url: str | None = Field(default=None, validation_alias="CUSTOM_LLM_BASE_URL")

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def projects_dir(self) -> Path:
        return self.data_dir / "projects"

    @property
    def cache_dir(self) -> Path:
        return self.data_dir / "cache"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "contextforge.db"

    def ensure_dirs(self) -> None:
        for d in (self.data_dir, self.projects_dir, self.cache_dir):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s
