"""Deterministic PRE-research prioritisation of discovery candidates.

Why this exists: the Wikidata query returns generic US "software company" items (product vendors,
enterprises, ...). Sampling 40 of them by hash ignores the ICP (small independent client-services
studios). This module orders the pool using ONLY fields already present in the discovery record
(description, listed-on-exchange flag, headcount); it never fetches anything.

It is a PRIORITISATION aid, not a qualifier and not a filter: nothing is dropped here and no
score from here reaches the lead score. Final company type is decided later from first-party
evidence (see score.classify_company). Candidates with no usable record fields (manual CSV,
synthetic fixtures, bare Wikidata items) all score 0 and keep the original hash order.
"""

from __future__ import annotations

import hashlib
import re

AGENCY_DESC_RE = re.compile(
    r"\b(?:agency|studio|consult(?:ancy|ing)|web (?:design|development)|software development (?:company|firm|agency)|"
    r"app development|custom software|digital (?:product|design|agency)|outsourc\w+|design and development|"
    r"development (?:company|shop|firm))\b", re.I)
VENDOR_DESC_RE = re.compile(
    r"\b(?:platform|saas|software as a service|cloud|enterprise|multinational|search engine|social (?:network|media)|"
    r"operating system|database|cyber ?security|identity|video game|marketplace|e-?commerce|fintech|"
    r"artificial intelligence|machine learning)\b", re.I)
LARGE_HEADCOUNT = 250
BAND = (5, 50)


def prequalify(attrs: dict) -> tuple[int, list[str]]:
    """(priority, reasons) from discovery-record fields only. Higher = researched earlier."""
    score, reasons = 0, []
    desc = (attrs.get("description") or "").strip()
    if desc:
        if AGENCY_DESC_RE.search(desc):
            score += 3
            reasons.append("+3 record description reads like a services studio/agency")
        if VENDOR_DESC_RE.search(desc):
            score -= 3
            reasons.append("-3 record description reads like a product/platform/enterprise company")
    if attrs.get("listed_on_exchange"):
        score -= 4
        reasons.append("-4 listed on a stock exchange (record)")
    emp = attrs.get("employees")
    if isinstance(emp, int):
        if emp > LARGE_HEADCOUNT:
            score -= 3
            reasons.append(f"-3 record headcount {emp} above {LARGE_HEADCOUNT}")
        elif BAND[0] <= emp <= BAND[1]:
            score += 1
            reasons.append(f"+1 record headcount {emp} within {BAND[0]}-{BAND[1]} (may be stale)")
    return score, reasons


def order_pool(pool: list, seed: str) -> list[tuple]:
    """[(candidate, priority, reasons)] sorted by (-priority, seeded hash): deterministic."""
    rows = []
    for c in pool:
        pri, why = prequalify(c.attrs or {})
        rows.append((c, pri, why))
    rows.sort(key=lambda r: (-r[1], hashlib.sha256(f"{seed}|{r[0].domain}".encode()).hexdigest()))
    return rows


def coverage(pool: list) -> dict:
    """How much of the pool carries ANY agency-relevant signal? Reported, never assumed."""
    n = len(pool)
    with_desc = sum(1 for c in pool if (c.attrs or {}).get("description"))
    agency = sum(1 for c in pool if AGENCY_DESC_RE.search((c.attrs or {}).get("description") or ""))
    vendor = sum(1 for c in pool if VENDOR_DESC_RE.search((c.attrs or {}).get("description") or ""))
    listed = sum(1 for c in pool if (c.attrs or {}).get("listed_on_exchange"))
    return {"pool": n, "with_record_description": with_desc, "agency_like_description": agency,
            "vendor_like_description": vendor, "listed_on_exchange": listed}
