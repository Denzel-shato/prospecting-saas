"""Discovery-only run: Engine #1 without any company-website research.

Calls only the chosen keyless discovery adapters (bounded, rate-limited, SSRF-guarded as always), de-duplicates by
canonical domain and writes ``pool.json`` + ``manifest.json``. It never fetches a company website, never ranks for
research and never scores or drafts, so the smallest live validation of discovery quality costs only the adapters'
own bounded API requests ($0) and does not crawl any studio's site. The outputs feed ``discovery-benchmark``.
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from .discovery import AUTOMATED, Adapter, Candidate, DiscoveryBlocked
from .guard import SpendLedger
from .pipeline import dedup
from .policy import IcpPolicy


def discover_only(adapters: list[Adapter], out_dir: str | Path, policy: IcpPolicy, label: str = "discovery") -> dict:
    ledger = SpendLedger()
    discovered: list[Candidate] = []
    status: list[dict] = []
    for ad in adapters:
        st = {"adapter": ad.name, "cost_class": ad.cost_class, "terms_note": ad.terms_note, "license": ad.license_note}
        try:
            got = ad.discover()
            st.update(status="ok", count=len(got))
            if getattr(ad, "run_note", ""):
                st["note"] = ad.run_note
            if getattr(ad, "yield_stats", None):
                st["yield"] = dict(ad.yield_stats)
            discovered.extend(got)
        except DiscoveryBlocked as exc:
            st.update(status="blocked", count=0, reason=str(exc))
        status.append(st)
        ledger.record(ad.name, 0.0, "keyless adapter")
    pool, rejected, possible_same = dedup(discovered)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{label}"
    out = Path(out_dir) / run_id
    out.mkdir(parents=True, exist_ok=True)
    manifest = {"mode": "discovery_only", "run_id": run_id, "icp": policy.id, "policy_version": policy.policy_version,
                "policy_digest": policy.digest, "paid_api_spend_usd": ledger.total_usd,
                "research": "none: no company website was fetched",
                "discovery_status": status,
                "counts": {"discovered_raw": len(discovered), "after_dedup_pool": len(pool),
                           "raw_automated": sum(c.discovery_method == AUTOMATED for c in discovered),
                           "duplicates_and_rejects": len(rejected)},
                "possible_same_company": possible_same}
    for name, data in (("manifest.json", manifest), ("pool.json", [asdict(c) for c in pool]),
                       ("rejected.json", rejected)):
        (out / name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"run_dir": out, "manifest": manifest, "pool": pool}
