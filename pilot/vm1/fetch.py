"""Polite, SSRF-safe fetching of first-party pages (and keyless discovery APIs).

* Every URL (and every redirect hop) goes through netsafe.validate_url.
* The connection is pinned to the validated IPs (no second DNS lookup).
* robots.txt is honoured per origin (RFC 9309 style: 4xx = allowed, 5xx/unreachable = disallowed).
* Per-host minimum delay (>= robots Crawl-delay, capped), response size cap, HTML-only,
  cross-domain redirects refused, identifying User-Agent, no cookies, no auth, no JS.
* The transport is injectable so tests (and the synthetic fixture) never touch a network.
"""

from __future__ import annotations

import http.client
import socket
import ssl
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from . import ROBOTS_TOKEN, USER_AGENT
from .canon import registrable_domain
from .netsafe import Resolver, Target, UnsafeURL, default_resolver, validate_url

REDIRECT_CODES = (301, 302, 303, 307, 308)
MAX_CRAWL_DELAY = 10.0


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class RawResponse:
    status: int
    headers: dict[str, str]
    body: bytes
    truncated: bool = False


class Transport(Protocol):
    def request(
        self,
        method: str,
        target: Target,
        headers: dict[str, str],
        body: bytes | None,
        timeout: float,
        max_bytes: int,
    ) -> RawResponse: ...


class _PinnedMixin:
    _ips: list[str]

    def _connect_pinned(self) -> socket.socket:
        last: OSError | None = None
        for ip in self._ips:
            try:
                return socket.create_connection((ip, self.port), self.timeout)  # type: ignore[attr-defined]
            except OSError as exc:
                last = exc
        raise last or OSError("no addresses to connect to")


class _PinnedHTTP(_PinnedMixin, http.client.HTTPConnection):
    def __init__(self, host: str, port: int, ips: list[str], timeout: float):
        super().__init__(host, port, timeout=timeout)
        self._ips = ips

    def connect(self) -> None:
        self.sock = self._connect_pinned()


class _PinnedHTTPS(_PinnedMixin, http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, ips: list[str], timeout: float):
        super().__init__(host, port, timeout=timeout, context=ssl.create_default_context())
        self._ips = ips

    def connect(self) -> None:
        sock = self._connect_pinned()
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


class PinnedTransport:
    """Real network transport. Connects only to the pre-validated IPs."""

    def request(self, method, target, headers, body, timeout, max_bytes) -> RawResponse:
        cls = _PinnedHTTPS if target.scheme == "https" else _PinnedHTTP
        conn = cls(target.host, target.port, list(target.ips), timeout)
        deadline = time.monotonic() + timeout * 3
        try:
            conn.request(method, target.path, body=body, headers=headers)
            resp = conn.getresponse()
            chunks: list[bytes] = []
            total = 0
            truncated = False
            while True:
                if time.monotonic() > deadline:
                    raise TimeoutError("overall response deadline exceeded")
                chunk = resp.read(65536)
                if not chunk:
                    break
                if total + len(chunk) > max_bytes:
                    chunks.append(chunk[: max_bytes - total])
                    truncated = True
                    break
                total += len(chunk)
                chunks.append(chunk)
            hdrs = {k.lower(): v for k, v in resp.getheaders()}
            return RawResponse(resp.status, hdrs, b"".join(chunks), truncated)
        finally:
            conn.close()


@dataclass
class FetchResult:
    url: str
    final_url: str | None = None
    status: int | None = None
    content_type: str | None = None
    text: str | None = None
    error: str | None = None
    robots_allowed: bool | None = None
    fetched_at: str = ""
    nbytes: int = 0
    redirects: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and self.status == 200 and self.text is not None


NETWORK_ERRORS = (OSError, TimeoutError, ssl.SSLError, http.client.HTTPException)


def _decode(raw: RawResponse) -> str:
    ctype = raw.headers.get("content-type", "")
    charset = "utf-8"
    for part in ctype.split(";")[1:]:
        k, _, v = part.strip().partition("=")
        if k.lower() == "charset" and v:
            charset = v.strip("\"' ")
    try:
        return raw.body.decode(charset, errors="replace")
    except LookupError:
        return raw.body.decode("utf-8", errors="replace")


class PoliteFetcher:
    def __init__(
        self,
        transport: Transport | None = None,
        resolver: Resolver | None = None,
        *,
        min_delay: float = 2.0,
        max_bytes: int = 1_000_000,
        timeout: float = 15.0,
        max_redirects: int = 5,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], str] = utc_now_iso,
    ):
        self.transport = transport or PinnedTransport()
        self.resolver = resolver or default_resolver
        self.min_delay = min_delay
        self.max_bytes = max_bytes
        self.timeout = timeout
        self.max_redirects = max_redirects
        self.clock = clock
        self.sleep = sleep
        self.now = now
        self.log: list[dict] = []
        self._robots: dict[tuple, dict] = {}
        self._last_request: dict[str, float] = {}

    # -- internals -----------------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        return {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
            "Accept-Encoding": "identity",
            "Connection": "close",
        }

    def _wait(self, host: str, extra_delay: float = 0.0) -> None:
        delay = max(self.min_delay, extra_delay)
        last = self._last_request.get(host)
        if last is not None:
            remaining = delay - (self.clock() - last)
            if remaining > 0:
                self.sleep(remaining)
        self._last_request[host] = self.clock()

    def _record(self, url: str, status, error, nbytes, robots=None) -> None:
        self.log.append(
            {"url": url, "status": status, "error": error, "bytes": nbytes,
             "robots_allowed": robots, "at": self.now()}
        )

    def _load_robots(self, target: Target) -> dict:
        robots_url = f"{target.scheme}://{target.host}/robots.txt"
        entry: dict = {"mode": "allow_all", "parser": None, "delay": 0.0, "why": "init"}
        try:
            rt = validate_url(robots_url, self.resolver)
            self._wait(rt.host)
            raw = self.transport.request("GET", rt, self._headers(), None, self.timeout, 500_000)
            hops = 0
            while raw.status in REDIRECT_CODES and hops < 3 and raw.headers.get("location"):
                nxt = validate_url(urljoin(rt.url, raw.headers["location"]), self.resolver)
                if registrable_domain(nxt.host) != registrable_domain(rt.host):
                    raise UnsafeURL("robots.txt redirected off-site")
                rt = nxt
                self._wait(rt.host)
                raw = self.transport.request("GET", rt, self._headers(), None, self.timeout, 500_000)
                hops += 1
            if raw.status == 200:
                rp = RobotFileParser()
                rp.parse(_decode(raw).splitlines())
                delay = rp.crawl_delay(ROBOTS_TOKEN)
                entry = {"mode": "parsed", "parser": rp, "delay": float(delay or 0), "why": "robots 200"}
            elif 400 <= raw.status < 500:
                entry = {"mode": "allow_all", "parser": None, "delay": 0.0, "why": f"robots {raw.status}"}
            else:
                entry = {"mode": "disallow_all", "parser": None, "delay": 0.0,
                         "why": f"robots_unreachable status {raw.status}"}
        except UnsafeURL as exc:
            entry = {"mode": "disallow_all", "parser": None, "delay": 0.0, "why": f"robots_unsafe: {exc}"}
        except NETWORK_ERRORS as exc:
            entry = {"mode": "disallow_all", "parser": None, "delay": 0.0,
                     "why": f"robots_unreachable {type(exc).__name__}"}
        self._robots[target.origin] = entry
        self._record(robots_url, None, None if entry["mode"] != "disallow_all" else entry["why"], 0, None)
        return entry

    def robots_decision(self, target: Target) -> tuple[bool, str, float]:
        entry = self._robots.get(target.origin) or self._load_robots(target)
        if entry["mode"] == "disallow_all":
            return False, entry["why"], 0.0
        if entry["delay"] > MAX_CRAWL_DELAY:
            return False, f"crawl_delay {entry['delay']}s exceeds cap {MAX_CRAWL_DELAY}s", 0.0
        if entry["mode"] == "parsed" and not entry["parser"].can_fetch(ROBOTS_TOKEN, target.url):
            return False, "disallowed by robots.txt", entry["delay"]
        return True, entry["why"], entry["delay"]

    # -- public ----------------------------------------------------------------------
    def fetch(self, url: str) -> FetchResult:
        res = FetchResult(url=url, fetched_at=self.now())
        try:
            target = validate_url(url, self.resolver)
        except UnsafeURL as exc:
            res.error = f"unsafe_url: {exc}"
            self._record(url, None, res.error, 0)
            return res
        origin_domain = registrable_domain(target.host)

        allowed, why, delay = self.robots_decision(target)
        res.robots_allowed = allowed
        if not allowed:
            res.error = f"robots: {why}"
            self._record(url, None, res.error, 0, False)
            return res

        current = target
        for _hop in range(self.max_redirects + 1):
            self._wait(current.host, delay)
            try:
                raw = self.transport.request("GET", current, self._headers(), None,
                                             self.timeout, self.max_bytes)
            except NETWORK_ERRORS as exc:
                res.error = f"network: {type(exc).__name__}"
                self._record(current.url, None, res.error, 0, True)
                return res

            if raw.status in REDIRECT_CODES and raw.headers.get("location"):
                nxt_url = urljoin(current.url, raw.headers["location"])
                try:
                    nxt = validate_url(nxt_url, self.resolver)
                except UnsafeURL as exc:
                    res.error = f"unsafe_redirect: {exc}"
                    self._record(nxt_url, raw.status, res.error, 0, True)
                    return res
                if registrable_domain(nxt.host) != origin_domain:
                    res.error = "offsite_redirect"
                    self._record(nxt_url, raw.status, res.error, 0, True)
                    return res
                res.redirects.append(nxt.url)
                if nxt.origin != current.origin:
                    ok, why2, delay = self.robots_decision(nxt)
                    if not ok:
                        res.error = f"robots: {why2}"
                        res.robots_allowed = False
                        self._record(nxt.url, raw.status, res.error, 0, False)
                        return res
                elif not self.robots_decision(nxt)[0]:
                    res.error = "robots: disallowed by robots.txt"
                    res.robots_allowed = False
                    self._record(nxt.url, raw.status, res.error, 0, False)
                    return res
                current = nxt
                continue

            res.final_url = current.url
            res.status = raw.status
            res.content_type = raw.headers.get("content-type", "")
            res.nbytes = len(raw.body)
            if raw.status != 200:
                res.error = f"http_{raw.status}"
            elif raw.truncated:
                res.error = "too_large"
            elif not any(t in res.content_type.lower() for t in ("text/html", "application/xhtml")):
                res.error = f"non_html: {res.content_type or 'unknown'}"
            else:
                res.text = _decode(raw)
            self._record(current.url, raw.status, res.error, res.nbytes, True)
            return res

        res.error = "too_many_redirects"
        self._record(url, None, res.error, 0, True)
        return res
