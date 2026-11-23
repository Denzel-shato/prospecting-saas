"""Error taxonomy for AI providers.

Every failure a provider can produce is an ``AIProviderError`` subclass so callers can
catch one base type. ``retryable`` is advisory metadata only: no retry loop, queue or
budget exists yet (deliberately out of scope for the provider foundation).

No message here ever contains an API key; providers redact secrets before building text.
"""

from __future__ import annotations

SNIPPET_LIMIT = 200


def make_snippet(text: str, secrets: tuple[str, ...] = (), limit: int = SNIPPET_LIMIT) -> str:
    """Short, single-line, secret-free excerpt of untrusted text for error messages."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[redacted]")
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


class AIProviderError(Exception):
    """Base class for every provider failure."""

    retryable = False

    def __init__(self, message: str, *, provider: str | None = None):
        super().__init__(message)
        self.provider = provider


class AIConfigError(AIProviderError):
    """Missing or invalid configuration, or an invalid request. Never retryable."""


class AITimeoutError(AIProviderError):
    """The provider did not answer within the request timeout."""

    retryable = True


class AITransportError(AIProviderError):
    """Connection, DNS or TLS failure before a complete HTTP response arrived."""

    retryable = True


class AIHTTPError(AIProviderError):
    """The provider answered with a non-2xx status."""

    def __init__(self, status: int, message: str, *, provider: str | None = None):
        super().__init__(f"HTTP {status}: {message}", provider=provider)
        self.status = status

    @property
    def retryable(self) -> bool:  # type: ignore[override]
        return self.status in (408, 409, 425, 429) or self.status >= 500


class AIResponseError(AIProviderError):
    """A 2xx answer that is unusable: bad envelope, not JSON, truncated, or schema-invalid."""

    def __init__(self, message: str, *, provider: str | None = None, snippet: str = ""):
        super().__init__(message, provider=provider)
        self.snippet = snippet
