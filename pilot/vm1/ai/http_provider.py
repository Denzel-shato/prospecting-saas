"""Shared machinery for HTTP/JSON providers: one place for status, envelope and output handling."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

from .errors import (
    AIConfigError, AIHTTPError, AIProviderError, AIResponseError, AITimeoutError, AITransportError,
    make_snippet,
)
from .request import StructuredRequest, StructuredResponse, build_response
from .transport import HttpTransport, StdlibHttpsTransport, validate_https_url

DEFAULT_MAX_RESPONSE_BYTES = 1_000_000
_BAD_TOKEN_CHARS = re.compile(r"[\s\x00-\x1f\x7f]")


def check_token(label: str, value: Any) -> str:
    """API keys/model names: non-empty, no whitespace or control chars (blocks header injection)."""
    if not isinstance(value, str) or not value or _BAD_TOKEN_CHARS.search(value):
        raise AIConfigError(f"{label} is missing or contains whitespace/control characters")
    return value


def build_messages(request: StructuredRequest) -> list[dict[str, str]]:
    """System + user messages; the schema is also stated in words so any model can follow it."""
    instruction = (
        "Respond with a single JSON object only: no prose, no markdown. "
        "It must match this JSON Schema:\n" + json.dumps(request.schema, sort_keys=True)
    )
    system = f"{request.system}\n\n{instruction}" if request.system else instruction
    return [{"role": "system", "content": system}, {"role": "user", "content": request.prompt}]


def normalize_usage(raw: Any) -> dict[str, int]:
    if not isinstance(raw, Mapping):
        return {}
    return {
        k: v for k in ("prompt_tokens", "completion_tokens", "total_tokens")
        if isinstance(v := raw.get(k), int) and not isinstance(v, bool)
    }


class HttpJsonProvider:
    """Base for adapters. Subclasses supply the URL, payload and envelope extraction only."""

    name = "http"

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        transport: HttpTransport | None = None,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
    ):
        self.model = check_token("model", model)
        self._api_key = check_token("api key", api_key)
        validate_https_url(base_url)
        self.base_url = base_url.rstrip("/")
        if isinstance(max_response_bytes, bool) or not isinstance(max_response_bytes, int) or max_response_bytes < 1:
            raise AIConfigError("max_response_bytes must be a positive integer")
        self.max_response_bytes = max_response_bytes
        self._transport: HttpTransport = transport or StdlibHttpsTransport()

    def __repr__(self) -> str:  # never include the key
        return f"{type(self).__name__}(model={self.model!r})"

    # -- hooks -------------------------------------------------------------------------
    def _url(self) -> str:
        raise NotImplementedError

    def _payload(self, request: StructuredRequest) -> dict[str, Any]:
        raise NotImplementedError

    def _extract(self, envelope: dict[str, Any]) -> tuple[str | Mapping[str, Any], dict[str, int]]:
        """Return (model content, usage) from a decoded 2xx envelope or raise AIResponseError."""
        raise NotImplementedError

    # -- shared flow -------------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _error_detail(self, body: bytes) -> str:
        text = body.decode("utf-8", errors="replace")
        detail = text
        try:
            doc = json.loads(text)
        except ValueError:
            doc = None
        if isinstance(doc, dict):
            err = doc.get("error")
            errs = doc.get("errors")
            if isinstance(err, dict) and isinstance(err.get("message"), str):
                detail = err["message"]
            elif isinstance(err, str):
                detail = err
            elif isinstance(errs, list) and errs and isinstance(errs[0], dict) and isinstance(errs[0].get("message"), str):
                detail = errs[0]["message"]
        return make_snippet(detail, (self._api_key,))

    def generate_structured(self, request: StructuredRequest) -> StructuredResponse:
        if not isinstance(request, StructuredRequest):
            raise AIConfigError("request must be a StructuredRequest")
        try:
            resp = self._transport.post_json(
                self._url(), self._headers(), self._payload(request), request.timeout, self.max_response_bytes
            )
        except AIProviderError as exc:
            exc.provider = exc.provider or self.name
            raise
        except TimeoutError:
            raise AITimeoutError(f"no response within {request.timeout:g}s", provider=self.name) from None
        except OSError as exc:
            raise AITransportError(f"connection failed ({type(exc).__name__})", provider=self.name) from None

        if not 200 <= resp.status < 300:
            raise AIHTTPError(resp.status, self._error_detail(resp.body), provider=self.name)

        try:
            envelope = json.loads(resp.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise AIResponseError(
                "response body is not valid JSON", provider=self.name,
                snippet=make_snippet(resp.body.decode("utf-8", errors="replace"), (self._api_key,)),
            ) from None
        if not isinstance(envelope, dict):
            raise AIResponseError("response envelope is not a JSON object", provider=self.name)

        try:
            content, usage = self._extract(envelope)
            return build_response(content, request, provider=self.name, model=self.model, usage=usage)
        except AIResponseError as exc:
            exc.provider = exc.provider or self.name
            if exc.snippet:
                exc.snippet = make_snippet(exc.snippet, (self._api_key,))
            raise
