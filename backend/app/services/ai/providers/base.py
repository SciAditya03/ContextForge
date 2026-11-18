"""Provider-independent LLM interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class ProviderConfig:
    provider: str  # openai | anthropic | gemini | openai_compatible | none
    model: str
    api_key: str | None = None
    base_url: str | None = None
    temperature: float = 0.2
    max_output_tokens: int = 16000
    timeout_s: float = 180.0
    retries: int = 3
    effort: str | None = None  # low | medium | high (mapped per provider where supported)


@dataclass
class LLMRequest:
    system: str
    prompt: str
    json_mode: bool = True
    max_output_tokens: int | None = None
    stage: str = ""


@dataclass
class LLMResponse:
    text: str
    model: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    finish_reason: str | None = None
    raw_meta: dict[str, object] = field(default_factory=dict)


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status
        self.retry_after = retry_after


class LLMProvider(ABC):
    name: str = "base"

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    @abstractmethod
    async def complete(self, req: LLMRequest) -> LLMResponse: ...

    async def list_models(self) -> list[str]:
        return []

    async def aclose(self) -> None:  # noqa: B027 - optional hook
        pass


def classify_http_status(status: int) -> bool:
    """Return True when an HTTP status is worth retrying."""
    return status in (408, 409, 425, 429) or status >= 500


def parse_retry_after(value: str | None) -> float | None:
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None
