#!/usr/bin/env python3
"""Identify the exact HTML ancestors introducing client/editorial labels.

This diagnostic reads only the existing captured 12-site benchmark snapshots.
It makes NO network requests and does not change the source snapshots.
Run from pilot/:
  python3 scripts/engine6_context_ancestry.py
"""
from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from vm1.htmlparse import _Extractor, VOID_TAGS
from vm1.snapshot import SnapshotStore


class Ancestry(HTMLParser):
    def __init__(self, person: str):
        super().__init__(convert_charrefs=True)
        self.person = person.casefold()
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.hits: list[tuple[str, list]] = []

    def handle_starttag(self, tag, attrs):
        if tag not in VOID_TAGS:
            self.stack.append((tag, {k: (v or "") for k, v in attrs}))

    def handle_startendtag(self, tag, attrs):
        # Self-closing tags never become ancestors.
        pass

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, value):
        if (self.person in value.casefold()
                and not any(tag in {"script", "style", "title", "template", "noscript"}
                            for tag, _ in self.stack)
                and len(self.hits) < 3):
            self.hits.append((value.strip()[:180], self.stack.copy()))


def short_attrs(a: dict[str, str]) -> str:
    return " ".join(
        f"{k}={a[k][:120]!r}"
        for k in ("class", "id", "itemtype", "itemprop", "role")
        if a.get(k)
    )


def main():
    targets = [
        ("Happy Cog", "happycog.com", "Lee Goldberg"),
        ("MindSea", "mindsea.com", "Reuben Hall"),
    ]
    base = ROOT / "runs" / "engine6-known-leaders-12" / "snapshots"
    for company, domain, person in targets:
        print(f"\n=== {company}: {person} ===", flush=True)
        slug = re.sub(r"[^a-z0-9]+", "-", domain)
        store = SnapshotStore(base / slug)
        entries = [
            e for e in store.entries()
            if e.get("status") == 200
            and "text/html" in (e.get("headers") or {}).get("content-type", "").lower()
        ]
        if len(entries) != 1:
            print(f"Expected 1 captured HTML page, got {len(entries)}")
            continue
        entry = entries[0]
        html = store.get("GET", entry["url"])[1].decode("utf-8", errors="replace")
        inspector = Ancestry(person)
        inspector.feed(html)
        print(f"URL: {entry['url']} | visible text hits: {len(inspector.hits)}")
        for text, ancestors in inspector.hits:
            print(f"\nMATCH: {text!r}")
            print("Ancestor labels responsible for veto:")
            offenders = [
                (tag, attrs, labels)
                for tag, attrs in ancestors
                if (labels := _Extractor._labels(tag, attrs)) & {"client", "editorial"}
            ]
            if not offenders:
                print("  none")
            for tag, attrs, labels in offenders:
                print(f"  <{tag}> {short_attrs(attrs)} => {sorted(labels)}")
            print("Nearest 9 ancestors (outermost first):")
            for tag, attrs in ancestors[-9:]:
                print(f"  <{tag}> {short_attrs(attrs)}")


if __name__ == "__main__":
    main()
