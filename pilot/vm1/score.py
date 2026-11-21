"""Deterministic, documented first-pass relevance score. No ML, no randomness, no hidden inputs.

Every point is traceable to evidence ids. Missing information earns no points and is listed
under ``unknowns``; it is never invented. Thresholds are ARBITRARY starting points that must be
calibrated against human labels; they are not validated.

QUALIFICATION GATE (applies before any tier above "weak" is possible):
  company_type is derived from evidence only:
    agency_studio        self-referential studio/agency (or "we build ... for clients") identity AND
                         >=1 service the company OFFERS to clients (not a tech keyword, feature list,
                         docs page, testimonial or client case study) AND no vendor/enterprise profile
    saas_vendor          >=3 distinct product-vendor signals (trial/demo/account/pricing/docs/platform/
                         customers-at-scale) and no agency identity           -> excluded
    enterprise_software  listed-company wording, or >=2 large-corporation signals, no agency identity
                                                                              -> excluded
    staffing             homepage staffing/recruiting self-description        -> excluded
    unclear              anything else (including mixed agency+vendor wording) -> capped at weak,
                         flagged for manual review. Unknown is never positive evidence.
  Only agency_studio can reach "possible". "strong" additionally needs US evidence, an explicit
  in-band headcount and >=2 distinct offered target services; otherwise it is held at "possible".

Positive rules (max 90 + 5):
  +20 entity_type: studio/agency wording (+12 if only "we build ... for clients" wording)   (source_supported+)
  +6 react, +6 nextjs, +4 typescript, +5 frontend, +5 web_app, +4 custom_software   (cap 25)
  +20 US location (first-party statement and/or dataset record)
  +15 explicit size within ICP band (5-50);  0 if 1-4 or unknown
  + 5 client-work wording (NOT purchase intent; agency_studio only)
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
    company_type: str = "unclear"
    type_evidence_ids: list[str] = field(default_factory=list)
    gate_notes: list[str] = field(default_factory=list)

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


TARGET_SERVICE_TAGS = ("react", "nextjs", "typescript", "frontend", "web_app")
VENDOR_MIN_SIGNALS = 3
ENTERPRISE_MIN_SIGNALS = 2
ENTITY_POINTS = 20
CLIENT_SERVICES_POINTS = 12


def classify_company(evidence: list[Evidence]) -> tuple[str, list[Evidence], list[str]]:
    """Company type from evidence alone. Returns (type, evidence used, human-readable reasons)."""
    staffing = _ok(evidence, "negative:staffing_recruiting")
    ident_strong = _ok(evidence, "entity_type:studio_or_agency") or _ok(evidence, "entity_type:client_services")
    ident_weak = _ok(evidence, "entity_type:consulting_engagements")
    ident = ident_strong or ident_weak
    services = [e for tag in TARGET_SERVICE_TAGS + ("custom_software",) for e in _ok(evidence, f"service:{tag}")]
    vendor = _ok(evidence, "company_type:saas_vendor_signal")
    ent = _ok(evidence, "company_type:enterprise_signal")
    vendor_cats = {e.value for e in vendor}
    ent_cats = {e.value for e in ent}
    big = "listed_company" in ent_cats or len(ent_cats) >= ENTERPRISE_MIN_SIGNALS
    vendorish = len(vendor_cats) >= VENDOR_MIN_SIGNALS
    if staffing:
        return "staffing", staffing, ["homepage describes a staffing/recruiting business"]
    # Only a STRONG identity (self-described studio/agency, or builds-for-clients) can shield a company from the
    # vendor/enterprise exclusions. The weak "firm's consulting engagements" identity never does (Issue #3).
    if big and not ident_strong:
        return "enterprise_software", ent, [f"large/listed-corporation signals {sorted(ent_cats)} and no studio/agency self-description"]
    if vendorish and not ident_strong:
        return "saas_vendor", vendor, [f"product-vendor signals {sorted(vendor_cats)} and no studio/agency self-description"]
    if ident and services and not vendorish and not big:
        return "agency_studio", ident + services, ["self-described service provider offering target services to clients"]
    reasons = []
    if not ident:
        reasons.append("no self-referential studio/agency (or build-for-clients) wording")
    if not services:
        reasons.append("no target service described as offered to clients")
    if ident and (vendorish or big):
        reasons.append(f"mixed identity: agency wording alongside vendor/enterprise signals {sorted(vendor_cats | ent_cats)}")
    if len(vendor_cats) in (1, 2) and not ident:
        reasons.append(f"some product-vendor signals {sorted(vendor_cats)}")
    return "unclear", ident + services + vendor + ent, reasons


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

    ctype, type_evs, type_reasons = classify_company(evidence)
    res.company_type = ctype
    res.type_evidence_ids = _ids(type_evs)
    if ctype in ("saas_vendor", "enterprise_software"):
        exclude(ctype, type_evs, "; ".join(type_reasons))

    if res.hard_exclusions:
        return res

    def add(rule: str, pts: int, evs: list[Evidence], note: str = "") -> None:
        res.components.append({"rule": rule, "points": pts, "evidence_ids": _ids(evs), "note": note})

    ent = _ok(evidence, "entity_type:studio_or_agency")
    cs = _ok(evidence, "entity_type:client_services")
    eng = _ok(evidence, "entity_type:consulting_engagements")
    if ent:
        add("entity_type: studio/agency wording", ENTITY_POINTS, ent)
    elif cs:
        add("entity_type: builds-for-clients wording (no studio/agency noun)", CLIENT_SERVICES_POINTS, cs)
    elif eng:
        add("entity_type: firm's own consulting/client engagements (weak identity)", CLIENT_SERVICES_POINTS, eng)
    else:
        res.unknowns.append("entity_type: no self-referential studio/agency description found")

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

    if _ok(evidence, "signal:client_work") and ctype == "agency_studio":
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

    # ---- qualification gate: business-type fit comes before any secondary signal ---------------
    if ctype != "agency_studio":
        res.gate_notes += type_reasons
        res.flags.append(f"manual_review: company type '{ctype}' not established as a client-services "
                         f"agency/studio; capped at weak ({'; '.join(type_reasons)})")
        cap = TIER_POSSIBLE - 1
        if res.total > cap:
            add(f"qualification gate: type '{ctype}' unverified, capped at {cap}", cap - res.total,
                type_evs, "US location, technology mentions, size and named people cannot promote an "
                          "unverified agency identity")
            res.total = cap
        res.tier = "weak"
    elif res.tier == "strong":
        offered_tags = {t for t in TARGET_SERVICE_TAGS if _ok(evidence, f"service:{t}")}
        missing = []
        if not us:
            missing.append("US presence not evidenced")
        if not (isinstance(size, int) and lo <= size <= hi):
            missing.append("no explicit in-band headcount")
        if len(offered_tags) < 2:
            missing.append("fewer than 2 offered target services")
        if missing:
            res.tier = "possible"
            res.gate_notes.append("held at possible: " + "; ".join(missing))
            res.flags.append("strong_gate: score >= strong threshold but " + "; ".join(missing))
    return res
