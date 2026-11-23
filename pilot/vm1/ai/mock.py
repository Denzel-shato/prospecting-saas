"""Offline mock provider: scripted answers, recorded calls, zero network, zero keys.

Each scripted item is consumed in order and may be:
  * a dict          -> model output as an already-parsed object
  * a str           -> raw model text (lets tests simulate fenced, malformed or non-object JSON)
  * an Exception    -> raised as-is (use AIProviderError subclasses to simulate failures)
  * a callable      -> called with the StructuredRequest, must return one of the above
When the script is empty, ``default`` is used if given (never consumed); otherwise an
AIConfigError is raised so a test cannot silently over-call the provider.
Output goes through the same parse + schema validation as real providers.
"""

from __future__ import annotations

from typing import Any, Callable, Iterable

from .errors import AIConfigError
from .request import StructuredRequest, StructuredResponse, build_response


class MockProvider:
    name = "mock"

    def __init__(self, responses: Iterable[Any] = (), *, default: Any = None, model: str = "mock-1"):
        self._queue = list(responses)
        self._default = default
        self.model = model
        self.calls: list[StructuredRequest] = []

    def generate_structured(self, request: StructuredRequest) -> StructuredResponse:
        if not isinstance(request, StructuredRequest):
            raise AIConfigError("request must be a StructuredRequest")
        self.calls.append(request)
        if self._queue:
            item = self._queue.pop(0)
        elif self._default is not None:
            item = self._default
        else:
            raise AIConfigError("mock provider has no scripted response left", provider=self.name)
        if callable(item) and not isinstance(item, Exception):
            item = item(request)
        if isinstance(item, Exception):
            raise item
        return build_response(item, request, provider=self.name, model=self.model)
