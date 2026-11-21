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

    rp = sub.add_parser("report", help="regenerate report.md for a run")
    rp.add_argument("--run", required=True)
    rp.add_argument("--labels")

    a = p.parse_args(argv)

    if a.cmd == "report":
        print(write_report(a.run, a.labels))
        return 0

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
