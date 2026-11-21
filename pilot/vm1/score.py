"""Deterministic, documented first-pass relevance score. No ML, no randomness, no hidden inputs.

Every point is traceable to evidence ids. Missing information earns no points and is listed
under ``unknowns``; it is never invented. Thresholds are ARBITRARY starting points that must be
calibrated against human labels; they are not validated.

Positive rules (max 90 + 5):
  +20 entity_type: studio/agency/software-dev-company wording        (source_supported+)
  +6 react, +6 nextjs, +4 typescript, +5 frontend, +5 web_app, +4 custom_software   (cap 25)
  +20 US location (first-party statement and/or dataset record)
  +15 explicit size within ICP band (5-50);  0 if 1-4 or unknown
  + 5 client-work wording (NOT purchase intent)
  + 5 publicly named decision-maker in a target role (first-party site)
Negative rules:
  -10 explicit size 51-250 (above band)
  -15 staff-augmentation / "hire developers" model wording
  -10 "global consultancy" wording
  -10 staffing/recruiting wording on a secondary page (review)
Hard exclusions (score = None, tier = excluded):
  staffing_recruiting (homepage self-description), size > 250, non_us_only (non-US evidence and
  no US evidence), non_first_party_domain, unreachable (homepage not fetched).
"not_researchable" (robots disallowed) is ineligible but is not an "exclusion violation".
Tiers: strong >= 65, possible 40-64, weak < 40.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .evidence import ASSERTABLE_LEVELS, CORROBORATED, Evidence
from .people import DecisionMaker

SERVICE_POINTS = {"react": 6, "nextjs": 6, "typescript": 4, "frontend": 5, "web_app": 5,
                  "custom_software": 4}
SERVICE_CAP = 25
TIER_STRONG = 65
TIER_POSSIBLE = 40
EXCLUDED = "excluded"
NOT_RESEARCHABLE = "not_researchable"


@dataclass
class ScoreResult:
    total: int | None
    tier: str
    components: list[dict] = field(default_factory=list)
    hard_exclusions: list[dict] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def explain(self) -> str:
        if self.hard_exclusions:
            return "; ".join(f"EXCLUDED: {e['rule']}" for e in self.hard_exclusions)
        parts = [f"{c['points']:+d} {c['rule']}" for c in self.components]
        return "; ".join(parts) or "no scoring evidence"


def _ok(evidence: list[Evidence], claim: str) -> list[Evidence]:
    return [e for e in evidence if e.claim_type == claim and e.level in ASSERTABLE_LEVELS]


def _ids(evs: list[Evidence]) -> list[str]:
    return [e.id for e in evs]


def score_company(
    evidence: list[Evidence],
    decision_makers: list[DecisionMaker],
    *,
    homepage_ok: bool,
    robots_blocked: bool = False,
    first_party_domain: bool = True,
    size_band: tuple[int, int] = (5, 50),
    size_hard_max: int = 250,
) -> ScoreResult:
    lo, hi = size_band
    res = ScoreResult(total=None, tier=EXCLUDED)

    def exclude(rule: str, evs: list[Evidence] | None = None, detail: str = "") -> None:
        res.hard_exclusions.append({"rule": rule, "evidence_ids": _ids(evs or []), "detail": detail})

    if not first_party_domain:
        exclude("non_first_party_domain", detail="directory/social/marketplace domain, not a company site")
    if robots_blocked:
        res.tier = NOT_RESEARCHABLE
        res.flags.append("robots_disallowed: cannot research this site; no content fetched")
        return res
    if not homepage_ok:
        exclude("unreachable", detail="homepage could not be fetched")

    staffing = _ok(evidence, "negative:staffing_recruiting")
    if staffing:
        exclude("staffing_recruiting", staffing, "homepage describes a staffing/recruiting business")

    size_ev = _ok(evidence, "size:employees")
    size = size_ev[0].value if size_ev else None
    if isinstance(size, int) and size > size_hard_max:
        exclude("size_over_250", size_ev, f"explicit count {size} exceeds hard max {size_hard_max}")

    us = _ok(evidence, "location:us")
    non_us = _ok(evidence, "location:non_us")
    if non_us and not us:
        exclude("non_us_only", non_us, "non-US location evidence and no US evidence")
    elif non_us and us:
        res.flags.append("conflict: both US and non-US location evidence; review manually")

    if res.hard_exclusions:
        return res

    def add(rule: str, pts: int, evs: list[Evidence], note: str = "") -> None:
        res.components.append({"rule": rule, "points": pts, "evidence_ids": _ids(evs), "note": note})

    ent = _ok(evidence, "entity_type:studio_or_agency")
    if ent:
        add("entity_type: studio/agency wording", 20, ent)
    else:
        res.unknowns.append("entity_type: no studio/agency self-description found")

    svc_total, svc_evs = 0, []
    for tag, pts in SERVICE_POINTS.items():
        evs = _ok(evidence, f"service:{tag}")
        if evs:
            svc_total += pts
            svc_evs += evs
            add(f"service: {tag}", pts, evs)
    if svc_total > SERVICE_CAP:
        add("service cap adjustment", SERVICE_CAP - svc_total, [], f"services capped at {SERVICE_CAP}")
    if not svc_evs:
        res.unknowns.append("services: none of the target service terms found")

    if us:
        corro = any(e.level == CORROBORATED for e in us)
        add("location: US supported", 20, us, "corroborated by independent record" if corro else "")
    else:
        res.unknowns.append("location: US presence not evidenced")

    if isinstance(size, int):
        if lo <= size <= hi:
            add(f"size: explicit {size} within {lo}-{hi}", 15, size_ev, size_ev[0].notes)
        elif size > hi:
            add(f"size: explicit {size} above {hi}", -10, size_ev, "above ICP band, below hard max")
        else:
            add(f"size: explicit {size} below {lo}", 0, size_ev, "micro-team; no points")
    else:
        res.unknowns.append("size: no single explicit headcount (not guessed)")

    if _ok(evidence, "signal:client_work"):
        add("signal: client-work wording (not purchase intent)", 5, _ok(evidence, "signal:client_work"))
    if decision_makers:
        add("decision-maker named on first-party site", 5, [])
    else:
        res.unknowns.append("decision-maker: none publicly named on fetched pages")

    for claim, rule, pts in (("negative:staff_augmentation", "negative: staff-augmentation model wording", -15),
                             ("negative:global_consultancy", "negative: global-consultancy wording", -10),
                             ("negative:staffing_mention", "negative: staffing wording on secondary page", -10)):
        evs = _ok(evidence, claim)
        if evs:
            add(rule, pts, evs)

    res.total = max(0, min(100, sum(c["points"] for c in res.components)))
    res.tier = "strong" if res.total >= TIER_STRONG else "possible" if res.total >= TIER_POSSIBLE else "weak"
    return res
