"""UNSENT outreach drafts, built only from evidence-backed claims.

* Every factual sentence is generated from a (template, evidence-id) pair; evidence that is not
  source_supported/corroborated/user_verified, or that failed verification, is OMITTED.
* No recipient email is ever set (``email: None``, ``email_status: not_collected``).
* No claims about growth, hiring, funding, awards, pain or intent (lint-enforced).
* Seller identity stays as {{PLACEHOLDERS}} for the human reviewer; nothing here can send.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field

from .evidence import ASSERTABLE_LEVELS, Evidence
from .people import DecisionMaker

SERVICE_WORDING = {
    "react": "React", "nextjs": "Next.js", "typescript": "TypeScript",
    "frontend": "frontend work", "web_app": "web application / SaaS interface work",
    "custom_software": "custom software development",
}
BANNED_ASSERTIONS = re.compile(
    r"\b(?:growing|growth|hiring|raised|funding|funded|recent(?:ly)?|congrat\w*|noticed you|saw that you|"
    r"expanding|launch(?:ed)?|award\w*|scal(?:e|ing) up|overwhelmed|busy|need(?:s)? help|struggl\w*|"
    r"looking for|deadline|backlog|behind schedule)\b", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PLACEHOLDER_RE = re.compile(r"\{\{[A-Z_]+\}\}")
STATUS = "UNSENT_DRAFT"


@dataclass
class Draft:
    domain: str
    company_name: str
    status: str
    recipient: dict
    subject: str
    body: str
    claims_used: list[dict] = field(default_factory=list)
    omitted_claims: list[dict] = field(default_factory=list)
    placeholders: list[str] = field(default_factory=list)
    lint: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    def to_text(self) -> str:
        return (f"*** {self.status} — NOT SENT — human review required ***\n"
                f"To: {self.recipient['name'] or '(no named contact found)'} "
                f"<email not collected>\nSubject: {self.subject}\n\n{self.body}\n")


def lint_draft(draft: Draft, evidence_by_id: dict[str, Evidence], verified_ids: set[str]) -> dict:
    issues: list[str] = []
    scan = draft.subject + "\n" + draft.body
    if BANNED_ASSERTIONS.search(scan):
        issues.append(f"banned assertion wording: {BANNED_ASSERTIONS.search(scan).group(0)!r}")
    if EMAIL_RE.search(scan):
        issues.append("email address present in draft text")
    if draft.recipient.get("email") is not None:
        issues.append("recipient email must be None")
    if draft.status != STATUS:
        issues.append("status must be UNSENT_DRAFT")
    for claim in draft.claims_used:
        ev = evidence_by_id.get(claim["evidence_id"])
        if ev is None:
            issues.append(f"claim references unknown evidence {claim['evidence_id']}")
        elif ev.level not in ASSERTABLE_LEVELS:
            issues.append(f"claim uses non-assertable level {ev.level} ({ev.id})")
        elif ev.id not in verified_ids:
            issues.append(f"claim uses unverified evidence {ev.id}")
    return {"passed": not issues, "issues": issues, "unsupported_factual_assertions": len(issues)}


def build_draft(
    *, domain: str, company_name: str, evidence: list[Evidence], verified_ids: set[str],
    decision_makers: list[DecisionMaker],
) -> Draft | None:
    by_id = {e.id: e for e in evidence}
    usable_services: list[Evidence] = []
    omitted: list[dict] = []
    for e in evidence:
        if not e.claim_type.startswith("service:") or e.claim_type.split(":", 1)[1] not in SERVICE_WORDING:
            continue
        if e.level in ASSERTABLE_LEVELS and e.id in verified_ids:
            usable_services.append(e)
        else:
            omitted.append({"evidence_id": e.id, "claim_type": e.claim_type,
                            "reason": f"level={e.level} verified={e.id in verified_ids}"})
    if not usable_services:
        return None  # nothing source-supported to ground a personalised draft in

    named = decision_makers[0] if decision_makers else None
    first = named.name.split()[0] if named else None
    salutation = f"Hi {first}," if first else f"Hello {company_name} team,"
    wording = [SERVICE_WORDING[e.claim_type.split(':', 1)[1]] for e in usable_services][:3]
    listed = ", ".join(wording[:-1]) + (" and " if len(wording) > 1 else "") + wording[-1]

    sentences: list[tuple[str, list[str]]] = [
        (f"I'm {{{{SELLER_NAME}}}}, an independent React/Next.js frontend developer.", []),
        (f"Your website mentions {listed}, which overlaps with the work I do.",
         [e.id for e in usable_services[:3]]),
        ("If extra frontend capacity could ever be useful on a client project, I'd be glad to share "
         "relevant examples: {{SELLER_PORTFOLIO_URL}}.", []),
        ("If this isn't relevant, no problem at all, just let me know and I won't follow up.", []),
    ]
    body = salutation + "\n\n" + " ".join(s for s, _ in sentences) + "\n\nBest,\n{{SELLER_NAME}}"
    claims = [{"sentence": s, "evidence_id": eid, "level": by_id[eid].level,
               "source_url": by_id[eid].source_url}
              for s, ids in sentences for eid in ids]
    subject = "Quick question about frontend capacity at " + company_name
    placeholders = sorted(set(PLACEHOLDER_RE.findall(body)))
    draft = Draft(
        domain=domain, company_name=company_name, status=STATUS,
        recipient={"name": named.name if named else None, "title": named.title if named else None,
                   "email": None, "email_status": "not_collected",
                   "name_source_url": named.source_url if named else None},
        subject=subject, body=body, claims_used=claims, omitted_claims=omitted, placeholders=placeholders)
    draft.lint = lint_draft(draft, by_id, verified_ids)
    return draft
