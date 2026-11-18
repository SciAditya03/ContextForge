"""OpenAI, OpenAI-compatible and Google Gemini providers over raw HTTPS (httpx)."""

from __future__ import annotations

from typing import Any

import httpx

from app.services.ai.providers.base import (
    LLMProvider,
    LLMRequest,
    LLMResponse,
    ProviderConfig,
    ProviderError,
    classify_http_status,
    parse_retry_after,
)

OPENAI_BASE = "https://api.openai.com/v1"
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


def _error_text(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        err = data.get("error", data)
        if isinstance(err, dict):
            return str(err.get("message") or err)[:300]
        return str(err)[:300]
    except ValueError:
        return resp.text[:300]


class _HTTPProvider(LLMProvider):
    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        self.http = httpx.AsyncClient(timeout=httpx.Timeout(config.timeout_s, connect=15.0))

    async def _post(self, url: str, headers: dict[str, str], body: dict[str, Any]) -> dict[str, Any]:
        try:
            resp = await self.http.post(url, headers=headers, json=body)
        except httpx.TimeoutException as exc:
            raise ProviderError(f"{self.name} request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not connect to {self.name}: {type(exc).__name__}", retryable=True) from exc
        if resp.status_code >= 400:
            raise ProviderError(
                f"{self.name} API error {resp.status_code}: {_error_text(resp)}",
                retryable=classify_http_status(resp.status_code),
                status=resp.status_code,
                retry_after=parse_retry_after(resp.headers.get("retry-after")),
            )
        try:
            return resp.json()  # type: ignore[no-any-return]
        except ValueError as exc:
            raise ProviderError(f"{self.name} returned non-JSON response", retryable=True) from exc

    async def aclose(self) -> None:
        await self.http.aclose()


class OpenAIProvider(_HTTPProvider):
    """OpenAI Chat Completions. Also used (with ``compatible=True``) for custom endpoints."""

    name = "openai"

    def __init__(self, config: ProviderConfig, compatible: bool = False) -> None:
        super().__init__(config)
        self.compatible = compatible
        if compatible:
            self.name = "openai_compatible"
            if not config.base_url:
                raise ProviderError("A base URL is required for OpenAI-compatible endpoints")
        elif not config.api_key:
            raise ProviderError("OpenAI API key is not configured")
        self.base = (config.base_url or OPENAI_BASE).rstrip("/")
        self._send_temperature = True
        self._send_json_format = True

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.config.api_key:
            h["Authorization"] = f"Bearer {self.config.api_key}"
        return h

    async def complete(self, req: LLMRequest) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self.config.model,
            "messages": [{"role": "system", "content": req.system}, {"role": "user", "content": req.prompt}],
        }
        max_tokens = req.max_output_tokens or self.config.max_output_tokens
        body["max_tokens" if self.compatible else "max_completion_tokens"] = max_tokens
        if self._send_temperature:
            body["temperature"] = self.config.temperature
        if req.json_mode and self._send_json_format:
            body["response_format"] = {"type": "json_object"}
        if not self.compatible and self.config.effort and str(self.config.model).startswith(("o", "gpt-5")):
            body["reasoning_effort"] = self.config.effort
        try:
            data = await self._post(f"{self.base}/chat/completions", self._headers(), body)
        except ProviderError as exc:
            # Some models/servers reject optional parameters; retry once without them.
            msg = str(exc).lower()
            if exc.status == 400 and ("temperature" in msg or "response_format" in msg or "reasoning_effort" in msg):
                if "temperature" in msg:
                    self._send_temperature = False
                    body.pop("temperature", None)
                if "response_format" in msg:
                    self._send_json_format = False
                    body.pop("response_format", None)
                body.pop("reasoning_effort", None)
                data = await self._post(f"{self.base}/chat/completions", self._headers(), body)
            else:
                raise
        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(f"{self.name} returned no choices", retryable=True)
        choice = choices[0]
        msg_obj = choice.get("message", {}) or {}
        if msg_obj.get("refusal"):
            raise ProviderError(f"Model refused: {str(msg_obj.get('refusal'))[:200]}")
        usage = data.get("usage") or {}
        return LLMResponse(
            text=msg_obj.get("content") or "",
            model=str(data.get("model") or self.config.model),
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
            finish_reason=choice.get("finish_reason"),
        )

    async def list_models(self) -> list[str]:
        try:
            resp = await self.http.get(f"{self.base}/models", headers=self._headers())
        except httpx.HTTPError as exc:
            raise ProviderError(f"Could not connect to {self.name}") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"{self.name} API error {resp.status_code}: {_error_text(resp)}", status=resp.status_code)
        return sorted(str(m.get("id")) for m in resp.json().get("data", []))


class GeminiProvider(_HTTPProvider):
    name = "gemini"

    def __init__(self, config: ProviderConfig) -> None:
        super().__init__(config)
        if not config.api_key:
            raise ProviderError("Gemini API key is not configured")
        self.base = (config.base_url or GEMINI_BASE).rstrip("/")

    def _headers(self) -> dict[str, str]:
        # key goes in a header, never in the URL (URLs end up in logs)
        return {"Content-Type": "application/json", "x-goog-api-key": str(self.config.api_key)}

    async def complete(self, req: LLMRequest) -> LLMResponse:
        model = self.config.model.removeprefix("models/")
        gen: dict[str, Any] = {
            "temperature": self.config.temperature,
            "maxOutputTokens": req.max_output_tokens or self.config.max_output_tokens,
        }
        if req.json_mode:
            gen["responseMimeType"] = "application/json"
        body: dict[str, Any] = {
            "systemInstruction": {"parts": [{"text": req.system}]},
            "contents": [{"role": "user", "parts": [{"text": req.prompt}]}],
            "generationConfig": gen,
        }
        data = await self._post(f"{self.base}/models/{model}:generateContent", self._headers(), body)
        cands = data.get("candidates") or []
        if not cands:
            fb = data.get("promptFeedback") or {}
            raise ProviderError(f"Gemini returned no candidates (blockReason={fb.get('blockReason')})")
        cand = cands[0]
        finish = cand.get("finishReason")
        if finish in {"SAFETY", "RECITATION", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII"}:
            raise ProviderError(f"Gemini blocked the response (finishReason={finish})")
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        usage = data.get("usageMetadata") or {}
        return LLMResponse(
            text=text,
            model=model,
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            finish_reason=finish,
        )

    async def list_models(self) -> list[str]:
        try:
            resp = await self.http.get(f"{self.base}/models", headers=self._headers(), params={"pageSize": 200})
        except httpx.HTTPError as exc:
            raise ProviderError("Could not connect to Gemini") from exc
        if resp.status_code >= 400:
            raise ProviderError(f"Gemini API error {resp.status_code}: {_error_text(resp)}", status=resp.status_code)
        out = []
        for m in resp.json().get("models", []):
            if "generateContent" in (m.get("supportedGenerationMethods") or []):
                out.append(str(m.get("name", "")).removeprefix("models/"))
        return sorted(out)
