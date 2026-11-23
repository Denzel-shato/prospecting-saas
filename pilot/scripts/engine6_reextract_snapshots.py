#!/usr/bin/env python3
"""Re-evaluate Engine #6 against the SAME 12 previously captured first-party HTML pages.

No HTTP, DNS, robots, capture, or discovery calls are made. Saved redacted snapshots
and the prior benchmark labels are inputs; the old benchmark is NEVER overwritten.

From pilot/:
    python3 scripts/engine6_reextract_snapshots.py
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SOURCE = ROOT / "runs" / "engine6-known-leaders-12"
FIELDS = ("company", "domain", "url", "expected_name", "expected_role")


def read_original(source: Path) -> list[dict]:
    path = source / "results.jsonl"
    if not path.exists():
        raise FileNotFoundError(f"Original benchmark not found: {path}")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
    if len({r["domain"] for r in rows}) != len(rows):
        raise ValueError("Original benchmark has duplicate domains; resolve before comparing")
    return rows


def reextract(row: dict, source: Path) -> dict:
    from vm1.evidence import PageSnapshot, verify_excerpt_parts
    from vm1.htmlparse import parse_html
    from vm1.people import find_decision_makers
    from vm1.snapshot import SnapshotStore

    result = dict(row)
    result.update(before_outcome=row.get("outcome"), after_outcome="not_rechecked",
                  expected_found_after=False, people_after=[], people_blocks_after=0,
                  name_in_text_after=None, snapshot_url=None)
    if not row.get("fetch_ok"):
        result["after_outcome"] = "original_fetch_failed"
        return result

    slug = re.sub(r"[^a-z0-9]+", "-", row["domain"].lower()).strip("-")
    store = SnapshotStore(source / "snapshots" / slug)
    html_entries = [
        e for e in store.entries()
        if e.get("method") == "GET" and e.get("status") == 200 and not e.get("truncated")
        and "text/html" in (e.get("headers") or {}).get("content-type", "").lower()
    ]
    if len(html_entries) != 1:
        result.update(after_outcome="ambiguous_or_missing_saved_html",
                      error=f"expected 1 saved HTML 200, got {len(html_entries)}")
        return result

    entry = html_entries[0]
    url = entry["url"]
    result["snapshot_url"] = url
    body = store.get("GET", url)[1].decode("utf-8", errors="replace")
    page = parse_html(body, url)
    result["people_blocks_after"] = len(page.people_blocks)
    name = " ".join(row["expected_name"].casefold().split())
    result["name_in_text_after"] = any(
        name in " ".join(t.casefold().split()) for t in [*page.blocks, *page.people_blocks]
    )
    snap = PageSnapshot(url=url, fetched_at=entry.get("captured_at", ""),
                        page=page, is_homepage=False)
    people = [
        p for p in find_decision_makers(
            [snap], limit=3, company_key=row["domain"], company_name=row["company"]
        )
        if verify_excerpt_parts(p.excerpt_parts, page)
    ]
    result["people_after"] = [
        {"name": p.name, "title": p.title, "basis": p.basis,
         "source_url": p.source_url, "excerpt": p.excerpt}
        for p in people
    ]
    result["expected_found_after"] = any(
        " ".join(p.name.casefold().split()) == name for p in people
    )
    result["after_outcome"] = (
        "found_expected" if result["expected_found_after"]
        else "needs_manual_review" if result["name_in_text_after"]
        else "name_absent_from_parsed_text"
    )
    return result


def save(rows: list[dict], out: Path) -> None:
    with (out / "results.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    with (out / "results.csv").open("w", newline="", encoding="utf-8") as f:
        names = [*FIELDS, "before_outcome", "after_outcome",
                 "expected_found_after", "name_in_text_after", "snapshot_url", "people_after"]
        writer = csv.DictWriter(f, fieldnames=names)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **{key: row.get(key, "") for key in names if key != "people_after"},
                "people_after": json.dumps(row.get("people_after", []), ensure_ascii=False)
            })
    old = sum(r.get("outcome") == "found_expected" for r in rows)
    new = sum(r.get("expected_found_after", False) for r in rows)
    accessible = sum(bool(r.get("fetch_ok")) for r in rows)
    body = [
        "# Engine #6 — offline before/after on 12 cached pages",
        "",
        "**Same saved first-party HTML; no new fetches. Not an independent sample or population recall.**",
        "Human verification is required for all extracted names, roles, and associations.",
        "",
        f"- Companies in original benchmark: {len(rows)}",
        f"- Original fetch successes: {accessible}",
        f"- Expected leaders before: {old}/{accessible}",
        f"- Expected leaders after: {new}/{accessible}",
        "",
        "| Company | Before | After | People extracted after |",
        "|---|---|---|---|"
    ]
    for row in rows:
        people = ", ".join(p["name"] + " (" + p["title"] + ")"
                           for p in row.get("people_after", [])) or "—"
        body.append(f"| {row['company']} | {row['before_outcome']} | "
                    f"{row['after_outcome']} | {people} |")
    body += ["", "The original records and saved snapshots were not modified.", ""]
    (out / "report.md").write_text("\n".join(body), encoding="utf-8")


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--worker":
        print(json.dumps(reextract(json.loads(sys.argv[2]), Path(sys.argv[3])),
                         ensure_ascii=False))
        return 0

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=SOURCE)
    parser.add_argument("--out", type=Path, default=SOURCE / "offline-after-card-fix")
    parser.add_argument("--timeout", type=int, default=12,
                        help="Maximum duration of each offline worker (1–30 seconds)")
    parser.add_argument("--limit", type=int, default=None,
                        help="Optionally process only the first N companies as a smoke test")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 30:
        parser.error("--timeout must be 1–30 seconds")
    rows = read_original(args.source)
    if args.limit is not None:
        if not 1 <= args.limit <= len(rows):
            parser.error(f"--limit must be between 1 and {len(rows)}")
        rows = rows[:args.limit]
    out = args.out
    if out.resolve() == args.source.resolve():
        parser.error("--out must be separate from original benchmark folder")
    out.mkdir(parents=True, exist_ok=True)
    results = []
    for i, row in enumerate(rows, 1):
        print(f"[{i}/{len(rows)}] {row['company']}", flush=True)
        try:
            completed = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()), "--worker",
                 json.dumps(row, ensure_ascii=False), str(args.source.resolve())],
                capture_output=True, text=True, timeout=args.timeout,
            )
            if completed.returncode:
                result = {**row, "before_outcome": row.get("outcome"),
                          "after_outcome": "worker_error", "expected_found_after": False,
                          "error": completed.stderr[-1000:]}
            else:
                result = json.loads(completed.stdout.splitlines()[-1])
        except subprocess.TimeoutExpired:
            result = {**row, "before_outcome": row.get("outcome"),
                      "after_outcome": "timeout", "expected_found_after": False}
        results.append(result)
        save(results, out)
        print("  " + result["after_outcome"], flush=True)
    print(f"REPORT: {out / 'report.md'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
