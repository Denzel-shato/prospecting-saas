"""Versioned, validated ICP policy (Issue #5).

A policy says which of the universal company facts (vm1.facts) matter for ONE customer profile and how much:
what a target company IS, which capabilities it has, where, how big, who to contact, and what disqualifies it.
It contains NO regular expressions and NO code: only claim-type names from the fact catalog, numbers, short
labels and phrase lists. Loading is strict: unknown keys, unknown claim types, impossible thresholds and unsafe
page-selection hints are rejected with every problem listed.

Schema version 1. See docs/ICP-FOUNDATION.md for the field-by-field reference.

Legacy compatibility: a flat file without ``schema_version`` (the original frontend-studio.json shape, keys
id/seller/target/size_band/size_hard_max/...) is interpreted as the built-in frontend-studio baseline with only
those overrides applied, which reproduces the pre-Issue-#5 behavior exactly.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
import string
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .facts import CLAIM_TYPES

SCHEMA_VERSION = 1
SUPPORTED_SCHEMA_VERSIONS = (1,)
BASELINE_PATH = Path(__file__).resolve().parent.parent / "icp" / "frontend-studio.json"
ROLE_CLASSES = ("founder_ceo", "cto_eng", "other_leader")
PAGE_POOLS = ("service", "about", "service_other", "team", "work", "contact", "detail", "project", "people")
SEGMENT_CATEGORIES = ("service_hub", "about", "team", "work", "contact")
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,63}$")
_SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
_TOKEN_RE = re.compile(r"^[a-z0-9]+$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,40}$")
_TERM_RE = re.compile(r"^[a-z0-9][a-z0-9 &'-]{0,58}\*?$")
_CTRL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class PolicyError(ValueError):
    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        super().__init__("invalid ICP policy:\n  - " + "\n  - ".join(self.problems))


# ---- model -------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class IdentityRule:
    claim: str
    strength: str  # strong | weak. Only a strong identity shields a company from type exclusions.
    points: int
    rule: str
    min_distinct_values: int = 1


@dataclass(frozen=True)
class Capability:
    id: str
    claim: str
    points: int
    counts_for_strong: bool = True


@dataclass(frozen=True)
class TargetType:
    id: str
    label: str
    short_label: str
    identity: tuple
    capabilities: tuple
    capability_cap: int
    min_capabilities: int
    capability_noun: str
    capability_rule_prefix: str
    identity_missing_unknown: str
    identity_missing_reason: str
    capabilities_missing_unknown: str
    capabilities_missing_reason: str
    qualified_reason: str
    mixed_identity_template: str
    gate_cap_note: str


@dataclass(frozen=True)
class Screen:
    """Claim-presence hard exclusion evaluated before size/geography (e.g. a staffing firm)."""
    rule: str
    type_id: str
    claim: str
    detail: str


@dataclass(frozen=True)
class TypeProfile:
    """A company TYPE that is not the target (vendor, enterprise, competitor ...). Excludes when matched unless a
    strong identity shields it. Matched when distinct claim values >= min_distinct_values or any_value is present."""
    id: str
    claim: str
    min_distinct_values: int
    any_value: tuple
    shielded_by_strong_identity: bool
    reason_template: str
    partial_note_template: str | None = None


@dataclass(frozen=True)
class PointRule:
    claim: str
    points: int
    rule: str
    requires_target_type: bool = False


@dataclass(frozen=True)
class Geography:
    countries: tuple  # () = no geographic requirement; ("US",) = US evidence required
    points: int
    exclude_india: bool = False


@dataclass(frozen=True)
class SizePolicy:
    band: tuple
    hard_max: int
    in_band_points: int
    above_band_points: int
    below_band_points: int


@dataclass(frozen=True)
class DecisionMakerPolicy:
    role_classes: tuple
    points: int


@dataclass(frozen=True)
class Tiers:
    strong: int
    possible: int


@dataclass(frozen=True)
class StrongRequirements:
    geography: bool
    size_in_band: bool
    min_capabilities: int


@dataclass(frozen=True)
class PrequalifyPolicy:
    positive_terms: tuple
    negative_terms: tuple


@dataclass(frozen=True)
class PageSelectionConfig:
    relevance_tokens: tuple
    extra_segments: tuple  # ((category, (slug, ...)), ...)
    slot_order: tuple
    service_slug: tuple | None  # (core_words, extra_core_words, provider_words) or None


@dataclass(frozen=True)
class IcpPolicy:
    schema_version: int
    id: str
    policy_version: str
    name: str
    description: str
    seller: str
    notes: str
    geography: Geography
    size: SizePolicy
    target_type: TargetType
    screens: tuple
    type_profiles: tuple
    bonuses: tuple
    penalties: tuple
    decision_makers: DecisionMakerPolicy
    tiers: Tiers
    strong_requirements: StrongRequirements
    prequalify: PrequalifyPolicy
    page_selection: PageSelectionConfig
    drafts_enabled: bool
    source_format: str = "schema_v1"  # schema_v1 | legacy_flat
    raw: dict = field(default_factory=dict, compare=False, hash=False, repr=False)

    @property
    def digest(self) -> str:
        """Stable fingerprint of the policy content, recorded in every run manifest."""
        return hashlib.sha256(json.dumps(self.raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return copy.deepcopy(self.raw)

    def max_possible_score(self) -> int:
        ident = max((r.points for r in self.target_type.identity), default=0)
        caps = min(self.target_type.capability_cap, sum(max(c.points, 0) for c in self.target_type.capabilities))
        rest = (self.geography.points if self.geography.countries or self.geography.exclude_india else 0) + max(self.size.in_band_points, 0)
        rest += sum(max(b.points, 0) for b in self.bonuses) + self.decision_makers.points
        return ident + caps + rest

    def with_size(self, band: tuple, hard_max: int) -> "IcpPolicy":
        """Copy with a different size band (used by the score_company compatibility wrapper)."""
        raw = copy.deepcopy(self.raw)
        raw["size"]["band"] = [band[0], band[1]]
        raw["size"]["hard_max"] = hard_max
        return load_policy(raw)


# ---- validation toolkit --------------------------------------------------------------------------------------------
class _Check:
    def __init__(self):
        self.problems: list[str] = []

    def err(self, path: str, msg: str) -> None:
        self.problems.append(f"{path}: {msg}")

    def obj(self, d, path, required=(), optional=()):
        if not isinstance(d, dict):
            self.err(path, f"must be an object, got {type(d).__name__}")
            return {}
        for k in d:
            if k not in required and k not in optional:
                self.err(f"{path}.{k}", "unknown key (typo? allowed: " + ", ".join(sorted(set(required) | set(optional))) + ")")
        for k in required:
            if k not in d:
                self.err(f"{path}.{k}", "required key missing")
        return d

    def text(self, d, key, path, *, required=True, default="", max_len=400):
        v = d.get(key, None)
        p = f"{path}.{key}"
        if v is None:
            if required and key not in d:
                return default
            return default
        if not isinstance(v, str):
            self.err(p, "must be a string")
            return default
        if len(v) > max_len or _CTRL_RE.search(v):
            self.err(p, f"must be <= {max_len} chars with no control characters")
            return default
        return v

    def integer(self, d, key, path, lo, hi, default=0):
        v = d.get(key, default)
        p = f"{path}.{key}"
        if isinstance(v, bool) or not isinstance(v, int):
            self.err(p, "must be an integer")
            return default
        if not lo <= v <= hi:
            self.err(p, f"must be between {lo} and {hi}, got {v}")
            return default
        return v

    def boolean(self, d, key, path, default=False):
        v = d.get(key, default)
        if not isinstance(v, bool):
            self.err(f"{path}.{key}", "must be true or false")
            return default
        return v

    def lst(self, d, key, path, *, min_len=0, max_len=200):
        v = d.get(key, [])
        if not isinstance(v, list):
            self.err(f"{path}.{key}", "must be a list")
            return []
        if not min_len <= len(v) <= max_len:
            self.err(f"{path}.{key}", f"must have {min_len}-{max_len} items, has {len(v)}")
        return v

    def claim(self, v, path, prefixes):
        if not isinstance(v, str) or v not in CLAIM_TYPES:
            self.err(path, f"unknown claim type {v!r}; policies may only use claim types registered in vm1.facts.CLAIM_TYPES")
            return ""
        if not v.startswith(tuple(prefixes)):
            self.err(path, f"claim {v!r} is not allowed here (expected prefix: {', '.join(prefixes)})")
        return v

    def template(self, v, path, allowed=("values",)):
        if not isinstance(v, str) or len(v) > 400 or _CTRL_RE.search(v):
            self.err(path, "must be a string of <= 400 chars")
            return ""
        try:
            fields = {f for _, f, _, _ in string.Formatter().parse(v) if f is not None}
        except ValueError:
            self.err(path, "malformed template braces")
            return ""
        bad = fields - set(allowed)
        if bad:
            self.err(path, f"unknown placeholder(s) {sorted(bad)}; allowed: {list(allowed)}")
        return v


def _identity(c: _Check, d, path) -> IdentityRule:
    d = c.obj(d, path, ("claim", "strength", "points", "rule"), ("min_distinct_values",))
    strength = d.get("strength")
    if strength not in ("strong", "weak"):
        c.err(f"{path}.strength", "must be 'strong' or 'weak'")
    # Past client delivery can support a weak services identity when separately evidenced
    # capabilities are required. It cannot shield an enterprise or a product vendor.
    prefixes = ("entity_type:", "company_type:")
    if strength == "weak" and d.get("claim") == "capability:client_application_delivery":
        prefixes += ("capability:",)
    return IdentityRule(c.claim(d.get("claim"), f"{path}.claim", prefixes), strength or "weak",
                        c.integer(d, "points", path, -50, 100), c.text(d, "rule", path, max_len=200),
                        c.integer(d, "min_distinct_values", path, 1, 10, 1))


def _parse_target(c: _Check, d, path) -> TargetType:
    keys = ("id", "label", "short_label", "identity", "capabilities", "capability_cap", "min_capabilities",
            "capability_noun", "capability_rule_prefix", "identity_missing_unknown", "identity_missing_reason",
            "capabilities_missing_unknown", "capabilities_missing_reason", "qualified_reason",
            "mixed_identity_template", "gate_cap_note")
    d = c.obj(d, path, keys)
    tid = d.get("id")
    if not isinstance(tid, str) or not _ID_RE.match(tid) or tid in ("unclear", "excluded"):
        c.err(f"{path}.id", "must be a lowercase id (not 'unclear'/'excluded')")
        tid = "target"
    ident = tuple(_identity(c, x, f"{path}.identity[{i}]") for i, x in enumerate(c.lst(d, "identity", path, min_len=1, max_len=10)))
    caps, seen = [], set()
    for i, x in enumerate(c.lst(d, "capabilities", path, min_len=1, max_len=40)):
        p = f"{path}.capabilities[{i}]"
        x = c.obj(x, p, ("id", "claim", "points"), ("counts_for_strong",))
        cid = x.get("id")
        if not isinstance(cid, str) or not _ID_RE.match(cid) or cid in seen:
            c.err(f"{p}.id", "must be a unique lowercase id")
        seen.add(cid)
        caps.append(Capability(cid if isinstance(cid, str) else "", c.claim(x.get("claim"), f"{p}.claim", ("service:", "capability:")),
                               c.integer(x, "points", p, -50, 100), c.boolean(x, "counts_for_strong", p, True)))
    claims = [x.claim for x in caps]
    if len(claims) != len(set(claims)):
        c.err(f"{path}.capabilities", "two capabilities use the same claim type")
    cap_total = c.integer(d, "capability_cap", path, 0, 100)
    min_caps = c.integer(d, "min_capabilities", path, 0, 40)
    if any(i.claim == "capability:client_application_delivery" for i in ident):
        if min_caps == 0 or "capability:client_application_delivery" in claims:
            c.err(f"{path}.capabilities", "a project-based identity requires a separate qualifying capability")
    if min_caps > len(caps):
        c.err(f"{path}.min_capabilities", "exceeds the number of capabilities defined")
    t = lambda k, m=300: c.text(d, k, path, max_len=m)  # noqa: E731
    mixed = c.template(d.get("mixed_identity_template"), f"{path}.mixed_identity_template")
    return TargetType(tid, t("label", 120), t("short_label", 60), ident, tuple(caps), cap_total, min_caps,
                      t("capability_noun", 40), t("capability_rule_prefix", 40), t("identity_missing_unknown"),
                      t("identity_missing_reason"), t("capabilities_missing_unknown"), t("capabilities_missing_reason"),
                      t("qualified_reason"), mixed, t("gate_cap_note"))


def _parse_page_selection(c: _Check, d, path) -> PageSelectionConfig:
    d = c.obj(d, path, ("relevance_tokens", "slot_order"), ("extra_segments", "service_slug"))
    toks = []
    for i, t in enumerate(c.lst(d, "relevance_tokens", path, max_len=150)):
        if isinstance(t, str) and _TOKEN_RE.match(t):
            toks.append(t)
        else:
            c.err(f"{path}.relevance_tokens[{i}]", "must be a lowercase alphanumeric word")
    from .pageselect import EDITORIAL_SEGS, EXCLUDED_SEGS  # lazy: pageselect imports this module's types
    forbidden = EDITORIAL_SEGS | EXCLUDED_SEGS
    extra = []
    ex = d.get("extra_segments", {})
    if not isinstance(ex, dict):
        c.err(f"{path}.extra_segments", "must be an object")
        ex = {}
    for cat, slugs in ex.items():
        if cat not in SEGMENT_CATEGORIES:
            c.err(f"{path}.extra_segments.{cat}", f"unknown category (allowed: {', '.join(SEGMENT_CATEGORIES)})")
            continue
        good = []
        for s in slugs if isinstance(slugs, list) else []:
            if not isinstance(s, str) or not _SLUG_RE.match(s):
                c.err(f"{path}.extra_segments.{cat}", f"{s!r} is not a lowercase URL slug")
            elif s in forbidden:
                c.err(f"{path}.extra_segments.{cat}", f"{s!r} is a shared safety exclusion (editorial/legal/docs/pricing/...) and cannot be promoted")
            else:
                good.append(s)
        if not isinstance(slugs, list):
            c.err(f"{path}.extra_segments.{cat}", "must be a list")
        extra.append((cat, tuple(good)))
    slots = c.lst(d, "slot_order", path, min_len=1, max_len=20)
    for i, s in enumerate(slots):
        if s not in PAGE_POOLS:
            c.err(f"{path}.slot_order[{i}]", f"{s!r} is not a page pool ({', '.join(PAGE_POOLS)})")
    slug = None
    if d.get("service_slug") is not None:
        sd = c.obj(d["service_slug"], f"{path}.service_slug", ("core_words", "extra_core_words", "provider_words"))
        parts = []
        for k in ("core_words", "extra_core_words", "provider_words"):
            ws = c.lst(sd, k, f"{path}.service_slug", max_len=60)
            for w in ws:
                if not isinstance(w, str) or not _TOKEN_RE.match(w):
                    c.err(f"{path}.service_slug.{k}", f"{w!r} must be a lowercase alphanumeric word")
            parts.append(tuple(w for w in ws if isinstance(w, str)))
        slug = tuple(parts)
    return PageSelectionConfig(tuple(toks), tuple(sorted(extra)), tuple(s for s in slots if s in PAGE_POOLS), slug)


def _parse(raw: dict, source_format: str) -> IcpPolicy:
    c = _Check()
    top = ("schema_version", "id", "policy_version", "name", "description", "geography", "size", "target_type",
           "screens", "type_profiles", "decision_makers", "tiers", "strong_requirements", "prequalify", "page_selection")
    d = c.obj(raw, "policy", top, ("seller", "notes", "bonuses", "penalties", "drafts"))
    if d.get("schema_version") not in SUPPORTED_SCHEMA_VERSIONS:
        c.err("policy.schema_version", f"must be one of {SUPPORTED_SCHEMA_VERSIONS}, got {d.get('schema_version')!r}")
    pid = d.get("id")
    if not isinstance(pid, str) or not _ID_RE.match(pid):
        c.err("policy.id", "must match [a-z0-9][a-z0-9._-]{1,63}")
        pid = "invalid"
    ver = d.get("policy_version")
    if not isinstance(ver, str) or not _SEMVER_RE.match(ver):
        c.err("policy.policy_version", "must look like 1.0.0")
        ver = "0.0.0"

    g = c.obj(d.get("geography"), "policy.geography", ("countries", "points"), ("exclude_india",))
    countries = g.get("countries", [])
    if not isinstance(countries, list) or any(x != "US" for x in countries) or len(countries) > 1:
        c.err("policy.geography.countries", "must be [] (no requirement) or [\"US\"]; the extractor only distinguishes US from non-US")
        countries = []
    exclude_india = c.boolean(g, "exclude_india", "policy.geography") if "exclude_india" in g else False
    if countries and exclude_india:
        c.err("policy.geography", "exclude_india is supported for the worldwide profile only")
    geo = Geography(tuple(countries), c.integer(g, "points", "policy.geography", -50, 100), exclude_india)

    s = c.obj(d.get("size"), "policy.size", ("band", "hard_max", "in_band_points", "above_band_points", "below_band_points"))
    band = s.get("band")
    if not (isinstance(band, list) and len(band) == 2 and all(isinstance(x, int) and not isinstance(x, bool) for x in band)
            and 0 <= band[0] <= band[1] <= 100000):
        c.err("policy.size.band", "must be [low, high] integers with 0 <= low <= high")
        band = [5, 50]
    hard = c.integer(s, "hard_max", "policy.size", 1, 1000000, 250)
    if hard < band[1]:
        c.err("policy.size.hard_max", "must be >= the band's upper bound")
    size = SizePolicy((band[0], band[1]), hard, c.integer(s, "in_band_points", "policy.size", -50, 100),
                      c.integer(s, "above_band_points", "policy.size", -50, 100),
                      c.integer(s, "below_band_points", "policy.size", -50, 100))

    target = _parse_target(c, d.get("target_type"), "policy.target_type")

    screens = []
    for i, x in enumerate(c.lst(d, "screens", "policy", max_len=20)):
        p = f"policy.screens[{i}]"
        x = c.obj(x, p, ("rule", "type_id", "claim", "detail"))
        screens.append(Screen(c.text(x, "rule", p, max_len=80), c.text(x, "type_id", p, max_len=80),
                              c.claim(x.get("claim"), f"{p}.claim", ("negative:",)), c.text(x, "detail", p, max_len=300)))

    profiles, ids = [], {target.id}
    for i, x in enumerate(c.lst(d, "type_profiles", "policy", max_len=20)):
        p = f"policy.type_profiles[{i}]"
        x = c.obj(x, p, ("id", "claim", "min_distinct_values", "shielded_by_strong_identity", "reason_template"),
                  ("any_value", "partial_note_template"))
        xid = x.get("id")
        if not isinstance(xid, str) or not _ID_RE.match(xid) or xid in ids:
            c.err(f"{p}.id", "must be a unique lowercase id different from the target type id")
        ids.add(xid)
        any_value = x.get("any_value", [])
        if not isinstance(any_value, list) or not all(isinstance(v, str) for v in any_value):
            c.err(f"{p}.any_value", "must be a list of strings")
            any_value = []
        partial = x.get("partial_note_template")
        profiles.append(TypeProfile(
            xid if isinstance(xid, str) else "", c.claim(x.get("claim"), f"{p}.claim", ("company_type:", "entity_type:")),
            c.integer(x, "min_distinct_values", p, 1, 10, 1), tuple(any_value),
            c.boolean(x, "shielded_by_strong_identity", p), c.template(x.get("reason_template"), f"{p}.reason_template"),
            c.template(partial, f"{p}.partial_note_template") if partial is not None else None))

    def point_rules(key, prefixes):
        out = []
        for i, x in enumerate(c.lst(d, key, "policy", max_len=20)):
            p = f"policy.{key}[{i}]"
            x = c.obj(x, p, ("claim", "points", "rule"), ("requires_target_type",))
            out.append(PointRule(c.claim(x.get("claim"), f"{p}.claim", prefixes), c.integer(x, "points", p, -50, 100),
                                 c.text(x, "rule", p, max_len=200), c.boolean(x, "requires_target_type", p)))
        return tuple(out)

    bonuses = point_rules("bonuses", ("signal:", "capability:"))
    penalties = point_rules("penalties", ("negative:", "signal:"))

    dm = c.obj(d.get("decision_makers"), "policy.decision_makers", ("role_classes", "points"))
    roles = c.lst(dm, "role_classes", "policy.decision_makers", min_len=1, max_len=3)
    for r in roles:
        if r not in ROLE_CLASSES:
            c.err("policy.decision_makers.role_classes", f"{r!r} is not a recognised role class {ROLE_CLASSES}")
    dmp = DecisionMakerPolicy(tuple(r for r in roles if r in ROLE_CLASSES), c.integer(dm, "points", "policy.decision_makers", 0, 50))

    t = c.obj(d.get("tiers"), "policy.tiers", ("strong", "possible"))
    tiers = Tiers(c.integer(t, "strong", "policy.tiers", 1, 100, 65), c.integer(t, "possible", "policy.tiers", 1, 100, 40))
    if not 0 < tiers.possible < tiers.strong <= 100:
        c.err("policy.tiers", "requires 0 < possible < strong <= 100")

    sr = c.obj(d.get("strong_requirements"), "policy.strong_requirements", ("geography", "size_in_band", "min_capabilities"))
    strong_req = StrongRequirements(c.boolean(sr, "geography", "policy.strong_requirements"),
                                    c.boolean(sr, "size_in_band", "policy.strong_requirements"),
                                    c.integer(sr, "min_capabilities", "policy.strong_requirements", 0, 40))
    if strong_req.geography and not (geo.countries or geo.exclude_india):
        c.err("policy.strong_requirements.geography", "cannot require geography without a geography policy")
    if strong_req.min_capabilities > sum(1 for x in target.capabilities if x.counts_for_strong):
        c.err("policy.strong_requirements.min_capabilities", "exceeds the number of capabilities with counts_for_strong")

    pq = c.obj(d.get("prequalify"), "policy.prequalify", ("positive_terms", "negative_terms"))
    pq_terms = {}
    for k in ("positive_terms", "negative_terms"):
        terms = c.lst(pq, k, "policy.prequalify", max_len=80)
        for tm in terms:
            if not isinstance(tm, str) or not _TERM_RE.match(tm):
                c.err(f"policy.prequalify.{k}", f"{tm!r}: lowercase words/phrases only (a trailing * allows a word ending)")
        pq_terms[k] = tuple(tm for tm in terms if isinstance(tm, str) and _TERM_RE.match(tm))
    page_sel = _parse_page_selection(c, d.get("page_selection"), "policy.page_selection")
    drafts = c.obj(d.get("drafts", {"enabled": False}), "policy.drafts", ("enabled",))
    drafts_enabled = c.boolean(drafts, "enabled", "policy.drafts", False)

    pol = IcpPolicy(
        schema_version=d.get("schema_version") if isinstance(d.get("schema_version"), int) else 0, id=pid, policy_version=ver,
        name=c.text(d, "name", "policy", max_len=160), description=c.text(d, "description", "policy", max_len=800),
        seller=c.text(d, "seller", "policy", required=False, max_len=800), notes=c.text(d, "notes", "policy", required=False, max_len=800),
        geography=geo, size=size, target_type=target, screens=tuple(screens), type_profiles=tuple(profiles),
        bonuses=bonuses, penalties=penalties, decision_makers=dmp, tiers=tiers, strong_requirements=strong_req,
        prequalify=PrequalifyPolicy(pq_terms["positive_terms"], pq_terms["negative_terms"]), page_selection=page_sel,
        drafts_enabled=drafts_enabled, source_format=source_format, raw=copy.deepcopy(raw) if isinstance(raw, dict) else {})
    if not c.problems and pol.max_possible_score() < pol.tiers.possible:
        c.err("policy", f"unreachable: the maximum possible score {pol.max_possible_score()} is below tiers.possible "
                        f"{pol.tiers.possible}; no company could ever be rated 'possible'")
    if c.problems:
        raise PolicyError(c.problems)
    return pol


# ---- loading ------------------------------------------------------------------------------------------------------
_LEGACY_KEYS = {"id", "seller", "target", "target_roles", "size_band", "size_hard_max", "hard_exclusions", "notes"}


def _baseline_raw() -> dict:
    return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))


def _from_legacy(d: dict) -> IcpPolicy:
    unknown = set(d) - _LEGACY_KEYS
    if unknown:
        raise PolicyError([f"legacy flat ICP file has unknown key(s) {sorted(unknown)}; add \"schema_version\": 1 to use the "
                           "full policy schema or remove them"])
    raw = _baseline_raw()
    if "id" in d:
        raw["id"] = d["id"]
    if "seller" in d:
        raw["seller"] = d["seller"]
    if "target" in d:
        raw["description"] = d["target"]
    if "notes" in d:
        raw["notes"] = d["notes"]
    if "size_band" in d:
        raw["size"]["band"] = list(d["size_band"])
    if "size_hard_max" in d:
        raw["size"]["hard_max"] = d["size_hard_max"]
    return _parse(raw, "legacy_flat")


def load_policy(source) -> IcpPolicy:
    """IcpPolicy | dict (schema v1 or legacy flat) | path to a JSON file -> validated IcpPolicy."""
    if isinstance(source, IcpPolicy):
        return source
    if isinstance(source, (str, Path)):
        try:
            source = json.loads(Path(source).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PolicyError([f"cannot read policy file {source}: {exc}"]) from exc
    if not isinstance(source, dict):
        raise PolicyError([f"policy must be a JSON object, got {type(source).__name__}"])
    if "schema_version" not in source:
        return _from_legacy(source)
    return _parse(source, "schema_v1")


as_policy = load_policy


@lru_cache(maxsize=1)
def baseline_policy() -> IcpPolicy:
    """The built-in frontend-studio compatibility baseline (icp/frontend-studio.json)."""
    return _parse(_baseline_raw(), "schema_v1")


def summarize(p: IcpPolicy) -> str:
    t = p.target_type
    lines = [f"{p.id} v{p.policy_version} (digest {p.digest}) - {p.name}",
             f"  target type : {t.id} ({t.label})",
             f"  identity    : " + "; ".join(f"{r.claim}[{r.strength},{r.points:+d}]" for r in t.identity),
             f"  capabilities: " + ", ".join(f"{c.id}({c.points:+d})" for c in t.capabilities) + f"  cap={t.capability_cap}",
             f"  geography   : {list(p.geography.countries) or ('worldwide, excluding India' if p.geography.exclude_india else 'any')}   size band {list(p.size.band)} hard max {p.size.hard_max}",
             f"  exclusions  : " + ", ".join([s.rule for s in p.screens] + [x.id for x in p.type_profiles]),
             f"  tiers       : strong>={p.tiers.strong} possible>={p.tiers.possible}   max possible score {p.max_possible_score()}",
             f"  roles       : {list(p.decision_makers.role_classes)}   drafts enabled: {p.drafts_enabled}"]
    return "\n".join(lines)
