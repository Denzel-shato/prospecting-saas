"""AI provider foundation for Engine #6 V2 (interface + adapters only).

Nothing in the existing deterministic pipeline imports this package, and importing it
performs no I/O. It contains no extraction, verification, queue or budget logic.
Real adapters make a network call only when ``generate_structured`` is invoked.
"""

from .cloudflare import CloudflareWorkersAIProvider
from .config import provider_from_env
from .errors import (
    AIConfigError, AIHTTPError, AIProviderError, AIResponseError, AITimeoutError, AITransportError,
)
from .groq import GroqProvider
from .mock import MockProvider
from .request import AIProvider, StructuredRequest, StructuredResponse
from .transport import HttpResponse, HttpTransport, StdlibHttpsTransport

__all__ = [
    "AIConfigError", "AIHTTPError", "AIProvider", "AIProviderError", "AIResponseError",
    "AITimeoutError", "AITransportError", "CloudflareWorkersAIProvider", "GroqProvider",
    "HttpResponse", "HttpTransport", "MockProvider", "StdlibHttpsTransport", "StructuredRequest",
    "StructuredResponse", "provider_from_env",
]
