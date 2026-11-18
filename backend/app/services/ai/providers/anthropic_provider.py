"""Anthropic (Claude) provider using the official ``anthropic`` SDK."""

from __future__ import annotations

import re

import anthropic

from app.services.ai.providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderConfig,
    ProviderError,
    parse_retry_after,
)

DEFAULT_MODEL = "claude-opus-5-5"

# Models that accept the server-side refusal fallback (`fallbacks: "default"`).
_FALLBACK_MODELS = {"claude-fable-5-2", "claude-fable-5-1", "claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5"}
_FALLBACK_BETA = "server-side-fallback-2026-07-01"
# Model families that accept output_config.effort.
_EFFORT_MODELS = re.compile(r"^claude-(fable|mythos|opus-5|opus-4-[5-9]|sonnet-5|sonnet-4-6|haiku-5)")


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not config.api_key:
            raise ProviderError("Anthropic API key is not configured", retryable=False)
        # Retries are handled uniformly by the orchestrator (with backoff + budget accounting).
        self.client = anthropic.AsyncAnthropic(
            api_key=config.api_key,
            base_url=config.base_url or None,
            timeout=config.timeout_s,
            max_retries=0,
        )
        self._use_fallbacks = (config.model or DEFAULT_MODEL) in _FALLBACK_MODELS

    async def complete(self, req: LLMRequest) -> LLMResponse:
        model = self.config.model or DEFAULT_MODEL
        params: dict[str, object] = {
            "model": model,
            "max_tokens": req.max_output_tokens or self.config.max_output_tokens,
            "system": req.system,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        # Current Claude models reject sampling parameters (temperature/top_p/top_k), so none are sent.
        # Thinking is adaptive by default on current models; depth is controlled with effort.
        if self.config.effort and _EFFORT_MODELS.match(model):
            params["output_config"] = {"effort": self.config.effort}
        try:
            message = await self._stream(params, with_fallbacks=self._use_fallbacks)
        except anthropic.BadRequestError as exc:
            if self._use_fallbacks and "fallback" in str(exc).lower():
                # e.g. a proxy/base URL that does not support server-side fallbacks
                self._use_fallbacks = False
                message = await self._stream_translated(params, with_fallbacks=False)
            else:
                raise ProviderError(f"Anthropic rejected the request: {_msg(exc)}", retryable=False, status=400) from exc
        except ProviderError:
            raise
        return self._to_response(message, model)

    async def _stream_translated(self, params: dict[str, object], with_fallbacks: bool):  # type: ignore[no-untyped-def]
        try:
            return await self._stream(params, with_fallbacks)
        except anthropic.BadRequestError as exc:
            raise ProviderError(f"Anthropic rejected the request: {_msg(exc)}", retryable=False, status=400) from exc

    async def _stream(self, params: dict[str, object], with_fallbacks: bool):  # type: ignore[no-untyped-def]
        try:
            if with_fallbacks:
                async with self.client.beta.messages.stream(
                    **params, betas=[_FALLBACK_BETA], fallbacks="default"  # type: ignore[arg-type]
                ) as stream:
                    return await stream.get_final_message()
            async with self.client.messages.stream(**params) as stream:  # type: ignore[arg-type]
                return await stream.get_final_message()
        except anthropic.BadRequestError:
            raise
        except anthropic.AuthenticationError as exc:
            raise ProviderError("Anthropic authentication failed (check the API key)", retryable=False, status=401) from exc
        except anthropic.PermissionDeniedError as exc:
            raise ProviderError("Anthropic API key lacks permission for this model", retryable=False, status=403) from exc
        except anthropic.NotFoundError as exc:
            raise ProviderError(f"Anthropic model or endpoint not found: {_msg(exc)}", retryable=False, status=404) from exc
        except anthropic.RateLimitError as exc:
            ra = parse_retry_after(exc.response.headers.get("retry-after") if exc.response is not None else None)
            raise ProviderError("Anthropic rate limit reached", retryable=True, status=429, retry_after=ra) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(f"Anthropic API error {exc.status_code}: {_msg(exc)}", retryable=exc.status_code >= 500, status=exc.status_code) from exc
        except anthropic.APITimeoutError as exc:
            raise ProviderError("Anthropic request timed out", retryable=True) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError("Could not connect to the Anthropic API", retryable=True) from exc

    def _to_response(self, message, model: str) -> LLMResponse:  # type: ignore[no-untyped-def]
        if message.stop_reason == "refusal":
            category = getattr(getattr(message, "stop_details", None), "category", None)
            raise ProviderError(f"Model declined the request (refusal{f': {category}' if category else ''})", retryable=False)
        text = "".join(getattr(b, "text", "") for b in message.content if getattr(b, "type", "") == "text")
        usage = getattr(message, "usage", None)
        return LLMResponse(
            text=text,
            model=getattr(message, "model", model),
            input_tokens=getattr(usage, "input_tokens", None),
            output_tokens=getattr(usage, "output_tokens", None),
            finish_reason=message.stop_reason,
        )

    async def list_models(self) -> list[str]:
        try:
            page = await self.client.models.list(limit=100)
            return [m.id for m in page.data]
        except anthropic.APIError as exc:
            raise ProviderError(f"Could not list Anthropic models: {_msg(exc)}") from exc

    async def aclose(self) -> None:
        await self.client.close()


def _msg(exc: Exception) -> str:
    return str(getattr(exc, "message", None) or exc)[:300]
