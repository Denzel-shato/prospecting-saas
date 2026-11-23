"""Cloudflare Workers AI adapter (REST: POST /accounts/{account_id}/ai/run/{model}).

Shapes follow Cloudflare's public docs: bearer token auth; model inputs go directly in the
body; JSON mode is ``response_format = {"type": "json_schema", "json_schema": <schema>}``;
text-generation output is ``result.response`` (a string normally, an already-parsed object
in JSON mode) with optional ``result.usage``. Cloudflare says it cannot guarantee schema
conformance, so the output is always re-validated locally.

This module performs no I/O at import time and no request unless ``generate_structured``
is called; tests inject a fake transport.
"""

from __future__ import annotations

import re
from typing import Any, Mapping
from urllib.parse import quote

from .errors import AIConfigError, AIResponseError, make_snippet
from .http_provider import HttpJsonProvider, build_messages, normalize_usage
from .request import StructuredRequest
from .transport import HttpTransport

DEFAULT_BASE_URL = "https://api.cloudflare.com/client/v4"
_ACCOUNT_ID = re.compile(r"^[A-Za-z0-9_-]+$")
_MODEL = re.compile(r"^[A-Za-z0-9@][A-Za-z0-9@._/-]*$")


class CloudflareWorkersAIProvider(HttpJsonProvider):
    name = "cloudflare"

    def __init__(
        self,
        *,
        account_id: str,
        api_token: str,
        model: str,
        base_url: str = DEFAULT_BASE_URL,
        transport: HttpTransport | None = None,
        max_response_bytes: int = 1_000_000,
    ):
        super().__init__(model=model, api_key=api_token, base_url=base_url, transport=transport,
                         max_response_bytes=max_response_bytes)
        if not isinstance(account_id, str) or not _ACCOUNT_ID.match(account_id):
            raise AIConfigError("account id is missing or contains invalid characters")
        if not _MODEL.match(self.model) or ".." in self.model or "//" in self.model:
            raise AIConfigError("model name contains invalid characters")
        self.account_id = account_id

    def _url(self) -> str:
        return f"{self.base_url}/accounts/{self.account_id}/ai/run/{quote(self.model, safe='@/')}"

    def _payload(self, request: StructuredRequest) -> dict[str, Any]:
        return {
            "messages": build_messages(request),
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "response_format": {"type": "json_schema", "json_schema": dict(request.schema)},
        }

    def _extract(self, envelope: dict[str, Any]) -> tuple[str | Mapping[str, Any], dict[str, int]]:
        if envelope.get("success") is False:
            errors = envelope.get("errors")
            detail = ""
            if isinstance(errors, list) and errors and isinstance(errors[0], dict):
                detail = str(errors[0].get("message", ""))
            raise AIResponseError(
                f"Cloudflare reported failure: {make_snippet(detail, (self._api_key,)) or 'no detail'}"
            )
        result = envelope.get("result", envelope)
        if not isinstance(result, dict) or "response" not in result:
            raise AIResponseError("Cloudflare envelope has no result.response")
        content = result["response"]
        if content is None or (isinstance(content, str) and not content.strip()):
            raise AIResponseError("Cloudflare returned an empty response")
        return content, normalize_usage(result.get("usage"))
