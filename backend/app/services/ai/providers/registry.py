"""Provider registry. New providers register a factory here; the pipeline never changes."""

from __future__ import annotations

from collections.abc import Callable

from app.services.ai.providers.anthropic_provider import DEFAULT_MODEL as ANTHROPIC_DEFAULT
from app.services.ai.providers.anthropic_provider import AnthropicProvider
from app.services.ai.providers.base import LLMProvider, ProviderConfig, ProviderError
from app.services.ai.providers.http_providers import GeminiProvider, OpenAIProvider

ProviderFactory = Callable[[ProviderConfig], LLMProvider]

_FACTORIES: dict[str, ProviderFactory] = {
    "openai": lambda c: OpenAIProvider(c),
    "openai_compatible": lambda c: OpenAIProvider(c, compatible=True),
    "anthropic": lambda c: AnthropicProvider(c),
    "gemini": lambda c: GeminiProvider(c),
}

PROVIDER_INFO: dict[str, dict[str, object]] = {
    "none": {"label": "Deterministic only (no LLM)", "default_model": None, "needs_key": False, "needs_base_url": False,
             "notes": "Runs every deterministic layer; AI interpretation sections are marked as not generated."},
    "anthropic": {"label": "Anthropic (Claude)", "default_model": ANTHROPIC_DEFAULT, "needs_key": True, "needs_base_url": False,
                  "notes": "Uses the official Anthropic SDK with streaming. Temperature is not sent (current Claude models reject sampling parameters); analysis depth maps to effort."},
    "openai": {"label": "OpenAI", "default_model": "gpt-4.1-mini", "needs_key": True, "needs_base_url": False,
               "notes": "Chat Completions API with JSON response format. Default model is a suggestion; use “List models” to pick one available to your key."},
    "gemini": {"label": "Google Gemini", "default_model": "gemini-2.5-flash", "needs_key": True, "needs_base_url": False,
               "notes": "Gemini generateContent API with JSON MIME type. Default model is a suggestion; use “List models”."},
    "openai_compatible": {"label": "OpenAI-compatible endpoint", "default_model": None, "needs_key": False, "needs_base_url": True,
                          "notes": "Any server implementing /chat/completions (vLLM, Ollama, LM Studio, OpenRouter, Azure-compatible gateways …)."},
}


def register_provider(name: str, factory: ProviderFactory, info: dict[str, object] | None = None) -> None:
    _FACTORIES[name] = factory
    if info:
        PROVIDER_INFO[name] = info


def build_provider(config: ProviderConfig) -> LLMProvider:
    factory = _FACTORIES.get(config.provider)
    if factory is None:
        raise ProviderError(f"Unknown provider '{config.provider}'")
    if not config.model:
        default = PROVIDER_INFO.get(config.provider, {}).get("default_model")
        if not default:
            raise ProviderError(f"A model name is required for provider '{config.provider}'")
        config.model = str(default)
    return factory(config)
