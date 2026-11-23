"""Offline old-vs-new Engine #2 ordering comparison. No network, no crawling, no live data.

OLD = the worldwide ICP without the specificity vocabulary (exactly the previous ordering: priority, breadth, hash).
NEW = the shipped worldwide ICP. The pool is FICTIONAL (.example) and built from the wording patterns named in the
root-cause evidence. Archetype labels are the author's construction, NOT human ground truth and NOT lead quality;
the point is to show how ordering reacts to wording, across many hash seeds. Usage: python3 scripts/engine2_specificity_before_after.py
"""
from __future__ import annotations

import copy
import json
import statistics
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from vm1.policy import load_policy  # noqa: E402
from vm1.prequalify import rank_pool  # noqa: E402

raw = json.loads((ROOT / "icp" / "frontend-studio-worldwide.json").read_text())
NEW = load_policy(raw)
legacy = copy.deepcopy(raw)
for k in ("generic_terms", "ambiguous_negative_terms", "service_context_terms"):
    legacy["prequalify"].pop(k)
OLD = load_policy(legacy)

H = {"directory_service_hint": True}  # every record from the "Software Development" category query carries this
# (archetype, tagline, service labels, extra attrs)
SPEC = [
    ("software_studio", "Custom software and app development for startups", ["Software Development", "Web Development"], {}),
    ("software_studio", "SaaS product development studio", ["Software Development"], {}),
    ("software_studio", "Product studio building web apps for scale-ups", ["Software Development", "UI/UX Design"], {"directory_frontend_hint": True}),
    ("software_studio", "Software development company for fintech and ecommerce teams", ["Software Development"], {}),
    ("software_studio", "Engineering studio: cloud and mobile products for clients", ["Software Development", "Consulting"], {}),
    ("software_studio", "Design and development partner for digital products", ["Web Development", "Software Development"], {}),
]
GENERIC = [("generic_web_agency", "", ["Consulting", "Web Design", "Web Development", "Digital Agency"], {}) for _ in range(5)] + [
    ("generic_web_agency", "Full-service digital agency", ["Web Design", "Web Development", "Consulting"], {}),
    ("generic_web_agency", "Award-winning web design agency", ["Web Design", "Branding", "Web Development"], {"directory_frontend_hint": True}),
    ("generic_web_agency", "Your consulting and web development partner", ["Consulting", "Web Development", "Web Design"], {}),
]
OTHER = [
    ("marketing_agency", "Social media and SEO growth agency", ["SEO", "Social Media Marketing", "Web Design"], {"directory_marketing_focus_hint": True}),
    ("marketing_agency", "Performance marketing and branding studio", ["Advertising", "Web Development"], {"directory_marketing_focus_hint": True}),
    ("saas_vendor", "The SaaS platform for project teams", ["Software Development"], {}),
    ("saas_vendor", "Cloud-based enterprise marketplace", ["Software Development"], {}),
    ("saas_vendor", "Leading fintech and ecommerce provider", ["Software Development"], {}),
    ("unknown_text", "", [], {}),
    ("unknown_text", "", [], {}),
]
ROWS = SPEC + GENERIC + OTHER
POOL = []
for i, (arch, tag, svc, extra) in enumerate(ROWS):
    POOL.append(SimpleNamespace(domain=f"c{i:02d}.example", archetype=arch,
                                attrs={**H, "directory_tagline": tag, "directory_services": svc, **extra}))
SEEDS = [f"seed-{i}" for i in range(50)]
TOP = 8


def run(policy):
    per_arch_rank, per_arch_top = {}, {}
    first = None
    for seed in SEEDS:
        order = rank_pool(POOL, seed, policy)
        first = first or [(r.candidate.domain, r.candidate.archetype) for r in order[:TOP]]
        for pos, r in enumerate(order, 1):
            per_arch_rank.setdefault(r.candidate.archetype, []).append(pos)
            if pos <= TOP:
                per_arch_top[r.candidate.archetype] = per_arch_top.get(r.candidate.archetype, 0) + 1
    return per_arch_rank, per_arch_top, first


old, new = run(OLD), run(NEW)
print(f"pool={len(POOL)} fictional records, {len(SEEDS)} hash seeds, top-{TOP} window. Archetypes are synthetic labels.\n")
print(f"{'archetype':20s} {'n':>2s} | {'mean rank old':>13s} {'new':>6s} | {'top-%d share old' % TOP:>15s} {'new':>6s}")
for arch in sorted({p.archetype for p in POOL}):
    n = sum(p.archetype == arch for p in POOL)
    mo, mn = statistics.mean(old[0][arch]), statistics.mean(new[0][arch])
    so, sn = old[1].get(arch, 0) / (len(SEEDS) * TOP), new[1].get(arch, 0) / (len(SEEDS) * TOP)
    print(f"{arch:20s} {n:2d} | {mo:13.1f} {mn:6.1f} | {so:15.0%} {sn:6.0%}")
print(f"\nseed-0 top-{TOP}  OLD:", [a for _, a in old[2]])
print(f"seed-0 top-{TOP}  NEW:", [a for _, a in new[2]])
print("\nseed-0 NEW top-3 explanations:")
for r in rank_pool(POOL, SEEDS[0], NEW)[:3]:
    t = r.tie_break()
    print(" ", r.candidate.domain, "rank_score", t.get("rank_score"), "specific", t.get("matched_specific"), "generic", t.get("matched_generic"))
