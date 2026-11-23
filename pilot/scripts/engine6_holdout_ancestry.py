#!/usr/bin/env python3
"""Inspect HTML ancestry for new holdout misses; no network and no code changes.

Uses the original immutable snapshot directory from engine6-independent-20.
Run from pilot/:
    python3 scripts/engine6_holdout_ancestry.py
    python3 scripts/engine6_holdout_ancestry.py --only wirebox.co.uk
"""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_SOURCE = ROOT / "runs" / "engine6-independent-20"
DEFAULT_DOMAINS = ["whitecapcanada.com", "wirebox.co.uk", "vangwe.com", "altar.io", "coara.co"]


def short_attrs(attrs: dict[str, str]) -> str:
    return " ".join(
        key + "=" + repr(attrs[key][:140])
        for key in ("class", "id", "role", "itemprop", "itemtype", "data-testid")
        if attrs.get(key)
    )


class Ancestry(HTMLParser):
    def __init__(self, person: str):
        super().__init__(convert_charrefs=True)
        self.target = " ".join(person.casefold().split())
        self.stack: list[tuple[str, dict[str, str]]] = []
        self.hits: list[dict] = []

    def handle_starttag(self, tag, attrs):
        from vm1.htmlparse import VOID_TAGS
        if tag not in VOID_TAGS:
            self.stack.append((tag, {k: v or "" for k, v in attrs}))

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, value):
        from vm1.htmlparse import _PeopleExtractor
        clean = " ".join(value.casefold().split())
        if self.target not in clean or len(self.hits) >= 4:
            return
        if any(t in {"script", "style", "title", "template", "noscript"}
               for t, _ in self.stack):
            return
        ancestors = []
        for tag, attrs in self.stack:
            labels = sorted(_PeopleExtractor._labels(tag, attrs))
            ancestors.append({
                "tag": tag,
                "attrs": short_attrs(attrs),
                "labels": labels,
            })
        self.hits.append({"text": value.strip()[:220], "ancestors": ancestors})


def worker(row: dict, source: Path) -> dict:
    from vm1.snapshot import SnapshotStore
    result = {"company": row["company"], "domain": row["domain"],
              "name": row["expected_name"], "original_outcome": row["outcome"],
              "hits": [], "problem": None}
    if not row.get("fetch_ok"):
        result["problem"] = "Original fetch not successful"
        return result
    slug = re.sub(r"[^a-z0-9]+", "-", row["domain"])
    store = SnapshotStore(source / "snapshots" / slug)
    saved = [e for e in store.entries()
             if e.get("method") == "GET" and e.get("status") == 200
             and "text/html" in (e.get("headers") or {}).get("content-type", "").lower()]
    if len(saved) != 1:
        result["problem"] = "Expected one HTML snapshot, found " + str(len(saved))
        return result
    entry = saved[0]
    captured = store.get("GET", entry["url"])
    if not captured:
        result["problem"] = "Saved body unavailable"
        return result
    html = captured[1].decode("utf-8", errors="replace")
    parser = Ancestry(row["expected_name"])
    parser.feed(html)
    result["hits"] = parser.hits
    result["snapshot_url"] = entry["url"]
    return result


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        print(json.dumps(worker(json.loads(sys.argv[2]), Path(sys.argv[3])),
                         ensure_ascii=False))
        return 0

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--only", action="append", metavar="DOMAIN")
    p.add_argument("--timeout", type=int, default=12)
    args = p.parse_args()
    if not 1 <= args.timeout <= 30:
        p.error("Per-site timeout must be 1–30 seconds.")
    source = args.source.resolve()
    records = source / "results.jsonl"
    if not records.is_file():
        p.error("Original benchmark results missing: " + str(records))
    rows = [json.loads(line) for line in records.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    wanted = set(args.only or DEFAULT_DOMAINS)
    if wanted - {r["domain"] for r in rows}:
        p.error("Unknown domain(s): " + str(sorted(wanted - {r["domain"] for r in rows})))
    rows = [r for r in rows if r["domain"] in wanted]
    for i, row in enumerate(rows, 1):
        print("\n=== " + row["company"] + " (" + row["expected_name"] + ") "
              + str(i) + "/" + str(len(rows)) + " ===", flush=True)
        try:
            proc = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker",
                 json.dumps(row, ensure_ascii=False), str(source)],
                capture_output=True, text=True, timeout=args.timeout,
            )
            if proc.returncode:
                print("Diagnostic error:", proc.stderr[-500:], flush=True)
                continue
            outcome = json.loads(proc.stdout.strip())
        except subprocess.TimeoutExpired:
            print("Diagnostic timed out; continuing.", flush=True)
            continue
        if outcome.get("problem"):
            print("Problem:", outcome["problem"], flush=True)
            continue
        print("Saved URL:", outcome["snapshot_url"])
        print("Visible text matches:", len(outcome["hits"]))
        for hit in outcome["hits"]:
            print("\nMATCH:", repr(hit["text"]))
            offenders = [x for x in hit["ancestors"]
                         if set(x["labels"]) & {"quote", "client", "editorial", "nav", "footer"}]
            print("ALL VETO-CARRYING ANCESTORS:")
            if not offenders:
                print("  none")
            for a in offenders[-12:]:
                print("  <" + a["tag"] + "> " + a["attrs"] + " => "
                      + str(a["labels"]))
            print("NEAREST 9 ANCESTORS:")
            for a in hit["ancestors"][-9:]:
                print("  <" + a["tag"] + "> " + a["attrs"] + " => "
                      + str(a["labels"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
