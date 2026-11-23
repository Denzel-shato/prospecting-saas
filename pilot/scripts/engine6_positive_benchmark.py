#!/usr/bin/env python3
"""Bounded positive-control benchmark for VM1 Engine #6.

One pre-reviewed first-party About/Team page per studio; NO discovery, email
collection, sending, or full pipeline. Results are NOT representative lead yield.

Run from pilot/:
    python3 scripts/engine6_positive_benchmark.py --limit 3
    python3 scripts/engine6_positive_benchmark.py --limit 12

Each site runs in a child process capped by --timeout. The driver is sequential,
prints progress, and saves every completed result before starting the next site.
Saved snapshots are redacted by VM1's RecordingTransport and remain git-ignored.
"""
from __future__ import annotations

import argparse
import csv
import faulthandler
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

PILOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PILOT))
DEFAULT_CSV = PILOT / "benchmarks" / "engine6-known-leaders.csv"
DEFAULT_OUT = PILOT / "runs" / "engine6-known-leaders-12"
FIELDS = ("company", "domain", "url", "expected_name", "expected_role")


def load_targets(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    if not rows:
        raise ValueError("Benchmark CSV has no rows")
    for row in rows:
        if not all(row.get(key, "").strip() for key in FIELDS):
            raise ValueError("Every target needs company, domain, url, expected_name, expected_role")
        if not row["url"].startswith("https://"):
            raise ValueError("Only HTTPS first-party leadership pages are permitted")
        from urllib.parse import urlsplit
        from vm1.canon import registrable_domain
        if registrable_domain(urlsplit(row["url"]).hostname or "") != row["domain"]:
            raise ValueError("Target URL must be on its company's first-party domain")
    return rows


def worker(target: dict, snapshot_root: Path) -> dict:
    from vm1.evidence import PageSnapshot, verify_excerpt_parts
    from vm1.fetch import PinnedTransport, PoliteFetcher
    from vm1.htmlparse import parse_html
    from vm1.people import find_decision_makers
    from vm1.snapshot import RecordingTransport, SnapshotStore

    started = time.monotonic()
    faulthandler.dump_traceback_later(10, repeat=False, file=sys.stderr)
    store = SnapshotStore(snapshot_root)
    fetcher = PoliteFetcher(
        RecordingTransport(PinnedTransport(), store),
        timeout=6.0, min_delay=2.0, max_bytes=1_000_000,
    )
    record = {
        **target, "fetch_ok": False, "http_status": None, "fetch_error": None,
        "people_blocks": 0, "expected_in_visible_text": None,
        "expected_found": False, "people": [], "outcome": "fetch_failed",
    }
    print("fetching leadership page", file=sys.stderr, flush=True)
    res = fetcher.fetch(target["url"])
    record.update(fetch_ok=res.ok, http_status=res.status, fetch_error=res.error)
    if not res.ok:
        record["elapsed_s"] = round(time.monotonic() - started, 2)
        return record

    print("parsing fetched HTML", file=sys.stderr, flush=True)
    url = res.final_url or target["url"]
    page = parse_html(res.text or "", url)
    record["people_blocks"] = len(page.people_blocks)
    wanted = " ".join(target["expected_name"].casefold().split())
    record["expected_in_visible_text"] = any(
        wanted in " ".join(block.casefold().split())
        for block in [*page.blocks, *page.people_blocks]
    )

    print("extracting people", file=sys.stderr, flush=True)
    snap = PageSnapshot(url=url, fetched_at=res.fetched_at, page=page, is_homepage=False)
    found = [
        p for p in find_decision_makers(
            [snap], limit=3, company_key=target["domain"], company_name=target["company"]
        ) if verify_excerpt_parts(p.excerpt_parts, page)
    ]
    record["people"] = [
        {"name": p.name, "title": p.title, "basis": p.basis,
         "source_url": p.source_url, "excerpt": p.excerpt}
        for p in found
    ]
    record["expected_found"] = any(
        " ".join(p.name.casefold().split()) == wanted for p in found
    )
    if record["expected_found"]:
        record["outcome"] = "found_expected"
    elif record["expected_in_visible_text"]:
        record["outcome"] = "needs_manual_review"
    else:
        record["outcome"] = "expected_name_absent_from_parsed_text"
    record["elapsed_s"] = round(time.monotonic() - started, 2)
    return record


def results_from(path: Path) -> dict[str, dict]:
    found = {}
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                if line.strip():
                    row = json.loads(line)
                    found[row["domain"]] = row
    return found


def write_reports(targets: list[dict], previous: dict, out: Path) -> None:
    rows = [previous[t["domain"]] for t in targets if t["domain"] in previous]
    with (out / "results.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=[
            *FIELDS, "outcome", "fetch_ok", "http_status", "fetch_error",
            "expected_in_visible_text", "expected_found", "people_blocks",
            "people_found", "elapsed_s", "people_json",
        ])
        writer.writeheader()
        for row in rows:
            writer.writerow({
                **{key: row.get(key, "") for key in FIELDS},
                **{key: row.get(key, "") for key in (
                    "outcome", "fetch_ok", "http_status", "fetch_error",
                    "expected_in_visible_text", "expected_found",
                    "people_blocks", "elapsed_s",
                )},
                "people_found": len(row.get("people") or []),
                "people_json": json.dumps(row.get("people") or [], ensure_ascii=False),
            })
    reachable = sum(bool(r.get("fetch_ok")) for r in rows)
    successes = sum(bool(r.get("expected_found")) for r in rows)
    needs_review = sum(r.get("outcome") == "needs_manual_review" for r in rows)
    failures = sum(r.get("outcome") == "fetch_failed" for r in rows)
    timed_out = sum(r.get("outcome") == "timeout" for r in rows)
    body = [
        "# VM1 Engine #6 — preselected first-party positive controls",
        "",
        "**Not population recall, autonomous discovery, or qualified-lead yield.** "
        "The pages were deliberately chosen because an official site showed a named leader "
        "during human-assisted research. Website content may change between review and fetch.",
        "",
        f"- Processed: {len(rows)} / {len(targets)}",
        f"- Fetched successfully: {reachable}",
        f"- Expected leader extracted: {successes}",
        f"- Expected leader found / successfully fetched: "
        f"{successes}/{reachable} (not a population estimate)",
        f"- Expected name visible but not extracted (review needed): {needs_review}",
        f"- Fetch failures: {failures}; timeouts: {timed_out}",
        "",
        "| Studio | Expected person | Outcome | Extracted people |",
        "|---|---|---|---|",
    ]
    for r in rows:
        names = ", ".join(
            p["name"] + " (" + p["title"] + ")" for p in r.get("people") or []
        ) or "—"
        body.append(
            f"| {r['company']} | {r['expected_name']} | {r['outcome']} | {names} |"
        )
    body.extend([
        "",
        "A success means Engine #6 returned the expected name with an attributable "
        "first-party excerpt. Every title and affiliation still needs manual review.",
        "An unsuccessful fetch is **not** an extraction failure. An absent expected name "
        "in parsed HTML is **not** automatically an extraction failure either.",
        "Other returned people may be false positives; inspect evidence before counting precision.",
        "Detailed per-site records: results.csv / results.jsonl. "
        "Diagnostic traces: diagnostics/. Redacted response snapshots: snapshots/.",
        "",
    ])
    (out / "report.md").write_text("\n".join(body), encoding="utf-8")


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--worker":
        target = json.loads(sys.argv[2])
        print(json.dumps(worker(target, Path(sys.argv[3])), ensure_ascii=False))
        return 0

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--limit", type=int, default=3,
                        help="Use 3 for the smoke test; 12 after it succeeds")
    parser.add_argument("--timeout", type=int, default=22,
                        help="Hard per-company child-process cap, max 30 seconds")
    args = parser.parse_args()
    if not 1 <= args.timeout <= 30:
        parser.error("--timeout must be between 1 and 30 seconds")
    targets = load_targets(args.csv)
    if not 1 <= args.limit <= len(targets):
        parser.error(f"--limit must be between 1 and {len(targets)}")

    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    (out / "diagnostics").mkdir(exist_ok=True)
    (out / "snapshots").mkdir(exist_ok=True)
    result_path = out / "results.jsonl"
    previous = results_from(result_path)
    print(f"12-company positive-control set, processing first {args.limit} (sequential)", flush=True)
    print(f"Per-company hard limit: {args.timeout}s; saved results reused on restart", flush=True)
    print(f"SSL_CERT_FILE: {os.environ.get('SSL_CERT_FILE', '(not set)')}", flush=True)
    try:
        for i, row in enumerate(targets[:args.limit], 1):
            if row["domain"] in previous:
                print(f"[{i}/{args.limit}] SKIP saved: {row['company']}", flush=True)
                continue
            print(f"[{i}/{args.limit}] START: {row['company']}", flush=True)
            slug = re.sub(r"[^a-z0-9]+", "-", row["domain"].lower()).strip("-")
            snap = out / "snapshots" / slug
            started = time.monotonic()
            try:
                proc = subprocess.run(
                    [sys.executable, str(Path(__file__).resolve()), "--worker",
                     json.dumps(row, ensure_ascii=False), str(snap)],
                    capture_output=True, text=True, timeout=args.timeout,
                    env=os.environ.copy(),
                )
                (out / "diagnostics" / f"{slug}.log").write_text(
                    proc.stderr[-15000:], encoding="utf-8"
                )
                if proc.returncode:
                    record = {**row, "outcome": "worker_error",
                              "error": proc.stderr[-500:], "fetch_ok": False}
                else:
                    record = json.loads(proc.stdout.splitlines()[-1])
            except subprocess.TimeoutExpired as exc:
                std_err = exc.stderr or b""
                if isinstance(std_err, bytes):
                    std_err = std_err.decode(errors="replace")
                (out / "diagnostics" / f"{slug}.log").write_text(
                    std_err[-15000:], encoding="utf-8"
                )
                record = {**row, "outcome": "timeout",
                          "fetch_ok": False, "error": f"worker exceeded {args.timeout}s"}
            except Exception as exc:
                record = {**row, "outcome": "worker_error", "fetch_ok": False,
                          "error": str(exc)}
            record.setdefault("elapsed_s", round(time.monotonic() - started, 2))
            with result_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            previous[row["domain"]] = record
            write_reports(targets, previous, out)
            print(f"[{i}/{args.limit}] {record['outcome']} "
                  f"({record['elapsed_s']}s)", flush=True)
    except KeyboardInterrupt:
        print("Interrupted. Completed results remain saved.", flush=True)
        write_reports(targets, previous, out)
        return 130
    write_reports(targets, previous, out)
    print(f"REPORT: {out / 'report.md'}", flush=True)
    print(f"CSV: {out / 'results.csv'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
