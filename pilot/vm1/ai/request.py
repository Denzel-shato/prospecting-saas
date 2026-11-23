"""Provider interface: one structured request in, one schema-validated object out."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol, runtime_checkable

from .errors import AIConfigError, AIResponseError, make_snippet
from .schema import SchemaViolation, check_schema, validate

DEFAULT_TIMEOUT = 30.0


@dataclass(frozen=True)
class StructuredRequest:
    """A request for one JSON object matching ``schema`` (top level must be an object)."""

    prompt: str
    schema: Mapping[str, Any]
    system: str = ""
    max_tokens: int = 1024
    temperature: float = 0.0
    timeout: float = DEFAULT_TIMEOUT

    def __post_init__(self) -> None:
        if not isinstance(self.prompt, str) or not self.prompt.strip():
            raise AIConfigError("prompt must be a non-empty string")
        if not isinstance(self.system, str):
            raise AIConfigError("system must be a string")
        try:
            check_schema(self.schema)
        except ValueError as exc:
            raise AIConfigError(f"invalid schema: {exc}") from None
        if self.schema.get("type") != "object":
            raise AIConfigError("schema top level must have type 'object'")
        if isinstance(self.max_tokens, bool) or not isinstance(self.max_tokens, int) or self.max_tokens < 1:
            raise AIConfigError("max_tokens must be a positive integer")
        if (isinstance(self.temperature, bool) or not isinstance(self.temperature, (int, float))
                or not 0 <= self.temperature <= 2):
            raise AIConfigError("temperature must be between 0 and 2")
        if (isinstance(self.timeout, bool) or not isinstance(self.timeout, (int, float))
                or not math.isfinite(self.timeout) or self.timeout <= 0):
            raise AIConfigError("timeout must be a positive, finite number of seconds")


@dataclass(frozen=True)
class StructuredResponse:
    data: dict
    provider: str
    model: str
    raw_text: str
    usage: Mapping[str, int] = field(default_factory=dict)


@runtime_checkable
class AIProvider(Protocol):
    """Anything that can answer a StructuredRequest. Raises AIProviderError subclasses only."""

    name: str

    def generate_structured(self, request: StructuredRequest) -> StructuredResponse: ...


def _reject_constant(token: str) -> Any:
    raise ValueError(f"non-standard JSON constant {token}")


def parse_json_object(text: str, *, provider: str) -> dict:
    """Parse model text as exactly one JSON object.

    Tolerates a single surrounding markdown code fence (a common model habit) and nothing
    else: no brace-hunting inside prose, no NaN/Infinity, no arrays or scalars.
    """
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```") and len(stripped) >= 6:
        inner = stripped[3:-3]
        first, _, rest = inner.partition("\n")
        if first.strip().lower() in ("", "json"):
            inner = rest
        stripped = inner.strip()
    if not stripped:
        raise AIResponseError("model returned empty content", provider=provider)
    try:
        value = json.loads(stripped, parse_constant=_reject_constant)
    except ValueError as exc:
        raise AIResponseError(
            f"model output is not valid JSON ({exc})", provider=provider, snippet=make_snippet(text)
        ) from None
    if not isinstance(value, dict):
        raise AIResponseError(
            f"model output is JSON {type(value).__name__}, expected an object",
            provider=provider, snippet=make_snippet(text),
        )
    return value


def build_response(
    content: str | Mapping[str, Any],
    request: StructuredRequest,
    *,
    provider: str,
    model: str,
    usage: Mapping[str, int] | None = None,
) -> StructuredResponse:
    """Turn model output (text or an already-parsed object) into a validated response."""
    if isinstance(content, str):
        raw_text = content
        data = parse_json_object(content, provider=provider)
    elif isinstance(content, Mapping):
        data = dict(content)
        try:
            raw_text = json.dumps(data, sort_keys=True)
        except (TypeError, ValueError):
            raise AIResponseError("model object is not JSON-serializable", provider=provider) from None
    else:
        raise AIResponseError(
            f"model content has unsupported type {type(content).__name__}", provider=provider
        )
    try:
        validate(data, request.schema)
    except SchemaViolation as exc:
        raise AIResponseError(
            f"model output violates schema: {exc}", provider=provider, snippet=make_snippet(raw_text)
        ) from None
    return StructuredResponse(data=data, provider=provider, model=model, raw_text=raw_text,
                              usage=dict(usage or {}))
