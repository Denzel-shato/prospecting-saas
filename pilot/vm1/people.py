"""Decision-maker extraction from FIRST-PARTY pages only, with attribution to the TARGET company.

A founder/CEO/CTO name on a company's website is not automatically that company's decision-maker: it may
be a testimonial author, a client or partner executive, a blog author or someone at another organisation.
A person is reported only when there is credible context tying them to THIS company:

  * the title itself names the company ("Founder at Acme") — a title naming ANOTHER organisation is rejected;
  * the block sits on a team/about/leadership page, or under a team/leadership/founders heading, and is not
    inside testimonial/client/partner/blog/docs structure; or
  * JSON-LD says the person works for / founded the organisation whose name matches the company.

Otherwise the answer is "unknown". No email addresses or other contact details are extracted or guessed.
The result means "the company's site says so" (source_supported), never "verified current".
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .context import NON_COMPANY_SPEECH_FLAGS, NON_COMPANY_SPEECH_KINDS, matches_self, page_kind
from .evidence import SOURCE_SUPPORTED, PageSnapshot
from .htmlparse import norm_ws

_ROLE = (
    r"(?:co-?founder|founder|chief executive officer|ceo|chief technology officer|cto|"
    r"chief operating officer|coo|managing director|managing partner|president|owner|principal|"
    r"head of (?:engineering|delivery|product|technology)|"
    r"(?:vp|vice president)(?: of)? engineering|"
    r"director of (?:engineering|delivery|technology)|engineering director|delivery director)"
)
_TITLE = rf"(?i:{_ROLE}(?:\s*(?:&|and|/|,)\s*{_ROLE})*)"  # title case-insensitive, names are not
_ORG_TAIL = r"(?:\s+(?i:at|of)\s+(?P<org>[\w&.' -]{2,40}))?"
TITLE_ONLY_RE = re.compile(rf"^(?P<title>{_TITLE}){_ORG_TAIL}$")
_NAME = r"[A-Z][a-zA-Z'’\-]+(?: [A-Z]\.)?(?: [A-Z][a-zA-Z'’\-]+){1,2}"
_SEP = r"\s*[,|–—\-:·•]\s*"
NAME_TITLE_RE = re.compile(rf"^(?P<name>{_NAME}){_SEP}(?P<title>{_TITLE}){_ORG_TAIL}$")
TITLE_NAME_RE = re.compile(rf"^(?P<title>{_TITLE}){_SEP}(?P<name>{_NAME})$")
NAME_ONLY_RE = re.compile(rf"^{_NAME}$")
TEAM_HEADING_RE = re.compile(
    r"(?i)\b(?:our team|the team|team|leadership|founders?|who we are|meet\b|people|management|our story|about)\b")

NAME_STOPWORDS = {
    "our", "team", "about", "the", "and", "meet", "contact", "services", "company", "studio",
    "founder", "ceo", "cto", "head", "director", "leadership", "us", "we", "careers", "blog",
    "work", "read", "more", "get", "started", "view", "all", "senior", "lead", "manager",
    "engineer", "developer", "designer", "story", "chief", "officer", "managing", "vice",
    "president", "owner", "principal", "partner", "agency", "software", "digital", "web",
    "case", "study", "studies", "learn", "book", "call", "free", "quote", "home", "privacy",
    "policy", "terms", "cookie", "inc", "llc", "ltd", "of", "at", "in", "for", "with",
}
# Words that make a "name" an organisation, not a person ("Homeowners Hub", "Acme Labs").
ORG_WORDS = {
    "hub", "labs", "lab", "partners", "group", "ai", "studios", "solutions", "systems", "technologies",
    "technology", "media", "capital", "ventures", "holdings", "health", "homeowners", "home", "network",
    "networks", "platform", "consulting", "corp", "foundation", "institute", "global", "bank", "energy",
    "logistics", "realty", "properties", "insurance", "university", "college", "school", "foods",
}


@dataclass
class DecisionMaker:
    name: str
    title: str
    role_class: str  # founder_ceo | cto_eng | other_leader
    source_url: str
    fetched_at: str
    excerpt: str
    excerpt_parts: list[str]
    level: str = SOURCE_SUPPORTED
    rank: int = 9
    attribution: str = ""  # why this person is tied to the target company

    def to_dict(self) -> dict:
        return asdict(self)


def _role_class(title: str) -> tuple[str, int]:
    t = title.lower()
    if re.search(r"founder|ceo|chief executive|owner|president|managing (?:director|partner)", t):
        return "founder_ceo", 1
    if re.search(r"cto|chief technology|engineering|technology|delivery", t):
        return "cto_eng", 2
    return "other_leader", 3


def valid_name(name: str) -> bool:
    tokens = [t.strip(".").lower() for t in name.split()]
    if not 2 <= len(tokens) <= 4 or len(name) > 40:
        return False
    return not any(t in NAME_STOPWORDS or t in ORG_WORDS for t in tokens)


def _attribute(kind: str, section: str, org: str | None, names: set[str]) -> str | None:
    """Reason this block is credibly about the target company, or None (=> unknown)."""
    if org:
        return "title_names_company" if matches_self(org, names) else None  # another org => reject
    if kind in ("team", "about"):
        return f"{kind}_page"
    if TEAM_HEADING_RE.search(section or ""):
        return "team_section_heading"
    return None


def _parse_block(block: str):
    m = NAME_TITLE_RE.match(block)
    if m:
        return m.group("name"), m.group("title"), m.groupdict().get("org")
    m = TITLE_NAME_RE.match(block)
    if m:
        return m.group("name"), m.group("title"), None
    return None


def _jsonld_people(snap: PageSnapshot, names: set[str]):
    """(name, title, attribution) for Person nodes tied to the company by JSON-LD structure."""
    if not names:
        return
    raw_all = " ".join(snap.page.jsonld_raw)
    for node in snap.page.jsonld_nodes():
        name, title = node.get("name"), node.get("jobTitle")
        if isinstance(name, str) and isinstance(title, str) and TITLE_ONLY_RE.match(title.strip()):
            works = node.get("worksFor")
            works_name = works.get("name") if isinstance(works, dict) else works
            if isinstance(works_name, str) and matches_self(works_name, names) and name in raw_all and title in raw_all:
                yield name, title, "jsonld_worksFor"
        org_name = node.get("name")
        if isinstance(org_name, str) and matches_self(org_name, names):
            for key in ("founder", "founders", "employee", "employees", "member", "members", "owner"):
                val = node.get(key)
                for person in (val if isinstance(val, list) else [val]):
                    if isinstance(person, dict) and isinstance(person.get("name"), str) \
                            and isinstance(person.get("jobTitle"), str) \
                            and TITLE_ONLY_RE.match(person["jobTitle"].strip()) \
                            and person["name"] in raw_all and person["jobTitle"] in raw_all:
                        yield person["name"], person["jobTitle"], f"jsonld_org_{key}"


def find_decision_makers(snaps: list[PageSnapshot], limit: int = 3, names: set[str] | None = None) -> list[DecisionMaker]:
    names = set(names or ())
    found: dict[str, DecisionMaker] = {}

    def add(name: str, title: str, snap: PageSnapshot, parts: list[str], attribution: str) -> None:
        name, title = norm_ws(name), norm_ws(title)
        if not valid_name(name):
            return
        cls, rank = _role_class(title)
        prev = found.get(name.lower())
        if prev is not None and not (rank <= prev.rank and len(title) > len(prev.title)):
            return  # already have this person; only replace with a more specific title
        found[name.lower()] = DecisionMaker(
            name=name, title=title, role_class=cls, source_url=snap.url, fetched_at=snap.fetched_at,
            excerpt=" … ".join(parts)[:200], excerpt_parts=[p[:200] for p in parts], rank=rank,
            attribution=attribution)

    for snap in snaps:
        kind = page_kind(snap.url, snap.is_homepage)
        if kind in NON_COMPANY_SPEECH_KINDS:
            continue
        rows = list(snap.page.iter_blocks())
        for pos, (_i, block, ctx, section) in enumerate(rows):
            if ctx & NON_COMPANY_SPEECH_FLAGS or len(block) > 120:
                continue
            parsed = _parse_block(block)
            if parsed:
                name, title, org = parsed
                why = _attribute(kind, section, org, names)
                if why:
                    add(name, title, snap, [block], why)
                continue
            if NAME_ONLY_RE.match(block) and pos + 1 < len(rows):
                _j, nxt, nctx, nsec = rows[pos + 1]
                tm = TITLE_ONLY_RE.match(nxt) if len(nxt) <= 80 else None
                if tm and not (nctx & NON_COMPANY_SPEECH_FLAGS):
                    why = _attribute(kind, section, tm.groupdict().get("org"), names)
                    if why:
                        add(block, tm.group("title"), snap, [block, nxt], why)
        for name, title, why in _jsonld_people(snap, names):
            add(name, title, snap, [name, title], why)
    ranked = sorted(found.values(), key=lambda d: d.rank)  # stable: page order within a rank
    return ranked[:limit]
