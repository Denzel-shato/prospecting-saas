"""SSRF protection: every URL is validated before any socket is opened.

* http/https only, default ports only (80/443), no credentials in the URL.
* IP-literal hosts and single-label / internal-looking hostnames are rejected.
* The hostname is resolved and EVERY returned address must be globally routable.
  The validated addresses are then pinned for the connection (see fetch.py), which
  closes the DNS-rebinding window between validation and connect.
"""

from __future__ import annotations

import ipaddress
import re
import socket
from dataclasses import dataclass
from typing import Callable, Sequence
from urllib.parse import urlsplit

Resolver = Callable[[str], Sequence[str]]

_BLOCKED_SUFFIXES = (
    ".local", ".localhost", ".internal", ".intranet", ".lan", ".home", ".corp",
    ".private", ".localdomain", ".home.arpa", ".onion",
)
_LABEL = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
_HOST_RE = re.compile(rf"^(?:{_LABEL}\.)+{_LABEL}$")


class UnsafeURL(ValueError):
    """The URL is not allowed to be fetched."""


@dataclass(frozen=True)
class Target:
    scheme: str
    host: str
    port: int
    path: str  # path + ?query, never a fragment
    ips: tuple[str, ...]

    @property
    def url(self) -> str:
        default = 443 if self.scheme == "https" else 80
        netloc = self.host if self.port == default else f"{self.host}:{self.port}"
        return f"{self.scheme}://{netloc}{self.path}"

    @property
    def origin(self) -> tuple[str, str, int]:
        return (self.scheme, self.host, self.port)


def is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return bool(ip.is_global) and not ip.is_multicast


def default_resolver(host: str) -> list[str]:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return []
    return sorted({info[4][0] for info in infos})


def validate_url(url: str, resolver: Resolver | None = None) -> Target:
    resolver = resolver or default_resolver
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError as exc:
        raise UnsafeURL(f"unparseable url: {exc}") from exc

    scheme = (parts.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise UnsafeURL(f"scheme {scheme!r} not allowed")
    if parts.username is not None or parts.password is not None:
        raise UnsafeURL("credentials in url not allowed")
    host = (parts.hostname or "").lower().rstrip(".")
    if not host:
        raise UnsafeURL("missing host")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise UnsafeURL("ip-literal hosts not allowed")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise UnsafeURL("invalid idna host") from exc
    if not _HOST_RE.match(host):
        raise UnsafeURL("host is not a valid multi-label hostname")
    if host.endswith(_BLOCKED_SUFFIXES):
        raise UnsafeURL("internal-looking hostname")

    default = 443 if scheme == "https" else 80
    port = port or default
    if port not in (80, 443):
        raise UnsafeURL(f"port {port} not allowed")

    ips = list(resolver(host))
    if not ips:
        raise UnsafeURL("host did not resolve")
    bad = [ip for ip in ips if not is_public_ip(ip)]
    if bad:
        raise UnsafeURL(f"host resolves to non-public address(es): {bad}")

    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return Target(scheme=scheme, host=host, port=port, path=path, ips=tuple(ips))
