"""Shared test helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from vm1.evidence import PageSnapshot  # noqa: E402
from vm1.htmlparse import parse_html  # noqa: E402

TS = "2026-11-21T00:00:00+00:00"
WORLD = ROOT / "fixtures" / "synthetic" / "world.json"


def snap(body_html: str, url: str = "https://x.example/", home: bool = True) -> PageSnapshot:
    page = parse_html(f"<html><head><title>T</title></head><body>{body_html}</body></html>", url)
    return PageSnapshot(url=url, fetched_at=TS, page=page, is_homepage=home)


def resolver(mapping: dict[str, list[str]]):
    return lambda host: mapping.get(host, [])


def team_snap(body_html: str, url: str = "https://x.example/team") -> PageSnapshot:
    """A page whose URL says it is the company's team/leadership page (not the homepage)."""
    return snap(body_html, url, home=False)
