"""Minimal HTTPS JSON POST transport (standard library only, injectable for tests).

* https only, no credentials in the URL, redirects are never followed (a 3xx is returned
  to the caller and treated as an error, so an Authorization header cannot be replayed
  to another host).
* ``timeout`` bounds the whole exchange: the socket timeout covers connect/send/each read,
  and a wall-clock deadline is checked between body chunks so a slow-drip response cannot
  outlive it.
* The response body is capped at ``max_bytes``.
"""

from __future__ import annotations

import http.client
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlsplit

from .errors import AIConfigError, AIResponseError, AITimeoutError, AITransportError

CHUNK = 8192


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    def post_json(
        self, url: str, headers: Mapping[str, str], payload: Mapping[str, Any], timeout: float, max_bytes: int
    ) -> HttpResponse: ...


def validate_https_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise AIConfigError("provider URL must use https")
    if not parts.hostname:
        raise AIConfigError("provider URL has no host")
    if parts.username or parts.password:
        raise AIConfigError("provider URL must not contain credentials")


ConnectionFactory = Callable[[str, int | None, float], "http.client.HTTPConnection"]


def _default_connection(host: str, port: int | None, timeout: float) -> http.client.HTTPConnection:
    return http.client.HTTPSConnection(host, port, timeout=timeout)


class StdlibHttpsTransport:
    def __init__(self, connection_factory: ConnectionFactory = _default_connection):
        self._connect = connection_factory

    def post_json(
        self, url: str, headers: Mapping[str, str], payload: Mapping[str, Any], timeout: float, max_bytes: int
    ) -> HttpResponse:
        validate_https_url(url)
        parts = urlsplit(url)
        target = parts.path or "/"
        if parts.query:
            target += "?" + parts.query
        body = json.dumps(payload).encode("utf-8")
        send_headers = {**headers, "Content-Type": "application/json", "Accept": "application/json"}
        deadline = time.monotonic() + timeout
        conn = self._connect(parts.hostname, parts.port, timeout)
        try:
            conn.request("POST", target, body=body, headers=send_headers)
            resp = conn.getresponse()
            chunks: list[bytes] = []
            size = 0
            while True:
                if time.monotonic() > deadline:
                    raise AITimeoutError(f"no complete response within {timeout:g}s")
                chunk = resp.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise AIResponseError(f"response body exceeds {max_bytes} bytes")
                chunks.append(chunk)
            return HttpResponse(resp.status, {k.lower(): v for k, v in resp.getheaders()}, b"".join(chunks))
        except TimeoutError:
            raise AITimeoutError(f"no response within {timeout:g}s") from None
        except (OSError, http.client.HTTPException) as exc:
            raise AITransportError(f"connection failed ({type(exc).__name__})") from None
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001 - closing must never mask the real error
                pass
