"""Deterministic, policy-aware PRE-research prioritisation of discovery candidates.

Uses only discovery-record description, listed-on-exchange flag and reported headcount.
Prequalification determines research order, never lead qualification or score.

With no explicit policy, this is the legacy frontend-studio ordering. Different
ICPs can use different description terms without changing evidence extraction.
"""

from __future__ import annotations

import hashlib
import re
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


def order_pool(pool: list, seed: str, policy: IcpPolicy | dict | None = None) -> list[tuple]:
    """[(candidate, priority, reasons)] ordered by policy priority then seeded hash."""
    pol = _policy(policy)
    rows = []
    for c in pool:
        pri, why = prequalify(c.attrs or {}, pol)
        rows.append((c, pri, why))
    rows.sort(key=lambda r: (-r[1], hashlib.sha256(f"{seed}|{r[0].domain}".encode()).hexdigest()))
    return rows


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
