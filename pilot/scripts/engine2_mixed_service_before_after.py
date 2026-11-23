"""Offline old-vs-new Engine #2 ordering with the SAME pool and seed. No network, no crawling, no paid APIs.

OLD = worldwide ICP without `service_line_terms` (previous commit's ordering). NEW = shipped ICP.
Usage: python3 scripts/engine2_mixed_service_before_after.py [--pool runs/pickanagency-candidates-rich.json] [--seed vm1-pilot-1]
The real pool file is gitignored; without --pool (or if absent) a FICTIONAL pool is used and labelled as such.
Accepted pool shapes: a list, or {"candidates": [...]}; each record flat or with "attrs", using domain/url/website,
tagline/directory_tagline, services/directory_services, description. Fields are used as given; nothing is inferred.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vm1.policy import load_policy  # noqa: E402
from vm1.prequalify import rank_pool  # noqa: E402

raw = json.loads((ROOT / "icp" / "frontend-studio-worldwide.json").read_text())
NEW = load_policy(raw)
legacy = copy.deepcopy(raw)
legacy["prequalify"].pop("service_line_terms")
OLD = load_policy(legacy)


def load_pool(path: Path):
    data = json.loads(path.read_text())
    rows = data.get("candidates", data.get("results", [])) if isinstance(data, dict) else data
    pool = []
    for r in rows:
        a = {**r, **(r.get("attrs") or {})}
        dom = a.get("domain") or urlsplit(a.get("url") or a.get("website") or "").netloc.removeprefix("www.")
        svc = a.get("directory_services") or a.get("services") or []
        svc = [s for s in svc if isinstance(s, str)]
        tag = a.get("directory_tagline") or a.get("tagline") or ""
        attrs = {"directory_service_hint": a.get("directory_service_hint", True), "directory_tagline": tag,
                 "directory_services": svc, "description": a.get("description") or "",
                 **{k: a[k] for k in ("directory_frontend_hint", "directory_software_focus_hint",
                                      "directory_marketing_focus_hint", "directory_vendor_hint", "listed_on_exchange", "employees") if k in a}}
        if dom:
            pool.append(SimpleNamespace(domain=dom, attrs=attrs))
    return pool


def fictional_pool():
    H = {"directory_service_hint": True}
    spec = [("mixed-dev-a", "", ["Custom Software Development", "Social Media Marketing"]),
            ("mixed-dev-b", "", ["Custom Software Development", "Web Development", "Social Media Marketing"]),
            ("software-only", "Custom software and app development studio", ["Software Development"]),
            ("generic-web", "", ["Consulting", "Web Design", "Web Development", "Digital Agency"]),
            ("marketing-only", "Social media growth agency", ["Social Media Marketing", "SEO"]),
            ("decoy-tagline", "Social media growth agency", ["Custom Software Development", "Social Media Marketing"]),
            ("saas-vendor", "The SaaS platform for project teams", ["Software Development", "Social Media Marketing"]),
            ("no-metadata", "", [])]
    return [SimpleNamespace(domain=f"{n}.example", attrs={**H, "directory_tagline": t, "directory_services": s}) for n, t, s in spec]


ap = argparse.ArgumentParser()
ap.add_argument("--pool", default=str(ROOT / "runs" / "pickanagency-candidates-rich.json"))
ap.add_argument("--seed", default="vm1-pilot-1")
args = ap.parse_args()
path = Path(args.pool)
real = path.is_file()
pool = load_pool(path) if real else fictional_pool()
print(f"pool: {'REAL ' + str(path) if real else 'FICTIONAL (real file not found)'}  n={len(pool)}  seed={args.seed}\n")
old = {r.candidate.domain: (i, r) for i, r in enumerate(rank_pool(pool, args.seed, OLD), 1)}
new = {r.candidate.domain: (i, r) for i, r in enumerate(rank_pool(pool, args.seed, NEW), 1)}
print(f"{'domain':34s} old->new  score(old->new)  reason")
for dom, (n_rank, n_row) in sorted(new.items(), key=lambda kv: kv[1][0]):
    o_rank, o_row = old[dom]
    ev = n_row.evidence
    why = ""
    if ev and ev.service_line_neutralised:
        why = f"service-line label neutral beside {list(ev.specific)}"
    elif o_rank != n_rank:
        why = "relative (others moved)"
    mark = f"{o_rank - n_rank:+d}" if o_rank != n_rank else "="
    print(f"{dom:34s} {o_rank:3d}->{n_rank:<3d} {mark:>4s}  {o_row.rank_score:>3}->{n_row.rank_score:<3}  {why}")
