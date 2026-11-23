"""python3 -m vm1.e6v2_audit [--source runs/engine6-independent-20] [--labels benchmarks/...csv] --out NEW_DIR"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .audit import run_audit, write_outputs

PILOT = Path(__file__).resolve().parents[2]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vm1.e6v2_audit", description="Offline V2 passage coverage audit.")
    ap.add_argument("--source", type=Path, default=PILOT / "runs" / "engine6-independent-20")
    ap.add_argument("--labels", type=Path, default=PILOT / "benchmarks" / "engine6-independent-20.csv")
    ap.add_argument("--out", type=Path, required=True, help="NEW output directory (must not contain files)")
    args = ap.parse_args(argv)
    try:
        rows = run_audit(args.source, args.labels)
        md, csv_path = write_outputs(rows, args.source, args.out)
    except (OSError, ValueError, KeyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"wrote {md} and {csv_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
