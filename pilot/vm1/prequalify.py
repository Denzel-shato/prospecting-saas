"""Deterministic, policy-aware PRE-research prioritisation of discovery candidates.

Uses only discovery-record text (description, directory tagline/services), listed-on-exchange flag and
reported headcount. Prequalification determines research order, never lead qualification or score.

With no explicit policy, this is the legacy frontend-studio ordering. Different
ICPs can use different description terms without changing evidence extraction.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache

from .policy import IcpPolicy, baseline_policy, load_policy


def _policy(policy: IcpPolicy | dict | None) -> IcpPolicy:
    return baseline_policy() if policy is None else load_policy(policy)


def _fragment(term: str) -> str:
    wild = term.endswith("*")
    stem = term[:-1] if wild else term
    return re.escape(stem).replace(r"\ ", r"\s+") + (r"\w+" if wild else "")


@lru_cache(maxsize=128)
def _matcher(terms: tuple[str, ...]) -> re.Pattern:
    """Match validated whole words/phrases; a trailing * requires a word continuation."""
    parts = [_fragment(t) for t in terms]
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.I) if parts else re.compile(r"(?!)")


def _description_matches(description: str, positive: bool, policy: IcpPolicy) -> bool:
    terms = policy.prequalify.positive_terms if positive else policy.prequalify.negative_terms
    return bool(_matcher(terms).search(description))


def _priority_parts(attrs: dict, pol: IcpPolicy) -> list[tuple[int, str, str]]:
    """[(points, reason, kind)]; kind is "text" for points derived from record wording, else "structural"."""
    is_baseline = pol.id == baseline_policy().id
    parts: list[tuple[int, str, str]] = []
    desc = (attrs.get("description") or "").strip()
    if desc:
        if _description_matches(desc, True, pol):
            parts.append((3, "record description reads like a services studio/agency" if is_baseline
                          else "record description matches ICP's preferred discovery terms", "text"))
        if _description_matches(desc, False, pol):
            parts.append((-3, "record description reads like a product/platform/enterprise company" if is_baseline
                          else "record description matches ICP's negative discovery terms", "text"))
    if pol.target_type.id == "agency_studio" and attrs.get("directory_vendor_hint"):
        parts.append((-3, "directory profile reads like a product/hosting vendor with no agency/studio wording", "structural"))
    if pol.target_type.id == "agency_studio" and attrs.get("directory_service_hint"):
        parts.append((3, "directory profile suggests client services", "text"))
        if attrs.get("directory_frontend_hint"):
            parts.append((1, "directory profile mentions relevant frontend or headless work", "structural"))
        # Source identity wording is a weak TIE-BREAK signal only. Almost every
        # record in this provider's Software Development category gets +3,
        # which otherwise leaves the shortlist ordered by an arbitrary hash.
        if attrs.get("directory_software_focus_hint"):
            parts.append((2, "directory name/tagline explicitly describes software/product development", "structural"))
        elif attrs.get("directory_marketing_focus_hint"):
            parts.append((-1, "directory name/tagline suggests marketing-led rather than software-led services", "structural"))
    if attrs.get("listed_on_exchange"):
        parts.append((-4, "listed on a stock exchange (record)", "structural"))
    emp = attrs.get("employees")
    if isinstance(emp, int) and not isinstance(emp, bool):
        hard = pol.size.hard_max
        lo, hi = pol.size.band
        if emp > hard:
            parts.append((-3, f"record headcount {emp} above {hard}", "structural"))
        elif lo <= emp <= hi:
            parts.append((1, f"record headcount {emp} within {lo}-{hi} (may be stale)", "structural"))
    return parts


def prequalify(attrs: dict, policy: IcpPolicy | dict | None = None) -> tuple[int, list[str]]:
    """Return (priority, reasons) based on public discovery-record fields only."""
    parts = _priority_parts(attrs, _policy(policy))
    return sum(p for p, _, _ in parts), [f"{p:+d} {why}" for p, why, _ in parts]


@lru_cache(maxsize=512)
def _term_matcher(term: str) -> re.Pattern:
    return _matcher((term,))


# Text fields a discovery record may carry. Directory adapters keep their tagline/service labels here;
# before Engine #2 only Wikidata's `description` was ever compared with the ICP's own vocabulary.
_TEXT_LIST_FIELDS = ("directory_services",)
_TEXT_FIELDS = ("description", "directory_tagline")


def record_text(attrs: dict) -> str:
    parts = [attrs.get(k) for k in _TEXT_FIELDS]
    for key in _TEXT_LIST_FIELDS:
        value = attrs.get(key)
        if isinstance(value, (list, tuple)):
            parts.extend(value)
    return " | ".join(p.strip() for p in parts if isinstance(p, str) and p.strip())


def term_breadth(attrs: dict, policy: IcpPolicy | dict | None = None) -> tuple[int, list[str], list[str]]:
    """(net, positive_terms_matched, negative_terms_matched): how many DISTINCT ICP terms the record's own
    text matches. Graded (one stray word is not five) and ICP-relative: it uses the policy's vocabulary and
    no weights of its own. Missing text gives (0, [], []): unknown is neutral, never a penalty."""
    pol = _policy(policy)
    text = record_text(attrs or {})
    if not text:
        return 0, [], []
    pos = [t for t in pol.prequalify.positive_terms if _term_matcher(t).search(text)]
    neg = [t for t in pol.prequalify.negative_terms if _term_matcher(t).search(text)]
    return len(pos) - len(neg), pos, neg


# ---------------------------------------------------------------------------------------------------------
# Specificity-aware record evidence (Engine #2). Used ONLY to order research; never a qualification score.
#
# Terms the ICP marks `generic_terms` (agency, consulting, web design ...) are labels nearly every directory
# member carries, so they say little about specialization and are capped at ONE unit however many match.
# Specific terms (software development company, custom software ...) in the company's own positioning
# (description/tagline) outrank the same words in broad directory category labels. `ambiguous_negative_terms`
# (saas, cloud, ecommerce ...) are read in context: "SaaS product development studio" names what the studio
# BUILDS, while "SaaS platform" names what it SELLS. Missing text is neutral. No term is tied to a company.
# ---------------------------------------------------------------------------------------------------------
SPECIFIC_POSITIONING, SPECIFIC_LABEL, SPECIFIC_CAP = 4, 2, 2  # points per distinct term / max distinct terms counted
GENERIC_POSITIONING, GENERIC_LABEL = 2, 1  # once in total
NEG_POSITIONING, NEG_LABEL, NEG_CAP = 4, 2, 2  # unambiguous negatives
AMBIG_POSITIONING, AMBIG_LABEL = 2, 1  # ambiguous negatives that no service context explains (once in total)

_SEGMENT_SPLIT = re.compile(r"[|.;!?\n]+")


@dataclass(frozen=True)
class RecordEvidence:
    points: int
    specific: tuple
    generic: tuple
    negative: tuple
    ambiguous_penalised: tuple
    ambiguous_neutralised: tuple

    def explain(self) -> dict:
        return {"points": self.points, "matched_specific": list(self.specific), "matched_generic": list(self.generic),
                "matched_negative": list(self.negative), "ambiguous_penalised": list(self.ambiguous_penalised),
                "ambiguous_neutralised": list(self.ambiguous_neutralised)}


@lru_cache(maxsize=256)
def _context_patterns(term: str, context: tuple[str, ...]) -> tuple[re.Pattern, re.Pattern]:
    """(term followed within two words by a service word, service-word + for/of + term)."""
    inner = _fragment(term)
    ctx = "(?:" + "|".join(_fragment(t) for t in context) + ")"
    after = re.compile(r"(?<!\w)" + inner + r"(?:\W+\w+){0,2}\W+" + ctx + r"(?!\w)", re.I)
    before = re.compile(r"(?<!\w)" + ctx + r"\W+(?:for|of)\W+(?:\w+\W+){0,2}" + inner + r"(?!\w)", re.I)
    return after, before


def _in_service_context(term: str, text: str, context: tuple[str, ...]) -> bool:
    after, before = _context_patterns(term, context)
    for segment in _SEGMENT_SPLIT.split(text):
        if _term_matcher(term).search(segment) and (after.search(segment) or before.search(segment)):
            return True
    return False


def record_evidence(attrs: dict, policy: IcpPolicy | dict | None = None) -> RecordEvidence:
    pol = _policy(policy)
    pq = pol.prequalify
    attrs = attrs or {}
    positioning = " | ".join(p.strip() for p in (attrs.get("description"), attrs.get("directory_tagline"))
                             if isinstance(p, str) and p.strip())
    services = attrs.get("directory_services")
    labels = " | ".join(x.strip() for x in services if isinstance(x, str) and x.strip()) if isinstance(services, (list, tuple)) else ""
    generic_set, ambiguous_set = set(pq.generic_terms), set(pq.ambiguous_negative_terms)

    def hits(terms, text):
        found = [t for t in terms if text and _term_matcher(t).search(text)]
        # one phrase must not be counted twice ("software development company" contains "development company")
        return [t for t in found if not any(t != u and t.rstrip("*") in u for u in found)]

    specific_terms = [t for t in pq.positive_terms if t not in generic_set]
    spec_pos = hits(specific_terms, positioning)
    spec_lab = [t for t in hits(specific_terms, labels) if t not in spec_pos]
    covered = spec_pos + spec_lab  # a generic word inside a matched specific phrase ("studio" in "product studio") is not extra
    gen_pos = [t for t in hits(pq.generic_terms, positioning) if not any(t.rstrip("*") in u for u in covered)]
    gen_lab = [t for t in hits(pq.generic_terms, labels) if t not in gen_pos and not any(t.rstrip("*") in u for u in covered)]
    points = (SPECIFIC_POSITIONING * min(len(spec_pos), SPECIFIC_CAP)
              + SPECIFIC_LABEL * min(len(spec_lab), max(0, SPECIFIC_CAP - len(spec_pos)))
              + (GENERIC_POSITIONING if gen_pos else GENERIC_LABEL if gen_lab else 0))

    # A company whose OWN wording names a specific software/product-development specialization is describing
    # services; ambiguous words next to it name its clients' domains. Directory labels alone do not do this.
    self_described = bool(spec_pos)
    neg_pos = hits([t for t in pq.negative_terms if t not in ambiguous_set], positioning)
    neg_lab = [t for t in hits([t for t in pq.negative_terms if t not in ambiguous_set], labels) if t not in neg_pos]
    penalised, neutralised = [], []
    for where, text in (("positioning", positioning), ("label", labels)):
        for t in hits(pq.ambiguous_negative_terms, text):
            if t in penalised or t in neutralised:
                continue
            if (self_described and where == "positioning") or _in_service_context(t, text, pq.service_context_terms):
                neutralised.append(t)
            else:
                penalised.append((t, where))
    points -= NEG_POSITIONING * min(len(neg_pos), NEG_CAP) + NEG_LABEL * min(len(neg_lab), max(0, NEG_CAP - len(neg_pos)))
    if penalised:
        points -= AMBIG_POSITIONING if any(w == "positioning" for _, w in penalised) else AMBIG_LABEL
    return RecordEvidence(points, tuple(spec_pos + spec_lab), tuple(gen_pos + gen_lab), tuple(neg_pos + neg_lab),
                          tuple(t for t, _ in penalised), tuple(neutralised))


def structural_priority(attrs: dict, policy: IcpPolicy | dict | None = None) -> int:
    """prequalify() priority WITHOUT the points derived from record wording (those are re-derived, with
    specificity, by record_evidence). Exchange listing, headcount and vendor/identity flags are kept."""
    return sum(p for p, _, kind in _priority_parts(attrs or {}, _policy(policy)) if kind == "structural")


@dataclass(frozen=True)
class Ranked:
    candidate: object
    priority: int
    reasons: list
    breadth: int
    positive: tuple
    negative: tuple
    rank_score: int | None = None  # specificity-aware ordering score; None = legacy ordering for this policy
    evidence: RecordEvidence | None = None

    def tie_break(self) -> dict:
        """Explanation for the manifest; empty when no record text distinguished this candidate."""
        if self.evidence is not None:
            out = {"rank_score": self.rank_score, **self.evidence.explain()}
            if not (self.positive or self.negative or self.evidence.points):
                return {}
            return out
        if not (self.positive or self.negative):
            return {}
        return {"term_breadth": self.breadth, "matched_positive": list(self.positive),
                "matched_negative": list(self.negative)}


def rank_pool(pool: list, seed: str, policy: IcpPolicy | dict | None = None) -> list[Ranked]:
    """Every candidate, best first.

    Legacy policies (no specificity vocabulary): policy priority, then ICP-term breadth, then seeded hash.
    Policies that declare generic/ambiguous terms: structural priority + specificity-aware record evidence
    as ONE score, so broad labels and a high wording-derived priority cannot outrank stronger ICP-specific
    evidence; then breadth, then the hash. prequalify() itself and all qualification scores are unchanged."""
    pol = _policy(policy)
    rows = []
    for c in pool:
        attrs = c.attrs or {}
        pri, why = prequalify(attrs, pol)
        net, pos, neg = term_breadth(attrs, pol)
        if pol.prequalify.uses_specificity:
            ev = record_evidence(attrs, pol)
            rows.append(Ranked(c, pri, why, net, tuple(pos), tuple(neg), structural_priority(attrs, pol) + ev.points, ev))
        else:
            rows.append(Ranked(c, pri, why, net, tuple(pos), tuple(neg)))
    rows.sort(key=lambda r: (-(r.priority if r.rank_score is None else r.rank_score), -r.breadth,
                             hashlib.sha256(f"{seed}|{r.candidate.domain}".encode()).hexdigest()))
    return rows


def order_pool(pool: list, seed: str, policy: IcpPolicy | dict | None = None) -> list[tuple]:
    """[(candidate, priority, reasons)] best first (see rank_pool)."""
    return [(r.candidate, r.priority, r.reasons) for r in rank_pool(pool, seed, policy)]


def coverage(pool: list, policy: IcpPolicy | dict | None = None) -> dict:
    """Describe discovery records; does not claim leads match or buy."""
    pol = _policy(policy)
    rows = [(c.attrs or {}) for c in pool]
    positive = sum(_description_matches(a.get("description") or "", True, pol) for a in rows)
    negative = sum(_description_matches(a.get("description") or "", False, pol) for a in rows)
    result = {
        "pool": len(rows),
        "with_record_description": sum(bool(a.get("description")) for a in rows),
        "target_like_description": positive,
        "negative_like_description": negative,
        "listed_on_exchange": sum(bool(a.get("listed_on_exchange")) for a in rows),
    }
    if pol.id == baseline_policy().id:
        # Old manifest/report keys remain valid for the default frontend-studio ICP.
        result["agency_like_description"] = positive
        result["vendor_like_description"] = negative
    return result
