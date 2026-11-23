#!/usr/bin/env python3
"""Bounded, read-only offline diagnosis of the independent 20-company holdout.

The original benchmark, cached HTML and VM1 extraction code are never changed.
Run from pilot/:
    python3 scripts/engine6_holdout_audit.py --only whitecapcanada.com --only wirebox.co.uk
    python3 scripts/engine6_holdout_audit.py
"""
from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import re
import subprocess
import sys

PILOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PILOT))
DEFAULT_SOURCE = PILOT / "runs" / "engine6-independent-20"


def examine(row: dict, source: Path) -> dict:
    from vm1.snapshot import SnapshotStore
    from vm1.htmlparse import parse_html
    from vm1.context import THIRD_PARTY_CTX, looks_like_quote_neighbour, page_kind
    from vm1.people import NAME_ONLY_RE, TITLE_ONLY_RE, NAME_TITLE_RE, PROSE_IS_RE
    from vm1.people import _third_party_people_section

    d = {
        "company": row["company"], "domain": row["domain"],
        "expected": row["expected_name"], "outcome": row["outcome"],
        "http": row.get("http_status"), "error": row.get("fetch_error"),
        "extracted": [(p.get("name"), p.get("title"))
                      for p in row.get("people", [])],
        "notes": [], "hits": [],
    }
    if not row.get("fetch_ok"):
        d["notes"].append("Original fetch failed or timed out: no extraction judgment.")
        return d

    slug = re.sub(r"[^a-z0-9]+", "-", row["domain"].lower()).strip("-")
    store = SnapshotStore(source / "snapshots" / slug)
    entries = [
        e for e in store.entries()
        if e.get("method") == "GET" and e.get("status") == 200
        and not e.get("truncated")
        and "text/html" in (e.get("headers") or {}).get("content-type", "").lower()
    ]
    if len(entries) != 1:
        d["notes"].append("Expected exactly one saved HTML response; got " + str(len(entries)))
        return d

    entry = entries[0]
    saved = store.get("GET", entry["url"])
    if not saved:
        d["notes"].append("Saved HTML body missing.")
        return d
    html = saved[1].decode("utf-8", errors="replace")
    page = parse_html(html, entry["url"])
    pview = replace(page, blocks=page.people_blocks,
                    block_ctx=page.people_ctx, block_section=page.people_sections)
    expected = " ".join(row["expected_name"].casefold().split())

    def has_name(value: str) -> bool:
        return expected in " ".join(value.casefold().split())

    hits = [i for i, block in enumerate(pview.blocks) if has_name(block)]
    d.update(
        url=entry["url"], page_kind=page_kind(entry["url"]),
        in_html=has_name(html),
        in_standard_blocks=any(has_name(block) for block in page.blocks),
        in_people_blocks=bool(hits),
        in_jsonld=any(has_name(block) for block in page.jsonld_raw),
        people_block_count=len(page.people_blocks),
        hit_count=len(hits),
    )
    if not hits:
        if d["in_standard_blocks"]:
            d["notes"].append("Name parsed in standard view, absent in people view.")
        elif d["in_html"]:
            d["notes"].append("Name in raw HTML only: check script, alt text, or parser.")
        else:
            d["notes"].append("Name absent from saved HTML: check original label and URL.")

    for i in hits[:3]:
        labels = sorted(pview.ctx_at(i) & THIRD_PARTY_CTX)
        d["hits"].append({
            "at": i,
            "section": pview.section_at(i),
            "veto_labels": labels,
            "veto_section": bool(_third_party_people_section(pview.section_at(i))),
            "veto_quote_neighbour": looks_like_quote_neighbour(pview, i),
            "neighbors": [
                {
                    "index": j, "text": pview.blocks[j][:180],
                    "ctx": sorted(pview.ctx_at(j)),
                    "name_only": bool(NAME_ONLY_RE.fullmatch(pview.blocks[j])),
                    "title_only": bool(TITLE_ONLY_RE.fullmatch(pview.blocks[j])),
                    "inline_name_title": bool(NAME_TITLE_RE.fullmatch(pview.blocks[j])),
                    "prose_person": bool(PROSE_IS_RE.search(pview.blocks[j])),
                }
                for j in range(max(0, i - 2), min(len(pview.blocks), i + 5))
            ],
        })
    return d


def write_report(rows: list[dict], path: Path) -> None:
    lines = [
        "ENGINE #6: INDEPENDENT 20 — OFFLINE TRIAGE",
        "Read-only. Does not re-fetch, modify extraction logic or alter holdout labels.",
        "",
    ]
    for r in rows:
        lines += [
            "=" * 68,
            r["company"] + " | expected: " + r["expected"],
            "Original: " + r["outcome"] + " | HTTP: " + str(r.get("http"))
            + " | fetch error: " + str(r.get("error")),
        ]
        if "url" in r:
            lines += [
                "Saved URL: " + r["url"] + " | page kind: " + r["page_kind"],
                "Name present: raw=" + str(r["in_html"])
                + " standard=" + str(r["in_standard_blocks"])
                + " people=" + str(r["in_people_blocks"])
                + " JSON-LD=" + str(r["in_jsonld"]),
            ]
        if r.get("extracted"):
            lines.append("Other extracted people: " + repr(r["extracted"]))
        for note in r.get("notes", []):
            lines.append("NOTE: " + note)
        for hit in r.get("hits", []):
            lines += [
                "NAME HIT AT BLOCK " + str(hit["at"]),
                "  Section: " + hit["section"][:180],
                "  Rejection: labels=" + repr(hit["veto_labels"])
                + " section=" + str(hit["veto_section"])
                + " quote=" + str(hit["veto_quote_neighbour"]),
            ]
            for n in hit["neighbors"]:
                flags = ("name=" + str(n["name_only"]) + ", title=" + str(n["title_only"])
                         + ", inline=" + str(n["inline_name_title"])
                         + ", prose=" + str(n["prose_person"]))
                lines.append("  [" + str(n["index"]) + "] " + repr(n["text"])
                             + " ctx=" + repr(n["ctx"]) + " " + flags)
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--worker":
        print(json.dumps(examine(json.loads(sys.argv[2]), Path(sys.argv[3])),
                         ensure_ascii=False))
        return 0

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--only", action="append", metavar="DOMAIN")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--timeout", type=int, default=12)
    args = parser.parse_args()
    if not 1 <= args.timeout <= 30:
        parser.error("--timeout must be from 1 to 30 seconds")
    source = args.source.resolve()
    records = source / "results.jsonl"
    if not records.is_file():
        parser.error("Original holdout results not found: " + str(records))
    rows = [json.loads(line) for line in records.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if args.only:
        selected = set(args.only)
        missing = selected - {r["domain"] for r in rows}
        if missing:
            parser.error("Unknown domains: " + ", ".join(sorted(missing)))
        rows = [r for r in rows if r["domain"] in selected]

    out = (args.out or source / "offline-triage.txt").resolve()
    if out == (source / "report.md").resolve() or out == records.resolve():
        parser.error("Refusing to overwrite the original benchmark records")
    analyzed = []
    for i, row in enumerate(rows, 1):
        print("[" + str(i) + "/" + str(len(rows)) + "] " + row["company"], flush=True)
        try:
            run = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker",
                 json.dumps(row, ensure_ascii=False), str(source)],
                capture_output=True, text=True, timeout=args.timeout,
            )
            if run.returncode:
                d = {"company": row["company"], "expected": row["expected_name"],
                     "outcome": row["outcome"], "http": row.get("http_status"),
                     "error": row.get("fetch_error"), "notes":
                     ["Diagnostic worker error: " + run.stderr[-350:]], "hits": []}
            else:
                d = json.loads(run.stdout.strip())
        except subprocess.TimeoutExpired:
            d = {"company": row["company"], "expected": row["expected_name"],
                 "outcome": row["outcome"], "http": row.get("http_status"),
                 "error": row.get("fetch_error"), "notes":
                 ["Offline analysis timed out; child process stopped."], "hits": []}
        analyzed.append(d)
        write_report(analyzed, out)
    print("REPORT:", out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
