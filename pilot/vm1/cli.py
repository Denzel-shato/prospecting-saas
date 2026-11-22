"""CLI: ``python -m vm1 <run|synthetic|report>``.

* run        live discovery (free keyless sources only) + own-site research on the real network.
* synthetic  pipeline check on FICTIONAL fixtures, fully offline. Never a finding.
* report     regenerate report.md for a finished run, optionally with human labels.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .discovery import ApiClient, DiscoveryBlocked, build_adapters
from .fetch import PoliteFetcher
from .guard import PaidApiBlocked, SpendLedger
from .pipeline import RunConfig, run_pipeline
from .report import write_report

ROOT = Path(__file__).resolve().parent.parent


def _icp(path: str) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _pick_from_run(run_dir: str, names: str | None, domains: str | None):
    from .discovery import Candidate
    rd = Path(run_dir)
    rows = json.loads((rd / "candidates.json").read_text(encoding="utf-8"))
    want_n = [n.strip().casefold() for n in (names or "").split(",") if n.strip()]
    want_d = [d.strip().casefold() for d in (domains or "").split(",") if d.strip()]
    if not want_n and not want_d:
        picked = rows
    else:
        picked, missing = [], []
        for n in want_n:
            hit = [r for r in rows if r["name"].casefold() == n] or [r for r in rows if n in r["name"].casefold()]
            (picked.append(hit[0]) if len(hit) == 1 else missing.append(f"{n!r} ({len(hit)} matches)"))
        for d in want_d:
            hit = [r for r in rows if (r.get("domain") or "").casefold() == d]
            (picked.append(hit[0]) if hit else missing.append(f"{d!r} (not found)"))
        if missing:
            raise SystemExit("could not resolve in candidates.json: " + ", ".join(missing))
    return [Candidate(**r) for r in picked]


def _dev_snapshot_cmd(a) -> int:
    from .snapshot import (RecordingTransport, ReplayAdapter, ReplayFetcher, SnapshotMissing, SnapshotStale,
                           SnapshotStore, capture, check_fresh)
    from .fetch import PinnedTransport
    store = SnapshotStore(a.out if a.cmd == "capture" else a.snapshots)
    if a.cmd == "capture":
        if a.from_run:
            cands = _pick_from_run(a.from_run, a.names, a.domains)
        elif a.manual_csv:
            from .discovery import ManualCsvAdapter
            cands = ManualCsvAdapter(a.manual_csv).discover()
        else:
            raise SystemExit("capture needs --manual-csv or --from-run")
        fetcher = PoliteFetcher(RecordingTransport(PinnedTransport(), store), min_delay=a.min_delay)
        man = capture(cands, fetcher, store, capture_pages=a.capture_pages, label=a.label)
        ok = sum(1 for c in man["companies"] if c["homepage_ok"])
        print(f"captured {len(man['companies'])} companies ({ok} homepages ok) -> {store.root}")
        print("snapshots are LOCAL, REDACTED, third-party page copies: keep them out of git and do not share them.")
        return 0
    try:
        man = check_fresh(store, None if a.allow_stale else a.max_age_days)
    except SnapshotStale as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 5
    fetcher = ReplayFetcher(store, strict=not a.collect_missing)
    cfg = RunConfig(icp=_icp(a.icp), out_dir=Path(a.out), mode="replay", max_candidates=len(man["candidates"]),
                    max_secondary=a.max_secondary,
                    extra={"replay": {"capture_id": man["capture_id"], "captured_at": man["started_at"],
                                      "capture_ended_at": man["ended_at"], "snapshot_dir": str(store.root)}})
    out_root = Path(a.out)
    before = set(out_root.iterdir()) if out_root.exists() else set()
    try:
        result = run_pipeline(cfg, [ReplayAdapter(store)], fetcher, SpendLedger())
    except SnapshotMissing as exc:
        import shutil
        for d in (set(out_root.iterdir()) - before if out_root.exists() else set()):  # no half-finished run left behind
            if d.is_dir() and not (d / "companies.json").exists():
                shutil.rmtree(d, ignore_errors=True)
        print(f"REPLAY FAILED (nothing was fetched or invented): {exc}", file=sys.stderr)
        return 4
    report = write_report(result["run_dir"], None)
    print(f"REPLAY (network disabled) run dir: {result['run_dir']}\nreport:  {report}")
    if fetcher.missing:
        print(f"INCOMPLETE: {len(fetcher.missing)} uncaptured page(s):", file=sys.stderr)
        for u in fetcher.missing:
            print(f"  - {u}", file=sys.stderr)
        return 4
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="vm1", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="live run (free keyless sources only)")
    r.add_argument("--icp", default=str(ROOT / "icp" / "frontend-studio.json"))
    r.add_argument("--out", default=str(ROOT / "runs"))
    r.add_argument("--sources", default="wikidata", help="comma list: wikidata,openstreetmap,manual_csv")
    r.add_argument("--ack-overpass-terms", action="store_true",
                   help="confirm you read the Overpass public-instance policy (needed for openstreetmap)")
    r.add_argument("--manual-csv", help="name,url CSV; labelled MANUAL, excluded from autonomous metrics")
    r.add_argument("--max-candidates", type=int, default=40)
    r.add_argument("--seed", default="vm1-pilot-1")
    r.add_argument("--min-delay", type=float, default=2.0, help="seconds between requests to one host")
    r.add_argument("--labels", help="human labels CSV to include in the report")

    s = sub.add_parser("synthetic", help="offline pipeline check on fictional fixtures")
    s.add_argument("--icp", default=str(ROOT / "icp" / "frontend-studio.json"))
    s.add_argument("--out", default=str(ROOT / "runs"))

    c = sub.add_parser("capture", help="DEV: fetch pages politely and store redacted local snapshots (no findings)")
    c.add_argument("--out", required=True, help="snapshot directory (git-ignored), e.g. snapshots/seven")
    c.add_argument("--manual-csv", help="name,url CSV")
    c.add_argument("--from-run", help="existing run dir whose candidates.json/companies.json supplies the companies")
    c.add_argument("--names", help="comma list of company names to pick from --from-run (case-insensitive)")
    c.add_argument("--domains", help="comma list of domains to pick from --from-run")
    c.add_argument("--capture-pages", type=int, default=8, help="secondary pages stored per company (superset of the 4 fetched in a normal run)")
    c.add_argument("--min-delay", type=float, default=2.0)
    c.add_argument("--label", default="")

    rv = sub.add_parser("replay", help="DEV: re-run the pipeline on captured snapshots with networking disabled")
    rv.add_argument("--snapshots", required=True)
    rv.add_argument("--icp", default=str(ROOT / "icp" / "frontend-studio.json"))
    rv.add_argument("--out", default=str(ROOT / "runs"))
    rv.add_argument("--collect-missing", action="store_true",
                    help="do not abort on an uncaptured page: record every missing page, finish, then exit non-zero")
    rv.add_argument("--max-age-days", type=float, default=30.0)
    rv.add_argument("--allow-stale", action="store_true")
    rv.add_argument("--max-secondary", type=int, default=4)

    rp = sub.add_parser("report", help="regenerate report.md for a run")
    rp.add_argument("--run", required=True)
    rp.add_argument("--labels")

    a = p.parse_args(argv)

    if a.cmd == "report":
        print(write_report(a.run, a.labels))
        return 0

    if a.cmd in ("capture", "replay"):
        return _dev_snapshot_cmd(a)

    ledger = SpendLedger()
    try:
        if a.cmd == "synthetic":
            from .fixture import build_synthetic
            world = ROOT / "fixtures" / "synthetic" / "world.json"
            adapters, fetcher = build_synthetic(world)
            cfg = RunConfig(icp=_icp(a.icp), out_dir=Path(a.out), mode="synthetic_fixture")
        else:
            names = [n for n in a.sources.split(",") if n.strip()]
            if a.manual_csv and "manual_csv" not in names:
                names.append("manual_csv")
            adapters = build_adapters(names, client=ApiClient(), ack_overpass_terms=a.ack_overpass_terms,
                                      manual_csv=a.manual_csv)
            fetcher = PoliteFetcher(min_delay=a.min_delay)
            cfg = RunConfig(icp=_icp(a.icp), out_dir=Path(a.out), mode="live",
                            max_candidates=a.max_candidates, seed=a.seed)
    except PaidApiBlocked as exc:
        print(f"BLOCKED (paid/keyed source refused): {exc}", file=sys.stderr)
        return 2
    except DiscoveryBlocked as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 3

    result = run_pipeline(cfg, adapters, fetcher, ledger)
    labels = getattr(a, "labels", None)
    report = write_report(result["run_dir"], labels)
    man = result["manifest"]
    print(f"run dir: {result['run_dir']}\nreport:  {report}")
    print(f"discovery: {[(d['adapter'], d['status']) for d in man['discovery_status']]}")
    print(f"counts: {man['counts']}  paid spend: ${man['paid_api_spend_usd']:.2f}")
    return 0
