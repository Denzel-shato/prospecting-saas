"""Smoke CLI: python3 -m vm1.e6v2_workflow --snapshot-dir DIR --company-key KEY --mock-response FILE.json"""

from __future__ import annotations

import argparse
import json
import sys

from ..ai import MockProvider
from .workflow import load_snapshots, run_offline


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vm1.e6v2_workflow", description="Offline Engine #6 V2 workflow (mock AI only).")
    ap.add_argument("--snapshot-dir", required=True, help="saved snapshot store (no network is used)")
    ap.add_argument("--company-key", required=True)
    ap.add_argument("--company-name", default=None)
    ap.add_argument("--mock-response", required=True, help="JSON file: the scripted mock model output")
    args = ap.parse_args(argv)
    try:
        with open(args.mock_response, encoding="utf-8") as fh:
            scripted = json.load(fh)
        snaps = load_snapshots(args.snapshot_dir)
        result = run_offline(snaps, MockProvider([scripted]), args.company_key, args.company_name)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result.to_dict(), indent=2, sort_keys=True))
    return 1 if result.error else 0


if __name__ == "__main__":
    sys.exit(main())
