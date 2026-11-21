"""Offline synthetic world for pipeline testing. EVERYTHING here is FICTIONAL.

All hosts use the reserved ``.example`` TLD. A stub resolver and a fake transport mean no network
is ever touched. Results from this world are never pilot findings.
"""

from __future__ import annotations

import json
import socket
from pathlib import Path

from .discovery import SyntheticFixtureAdapter
from .fetch import PoliteFetcher, RawResponse


class FakeTransport:
    def __init__(self, world: dict, base_dir: Path):
        self.hosts = world["hosts"]
        self.base = base_dir
        self.requests: list[tuple[str, str]] = []

    def request(self, method, target, headers, body, timeout, max_bytes) -> RawResponse:
        self.requests.append((method, target.url))
        host = self.hosts.get(target.host)
        if host is None:
            raise OSError("synthetic: no such host")
        if host.get("behavior") == "timeout":
            raise socket.timeout("synthetic timeout")
        path = target.path.split("?", 1)[0]
        if path == "/robots.txt":
            txt = host.get("robots")
            if txt is None:
                return RawResponse(404, {"content-type": "text/plain"}, b"")
            return RawResponse(200, {"content-type": "text/plain"}, txt.encode())
        page = host.get("pages", {}).get(path)
        if page is None:
            return RawResponse(404, {"content-type": "text/html"}, b"not found")
        headers_out = {"content-type": page.get("content_type", "text/html; charset=utf-8")}
        if page.get("location"):
            headers_out["location"] = page["location"]
        body = b""
        if page.get("file"):
            body = (self.base / page["file"]).read_bytes()
        return RawResponse(page.get("status", 200), headers_out, body)


def build_synthetic(world_path: str | Path):
    world_path = Path(world_path)
    world = json.loads(world_path.read_text(encoding="utf-8"))
    transport = FakeTransport(world, world_path.parent)

    def resolver(host: str) -> list[str]:
        h = world["hosts"].get(host)
        return [h.get("ip", "1.1.1.1")] if h else []

    fetcher = PoliteFetcher(transport, resolver, min_delay=0.0, sleep=lambda s: None)
    return [SyntheticFixtureAdapter(world_path)], fetcher
