"""Engine #6 V2 deterministic verification of AI-extracted decision makers.

Offline, stdlib only, no AI call. Input: the AI's JSON plus the ``EvidencePassage`` records produced by
``evidence_prep``. Output: one ``Verdict`` per claimed person: ``accepted`` | ``rejected`` | ``manual_review``
with a machine-readable reason.

Checks (first failure wins; rejections precede manual review):
1. structure: name, role, company, passage_id, quote are non-empty strings
2. passage_id exists in the supplied passages
3. quote is an exact substring of the passage text (whitespace-normalised, case-sensitive, min length)
4. name is a plausible person name (existing ``people.valid_name``) and appears in the quote
5. role appears in the quote (case-insensitive)
6. company matches the target (existing ``people.org_matches``) and the quote does not tie the role to
   a different organisation
7. passage third-party risk flags (quote / client / editorial / testimonial section) reject; unclear
   context flags (adjacent_quote, context_unknown, footer, aside, unclassified article), a non-leadership role, or an
   untrusted page kind route to manual review. A first-person quotation followed by a name/title is
   still only adjacent attribution: unless the quote and speaker/company link are present together
   in verifiable first-party evidence, it remains manual review and is never auto-promoted.

A passage containing a statement does not prove it is true; ``accepted`` means "supported by the quoted
first-party text", nothing more.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Iterable

from ..htmlparse import norm_ws
from ..people import org_matches, valid_name
from ..e6v2.evidence_prep import EvidencePassage, EvidencePrepResult, _ROLE_RE

ACCEPTED = "accepted"
REJECTED = "rejected"
MANUAL_REVIEW = "manual_review"

MIN_QUOTE_CHARS = 8
REQUIRED_FIELDS = ("name", "role", "company", "passage_id", "quote")
REJECT_FLAGS = frozenset({"ctx:quote", "ctx:client", "ctx:editorial", "section:third_party",
                          "page:editorial", "page:work"})
REVIEW_FLAGS = frozenset({"adjacent_quote", "context_unknown", "ctx:footer", "ctx:aside", "ctx:article_unknown"})
TRUSTED_PAGE_KINDS = frozenset({"team", "about", "home"})

_CLIENT_WORDS_RE = re.compile(r"(?i)\b(?:testimonials?|clients?|customers?|case stud(?:y|ies)|reviews?)\b")
# "<Role> at/of/@ <Org Name>" -- captures the organisation that follows the role.
_ORG_AFTER_ROLE_RE = re.compile(
    r"(?:\bat\b|\bof\b|@|,)\s+((?:[A-Z][\w&'’.\-]*)(?:\s+(?:[A-Z][\w&'’.\-]*|&|and)){0,3})")


@dataclass(frozen=True)
class Verdict:
    status: str
    reason: str
    name: str = ""
    role: str = ""
    company: str = ""
    passage_id: str = ""
    quote: str = ""

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def _verdict(status: str, reason: str, item: Any) -> Verdict:
    get = item.get if isinstance(item, dict) else (lambda k, d="": d)

    def s(k):
        v = get(k, "")
        return v if isinstance(v, str) else ""
    return Verdict(status, reason, s("name"), s("role"), s("company"), s("passage_id"), s("quote"))


def _items(ai_json: Any) -> list:
    if isinstance(ai_json, (str, bytes)):
        try:
            ai_json = json.loads(ai_json)
        except (ValueError, TypeError):
            return [None]
    if isinstance(ai_json, dict):
        ai_json = ai_json.get("decision_makers", [])
    return list(ai_json) if isinstance(ai_json, list) else [None]


def _passage_map(passages: Any) -> dict:
    if isinstance(passages, EvidencePrepResult):
        return passages.by_id()
    if isinstance(passages, dict):
        return passages
    return {p.passage_id: p for p in passages}


def _foreign_org(quote: str, role: str, company_key: str, company_name: str | None) -> str | None:
    """Organisation the quote attaches to the role, when it is not the target company."""
    start = quote.lower().find(role.lower())
    tail = quote[start + len(role):] if start >= 0 else ""
    m = _ORG_AFTER_ROLE_RE.match(tail.lstrip()) if tail else None
    if not m:
        return None
    org = m.group(1).strip()
    return None if org_matches(org, company_key, company_name) else org


def _verify_one(item: Any, passages: dict, company_key: str, company_name: str | None) -> Verdict:
    if not isinstance(item, dict):
        return _verdict(REJECTED, "malformed_entry", item)
    for f in REQUIRED_FIELDS:
        v = item.get(f)
        if not isinstance(v, str) or not norm_ws(v):
            return _verdict(REJECTED, f"missing_or_invalid_{f}", item)
    name, role = norm_ws(item["name"]), norm_ws(item["role"])
    company, quote = norm_ws(item["company"]), norm_ws(item["quote"])

    passage: EvidencePassage | None = passages.get(item["passage_id"].strip())
    if passage is None:
        return _verdict(REJECTED, "unknown_passage_id", item)
    text = norm_ws(passage.text)
    if len(quote) < MIN_QUOTE_CHARS or quote not in text:
        return _verdict(REJECTED, "quote_not_in_passage", item)
    if not valid_name(name):
        return _verdict(REJECTED, "invalid_person_name", item)
    if not re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", quote):
        return _verdict(REJECTED, "name_not_in_quote", item)
    if role.lower() not in quote.lower():
        return _verdict(REJECTED, "role_not_in_quote", item)
    if not org_matches(company, company_key, company_name):
        return _verdict(REJECTED, "company_mismatch", item)
    if _foreign_org(quote, role, company_key, company_name):
        return _verdict(REJECTED, "role_tied_to_other_company", item)

    flags = set(passage.risk_flags)
    if flags & REJECT_FLAGS:
        return _verdict(REJECTED, "third_party_context:" + ",".join(sorted(flags & REJECT_FLAGS)), item)
    if _CLIENT_WORDS_RE.search(quote) or any(_CLIENT_WORDS_RE.search(h) for h in passage.headings):
        return _verdict(REJECTED, "testimonial_or_client_attribution", item)
    if flags & REVIEW_FLAGS:
        return _verdict(MANUAL_REVIEW, "unclear_context:" + ",".join(sorted(flags & REVIEW_FLAGS)), item)
    if passage.page_kind not in TRUSTED_PAGE_KINDS:
        return _verdict(MANUAL_REVIEW, f"page_kind_{passage.page_kind}", item)
    if not _ROLE_RE.search(role):
        return _verdict(MANUAL_REVIEW, "role_not_recognised_leadership", item)
    return _verdict(ACCEPTED, "supported_by_first_party_quote", item)


def verify_decision_makers(ai_json: Any, passages: EvidencePrepResult | Iterable[EvidencePassage] | dict,
                           company_key: str, company_name: str | None = None) -> list[Verdict]:
    """Verify each claimed decision maker in ``ai_json`` against ``passages`` for the target company."""
    pmap = _passage_map(passages)
    return [_verify_one(i, pmap, company_key, company_name) for i in _items(ai_json)]
