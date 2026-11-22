"""Deterministic, policy-driven qualification and first-pass relevance score (Issue #5).

No ML, no randomness, no hidden inputs. Every point is traceable to evidence ids. Missing information earns no
points and is listed under ``unknowns``; it is never invented. Thresholds are ARBITRARY starting points that must be
calibrated against human labels; they are not validated, for any profile.

TWO LAYERS
  universal checks (policy cannot change)   homepage reachable, first-party domain, robots.txt respected,
                                             only assertable evidence levels (source_supported/corroborated/
                                             user_verified) ever score
  ICP policy (vm1.policy.IcpPolicy)          what the target company is, which capabilities count and how much,
                                             geography, size, exclusions, decision-maker roles, tier thresholds

QUALIFICATION GATE (applies before any tier above "weak" is possible), generic over the policy:
  The company type is derived from evidence only and is one of
    <target type id>   a STRONG or WEAK identity evidence rule matched AND >= min_capabilities capabilities are
                       evidenced AND no type profile (vendor/enterprise/competitor...) is matched
    <screen type>      a screen claim is present (e.g. staffing)                     -> excluded
    <profile id>       a type profile matched and no strong identity shields it      -> excluded
    unclear            anything else (including mixed identity + vendor wording)     -> capped at weak,
                       flagged for manual review. Unknown is never positive evidence.
  Only the target type can reach "possible". "strong" additionally needs whatever policy.strong_requirements lists
  (geography, in-band explicit headcount, minimum offered capabilities); otherwise it is held at "possible".
  A WEAK identity rule can establish the target type but can never shield a company from a type profile.

The frontend-studio baseline policy (icp/frontend-studio.json) reproduces the pre-Issue-#5 numbers exactly; that is
verified by differential tests against a frozen copy of commit 516c9f4 (tests/reference/).

Hard exclusions (score = None, tier = excluded): policy screens, size > hard max, non-target geography only,
matched type profiles, plus the universal non_first_party_domain and unreachable. "not_researchable" (robots
disallowed) is ineligible but is not an "exclusion violation".
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from functools import lru_cache

from .evidence import ASSERTABLE_LEVELS, CORROBORATED, Evidence
from .people import DecisionMaker
from .policy import IcpPolicy, baseline_policy, load_policy

# Baseline (frontend-studio) tier thresholds, kept for callers that import them. policy.tiers is authoritative;
# a test pins these to the baseline policy file.
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
    policy_id: str = ""
    policy_version: str = ""
    criteria: list[dict] = field(default_factory=list)

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


def _first_ok(evidence: list[Evidence], rules) -> tuple[object, list[Evidence]] | None:
    """First identity rule (in policy order) whose evidence is present and, for distinct-signal rules, diverse enough."""
    for r in rules:
        evs = _ok(evidence, r.claim)
        if evs and len({e.value for e in evs}) >= r.min_distinct_values:
            return r, evs
    return None


def classify_company(evidence: list[Evidence], policy: IcpPolicy | None = None) -> tuple[str, list[Evidence], list[str]]:
    """Company type from evidence alone, under a policy. Returns (type id, evidence used, human-readable reasons)."""
    pol = policy or baseline_policy()
    t = pol.target_type
    strong = _first_ok(evidence, [r for r in t.identity if r.strength == "strong"])
    weak = _first_ok(evidence, [r for r in t.identity if r.strength == "weak"])
    ident_strong = strong[1] if strong else []
    ident = ident_strong or (weak[1] if weak else [])
    services = [e for c in t.capabilities for e in _ok(evidence, c.claim)]
    n_caps = sum(1 for c in t.capabilities if _ok(evidence, c.claim))

    for sc in pol.screens:
        hit = _ok(evidence, sc.claim)
        if hit:
            return sc.type_id, hit, [sc.detail]
    prof = []
    for p in pol.type_profiles:
        evs = _ok(evidence, p.claim)
        cats = {e.value for e in evs}
        hit = len(cats) >= p.min_distinct_values or bool(cats & set(p.any_value))
        prof.append((p, evs, cats, hit))
    # Only a STRONG identity can shield a company from a type exclusion; a weak one never does (Issue #3).
    for p, evs, cats, hit in prof:
        if hit and not (p.shielded_by_strong_identity and ident_strong):
            return p.id, evs, [p.reason_template.format(values=sorted(cats))]
    blocked = any(hit for _, _, _, hit in prof)
    if ident and n_caps >= t.min_capabilities and not blocked:
        return t.id, ident + services, [t.qualified_reason]
    reasons = []
    if not ident:
        reasons.append(t.identity_missing_reason)
    if n_caps < t.min_capabilities:
        reasons.append(t.capabilities_missing_reason)
    if ident and blocked:
        union = sorted(set().union(*[cats for _, _, cats, _ in prof]))
        reasons.append(t.mixed_identity_template.format(values=union))
    if not ident:
        for p, _evs, cats, _hit in prof:
            if p.partial_note_template and 0 < len(cats) < p.min_distinct_values:
                reasons.append(p.partial_note_template.format(values=sorted(cats)))
    return "unclear", ident + services + [e for _, evs, _, _ in reversed(prof) for e in evs], reasons


@lru_cache(maxsize=64)
def _baseline_sized(band: tuple, hard_max: int) -> IcpPolicy:
    return baseline_policy().with_size(band, hard_max)


def score_company(
    evidence: list[Evidence],
    decision_makers: list[DecisionMaker],
    *,
    homepage_ok: bool,
    robots_blocked: bool = False,
    first_party_domain: bool = True,
    size_band: tuple[int, int] = (5, 50),
    size_hard_max: int = 250,
    policy: IcpPolicy | dict | str | None = None,
) -> ScoreResult:
    """Compatibility entry point. Without ``policy`` it scores under the frontend-studio baseline (optionally with a
    different size band), which is the pre-Issue-#5 behavior."""
    if policy is None:
        base = baseline_policy()
        pol = base if (tuple(size_band), size_hard_max) == (base.size.band, base.size.hard_max) \
            else _baseline_sized(tuple(size_band), size_hard_max)
    else:
        pol = load_policy(policy)
    return qualify_company(evidence, decision_makers, pol, homepage_ok=homepage_ok, robots_blocked=robots_blocked,
                           first_party_domain=first_party_domain)


def qualify_company(
    evidence: list[Evidence],
    decision_makers: list[DecisionMaker],
    policy: IcpPolicy,
    *,
    homepage_ok: bool,
    robots_blocked: bool = False,
    first_party_domain: bool = True,
) -> ScoreResult:
    pol = policy
    t = pol.target_type
    lo, hi = pol.size.band
    res = ScoreResult(total=None, tier=EXCLUDED, policy_id=pol.id, policy_version=pol.policy_version)

    def crit(name: str, status: str, detail: str, ids: list[str] | None = None) -> None:
        res.criteria.append({"criterion": name, "status": status, "detail": detail, "evidence_ids": ids or []})

    def exclude(rule: str, evs: list[Evidence] | None = None, detail: str = "") -> None:
        res.hard_exclusions.append({"rule": rule, "evidence_ids": _ids(evs or []), "detail": detail})
        crit(f"exclusion:{rule}", "excluded", detail or rule, _ids(evs or []))

    if not first_party_domain:
        exclude("non_first_party_domain", detail="directory/social/marketplace domain, not a company site")
    if robots_blocked:
        res.tier = NOT_RESEARCHABLE
        res.flags.append("robots_disallowed: cannot research this site; no content fetched")
        crit("robots", "blocked", "robots.txt disallows fetching; nothing was researched")
        return res
    if not homepage_ok:
        exclude("unreachable", detail="homepage could not be fetched")

    for sc in pol.screens:
        hit = _ok(evidence, sc.claim)
        if hit:
            exclude(sc.rule, hit, sc.detail)

    size_ev = _ok(evidence, "size:employees")
    size = size_ev[0].value if size_ev else None
    if isinstance(size, int) and size > pol.size.hard_max:
        exclude(f"size_over_{pol.size.hard_max}", size_ev, f"explicit count {size} exceeds hard max {pol.size.hard_max}")

    us: list[Evidence] = []
    if pol.geography.countries:
        us = _ok(evidence, "location:us")
        non_us = _ok(evidence, "location:non_us")
        if non_us and not us:
            exclude("non_us_only", non_us, "non-US location evidence and no US evidence")
        elif non_us and us:
            res.flags.append("conflict: both US and non-US location evidence; review manually")

    ctype, type_evs, type_reasons = classify_company(evidence, pol)
    res.company_type = ctype
    res.type_evidence_ids = _ids(type_evs)
    if ctype in {p.id for p in pol.type_profiles}:
        exclude(ctype, type_evs, "; ".join(type_reasons))

    if res.hard_exclusions:
        return res

    def add(rule: str, pts: int, evs: list[Evidence], note: str = "") -> None:
        res.components.append({"rule": rule, "points": pts, "evidence_ids": _ids(evs), "note": note})

    # ---- identity -----------------------------------------------------------------------------------------------
    first = _first_ok(evidence, t.identity)
    if first:
        rule, evs = first
        add(rule.rule, rule.points, evs)
        crit("identity", "met", f"{rule.rule} ({rule.strength} identity)", _ids(evs))
    else:
        res.unknowns.append(t.identity_missing_unknown)
        crit("identity", "unknown", t.identity_missing_reason)

    # ---- capabilities --------------------------------------------------------------------------------------------
    svc_total, svc_evs, found = 0, [], []
    for cap in t.capabilities:
        evs = _ok(evidence, cap.claim)
        if evs:
            svc_total += cap.points
            svc_evs += evs
            found.append(cap.id)
            add(f"{t.capability_rule_prefix}{cap.id}", cap.points, evs)
    if svc_total > t.capability_cap:
        add(f"{t.capability_rule_prefix.rstrip(': ')} cap adjustment", t.capability_cap - svc_total, [],
            f"{t.capability_noun} capped at {t.capability_cap}")
    if not svc_evs:
        res.unknowns.append(t.capabilities_missing_unknown)
        crit("capabilities", "unknown", t.capabilities_missing_reason)
    else:
        status = "met" if len(found) >= t.min_capabilities else "not_met"
        crit("capabilities", status, f"evidenced {found} (policy needs >= {t.min_capabilities})", _ids(svc_evs))

    # ---- geography -----------------------------------------------------------------------------------------------
    if pol.geography.countries:
        if us:
            corro = any(e.level == CORROBORATED for e in us)
            add("location: US supported", pol.geography.points, us, "corroborated by independent record" if corro else "")
            crit("geography", "met", "US location supported" + (" (corroborated by an independent record)" if corro else ""), _ids(us))
        else:
            res.unknowns.append("location: US presence not evidenced")
            crit("geography", "unknown", "US presence not evidenced")

    # ---- size ----------------------------------------------------------------------------------------------------
    if isinstance(size, int):
        if lo <= size <= hi:
            add(f"size: explicit {size} within {lo}-{hi}", pol.size.in_band_points, size_ev, size_ev[0].notes)
            crit("size", "met", f"explicit headcount {size} within the {lo}-{hi} band", _ids(size_ev))
        elif size > hi:
            add(f"size: explicit {size} above {hi}", pol.size.above_band_points, size_ev, "above ICP band, below hard max")
            crit("size", "not_met", f"explicit headcount {size} is above the {lo}-{hi} band", _ids(size_ev))
        else:
            add(f"size: explicit {size} below {lo}", pol.size.below_band_points, size_ev, "micro-team; no points")
            crit("size", "not_met", f"explicit headcount {size} is below the {lo}-{hi} band", _ids(size_ev))
    else:
        res.unknowns.append("size: no single explicit headcount (not guessed)")
        crit("size", "unknown", "no single explicit headcount was found (never guessed)")

    # ---- bonuses, decision makers, penalties -----------------------------------------------------------------------
    for b in pol.bonuses:
        evs = _ok(evidence, b.claim)
        if evs and (not b.requires_target_type or ctype == t.id):
            add(b.rule, b.points, evs)
    dms = [d for d in decision_makers if d.role_class in pol.decision_makers.role_classes]
    if dms:
        add("decision-maker named on first-party site", pol.decision_makers.points, [])
        crit("decision_makers", "met", f"{len(dms)} publicly named person(s) in target roles")
    else:
        res.unknowns.append("decision-maker: none publicly named on fetched pages")
        crit("decision_makers", "unknown", "no person in a target role is publicly named on the fetched pages")
    for p in pol.penalties:
        evs = _ok(evidence, p.claim)
        if evs:
            add(p.rule, p.points, evs)

    res.total = max(0, min(100, sum(c["points"] for c in res.components)))
    res.tier = "strong" if res.total >= pol.tiers.strong else "possible" if res.total >= pol.tiers.possible else "weak"

    # ---- qualification gate: business-type fit comes before any secondary signal -----------------------------------
    if ctype != t.id:
        res.gate_notes += type_reasons
        res.flags.append(f"manual_review: company type '{ctype}' not established as a {t.label}; "
                         f"capped at weak ({'; '.join(type_reasons)})")
        cap = pol.tiers.possible - 1
        if res.total > cap:
            add(f"qualification gate: type '{ctype}' unverified, capped at {cap}", cap - res.total, type_evs, t.gate_cap_note)
            res.total = cap
        res.tier = "weak"
        crit("target_type", "not_met", f"type '{ctype}' not established as a {t.label}: " + "; ".join(type_reasons), _ids(type_evs))
    else:
        crit("target_type", "met", t.qualified_reason, _ids(type_evs))
        if res.tier == "strong":
            sr = pol.strong_requirements
            offered = sum(1 for c in t.capabilities if c.counts_for_strong and _ok(evidence, c.claim))
            missing = []
            if sr.geography and not us:
                missing.append("US presence not evidenced")
            if sr.size_in_band and not (isinstance(size, int) and lo <= size <= hi):
                missing.append("no explicit in-band headcount")
            if offered < sr.min_capabilities:
                missing.append(f"fewer than {sr.min_capabilities} offered target {t.capability_noun}")
            if missing:
                res.tier = "possible"
                res.gate_notes.append("held at possible: " + "; ".join(missing))
                res.flags.append("strong_gate: score >= strong threshold but " + "; ".join(missing))
                crit("strong_gate", "not_met", "held at possible: " + "; ".join(missing))
    return res


def explain_verdict(res: ScoreResult, evidence: list[Evidence], policy: IcpPolicy | None = None) -> str:
    """Human-readable, evidence-cited account of why a company matched or failed ONE policy.

    Every statement comes from ``res.criteria`` (built during scoring) and quotes the stored verbatim excerpt of each
    cited evidence item. It adds no new claims."""
    by_id = {e.id: e for e in evidence}
    name = f"{res.policy_id} v{res.policy_version}" if res.policy_id else "policy"
    head = f"{name}: tier {res.tier}" + (f" ({res.total})" if res.total is not None else "") + f", type '{res.company_type}'"
    lines = [head]
    label = {"met": "MET", "not_met": "NOT MET", "unknown": "UNKNOWN", "excluded": "EXCLUDED", "blocked": "BLOCKED"}
    for c in res.criteria:
        lines.append(f"- [{label.get(c['status'], c['status'].upper())}] {c['criterion']}: {c['detail']}")
        for eid in c["evidence_ids"][:3]:
            e = by_id.get(eid)
            if e is not None:
                lines.append(f"    evidence {eid} ({e.level}) {e.source_url}: \"{e.excerpt}\"")
    for f in res.flags:
        lines.append(f"- flag: {f}")
    return "\n".join(lines)
