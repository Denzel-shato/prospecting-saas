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


@lru_cache(maxsize=128)
def _matcher(terms: tuple[str, ...]) -> re.Pattern:
    """Match validated whole words/phrases; a trailing * requires a word continuation."""
    parts = []
    for term in terms:
        wild = term.endswith("*")
        stem = term[:-1] if wild else term
        fragment = re.escape(stem).replace(r"\ ", r"\s+")
        parts.append(fragment + (r"\w+" if wild else ""))
    return re.compile(r"(?<!\w)(?:" + "|".join(parts) + r")(?!\w)", re.I) if parts else re.compile(r"(?!)")


def _description_matches(description: str, positive: bool, policy: IcpPolicy) -> bool:
    terms = policy.prequalify.positive_terms if positive else policy.prequalify.negative_terms
    return bool(_matcher(terms).search(description))


def prequalify(attrs: dict, policy: IcpPolicy | dict | None = None) -> tuple[int, list[str]]:
    """Return (priority, reasons) based on public discovery-record fields only."""
    pol = _policy(policy)
    is_baseline = pol.id == baseline_policy().id
    score, reasons = 0, []
    desc = (attrs.get("description") or "").strip()
    if desc:
        if _description_matches(desc, True, pol):
            score += 3
            reasons.append("+3 record description reads like a services studio/agency" if is_baseline
                           else "+3 record description matches ICP's preferred discovery terms")
        if _description_matches(desc, False, pol):
            score -= 3
            reasons.append("-3 record description reads like a product/platform/enterprise company" if is_baseline
                           else "-3 record description matches ICP's negative discovery terms")
    if pol.target_type.id == "agency_studio" and attrs.get("directory_vendor_hint"):
        score -= 3
        reasons.append("-3 directory profile reads like a product/hosting vendor with no agency/studio wording")
    if pol.target_type.id == "agency_studio" and attrs.get("directory_service_hint"):
        score += 3
        reasons.append("+3 directory profile suggests client services")
        if attrs.get("directory_frontend_hint"):
            score += 1
            reasons.append("+1 directory profile mentions relevant frontend or headless work")
        # Source identity wording is a weak TIE-BREAK signal only. Almost every
        # record in this provider's Software Development category gets +3,
        # which otherwise leaves the shortlist ordered by an arbitrary hash.
        if attrs.get("directory_software_focus_hint"):
            score += 2
            reasons.append("+2 directory name/tagline explicitly describes software/product development")
        elif attrs.get("directory_marketing_focus_hint"):
            score -= 1
            reasons.append("-1 directory name/tagline suggests marketing-led rather than software-led services")
    if attrs.get("listed_on_exchange"):
        score -= 4
        reasons.append("-4 listed on a stock exchange (record)")
    emp = attrs.get("employees")
    if isinstance(emp, int) and not isinstance(emp, bool):
        hard = pol.size.hard_max
        lo, hi = pol.size.band
        if emp > hard:
            score -= 3
            reasons.append(f"-3 record headcount {emp} above {hard}")
        elif lo <= emp <= hi:
            score += 1
            reasons.append(f"+1 record headcount {emp} within {lo}-{hi} (may be stale)")
    return score, reasons


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


@dataclass(frozen=True)
class Ranked:
    candidate: object
    priority: int
    reasons: list
    breadth: int
    positive: tuple
    negative: tuple

    def tie_break(self) -> dict:
        """Explanation for the manifest; empty when no record text distinguished this candidate."""
        if not (self.positive or self.negative):
            return {}
        return {"term_breadth": self.breadth, "matched_positive": list(self.positive),
                "matched_negative": list(self.negative)}


def rank_pool(pool: list, seed: str, policy: IcpPolicy | dict | None = None) -> list[Ranked]:
    """Every candidate, best first. Order: policy priority, then ICP-term breadth in the record's own text,
    then the seeded hash. The hash only separates candidates that no available signal distinguishes."""
    pol = _policy(policy)
    rows = []
    for c in pool:
        attrs = c.attrs or {}
        pri, why = prequalify(attrs, pol)
        net, pos, neg = term_breadth(attrs, pol)
        rows.append(Ranked(c, pri, why, net, tuple(pos), tuple(neg)))
    rows.sort(key=lambda r: (-r.priority, -r.breadth,
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
