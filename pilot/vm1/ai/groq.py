"""Groq adapter (OpenAI-compatible: POST {base}/chat/completions).

Shapes follow Groq's public docs: bearer auth; ``max_completion_tokens`` (``max_tokens`` is
deprecated); ``response_format`` is either ``{"type": "json_object"}`` (all models, no schema
enforcement) or ``{"type": "json_schema", "json_schema": {"name", "strict", "schema"}}``
(only some models support it, so it is opt-in via ``response_mode``). Output is read from
``choices[0].message.content``. Output is always re-validated locally either way.

Groq's docs do not list ``finish_reason`` values; ``"length"`` (the OpenAI-compatible value
for a token-limit cut-off) is treated defensively as a truncated, unusable answer.
"""

from __future__ import annotations

from typing import Any, Mapping

from .errors import AIConfigError, AIResponseError
from .http_provider import HttpJsonProvider, build_messages, normalize_usage
from .request import StructuredRequest
from .transport import HttpTransport

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
RESPONSE_MODES = ("json_object", "json_schema")


class GroqProvider(HttpJsonProvider):
    name = "groq"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        response_mode: str = "json_object",
        strict_schema: bool = False,
        transport: HttpTransport | None = None,
        max_response_bytes: int = 1_000_000,
    ):
        super().__init__(model=model, api_key=api_key, base_url=base_url, transport=transport,
                         max_response_bytes=max_response_bytes)
        if response_mode not in RESPONSE_MODES:
            raise AIConfigError(f"response_mode must be one of {RESPONSE_MODES}")
        if not isinstance(strict_schema, bool):
            raise AIConfigError("strict_schema must be a boolean")
        self.response_mode = response_mode
        self.strict_schema = strict_schema

    def _url(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _payload(self, request: StructuredRequest) -> dict[str, Any]:
        if self.response_mode == "json_schema":
            response_format: dict[str, Any] = {
                "type": "json_schema",
                "json_schema": {"name": "response", "strict": self.strict_schema,
                                "schema": dict(request.schema)},
            }
        else:
            response_format = {"type": "json_object"}
        return {
            "model": self.model,
            "messages": build_messages(request),
            "temperature": request.temperature,
            "max_completion_tokens": request.max_tokens,
            "response_format": response_format,
        }

    def _extract(self, envelope: dict[str, Any]) -> tuple[str | Mapping[str, Any], dict[str, int]]:
        choices = envelope.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise AIResponseError("Groq envelope has no choices")
        choice = choices[0]
        if choice.get("finish_reason") == "length":
            raise AIResponseError("Groq output was cut off at the token limit (finish_reason=length)")
        message = choice.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise AIResponseError("Groq returned no message content")
        return content, normalize_usage(envelope.get("usage"))
