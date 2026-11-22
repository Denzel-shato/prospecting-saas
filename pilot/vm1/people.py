"""Decision-maker extraction from FIRST-PARTY pages only.

A person is reported only when the company's own site names them next to a target role AND the
context credibly ties them to THIS company. A founder/CEO/CTO string on a first-party page is not
enough: it may be a testimonial, a client case study, a partner, a blog author, a customer
executive or the head of some other organisation. Credible context is one of:
  * an explicit "at <org>" that matches the target company;
  * a team / leadership / about page (URL kind) outside any quote/client/editorial structure;
  * a team-style heading above the block (e.g. "Meet the team") with no third-party heading;
  * JSON-LD where the person is founder/employee of an Organization matching the target company.
Otherwise the answer is an explicit "unknown" (no person), never a guess.
The result means "the company's site says so" (source_supported), never "verified current".
No email addresses or other contact details are extracted, inferred, or guessed.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass

from .context import (NON_SELF_KINDS, TEAM_SECTION_RE, THIRD_PARTY_CTX, THIRD_PARTY_SECTION_RE,
                      looks_like_quote_neighbour, page_kind)
from .evidence import SOURCE_SUPPORTED, PageSnapshot, name_forms
from .htmlparse import norm_ws

_ROLE = (
    r"(?:co-?founder|founding partner|co-?owner|founder|chief executive officer|chief executive|ceo|chief technology officer|cto|"
    r"chief operating officer|coo|managing director|managing partner|president|owner|principal|"
    r"head of (?:engineering|delivery|product|technology)|"
    r"(?:vp|vice president)(?: of)? engineering|"
    r"director of (?:engineering|delivery|technology)|engineering director|delivery director)"
)
_TITLE = (rf"(?i:{_ROLE}(?:\s*(?:&|and|/|,)\s*{_ROLE})*(?:\s*(?:&|and|/|,)\s*partner)?"
          r"(?:\s*(?:&|and|/|\+)\s*(?:[A-Za-z]+ ){0,2}[A-Za-z]+)?)")  # title case-insensitive, names are not
_ORG_TAIL = r"(?:\s+(?i:at|of|@)\s+(?P<org>[\w&.'’ -]{2,50}))?"
TITLE_ONLY_RE = re.compile(rf"^(?P<title>{_TITLE}){_ORG_TAIL}$")
_UP, _LOW = "A-ZÀ-ÖØ-Þ", "a-zà-öø-ÿ"  # accented letters occur in real names (worldwide ICP)
_TOK = rf"[{_UP}][{_LOW}{_UP}'’\-]+"
_PART = r"(?:van|von|de|del|della|der|den|da|di|du|dos|le|la|ten|ter|bin|al|el)"
_NAME = rf"{_TOK}(?: [{_UP}]\.)?(?: (?:{_PART} ){{0,2}}{_TOK}){{1,2}}"
_SEP = r"\s*[,|–—\-:·•]\s*"
NAME_TITLE_RE = re.compile(rf"^(?P<name>{_NAME}){_SEP}(?P<title>{_TITLE}){_ORG_TAIL}$")
TITLE_NAME_RE = re.compile(rf"^(?P<title>{_TITLE}){_SEP}(?P<name>{_NAME})$")
NAME_ONLY_RE = re.compile(rf"^{_NAME}$")
# Prose self-descriptions. The organisation is REQUIRED and must match the target company (see org_matches), so a
# client's or partner's executive ("Jane Doe is the CEO of Clientco") never attributes.
_PROSE_ORG = r"(?P<org>[\w&.'’ -]{2,50}?)(?=[.,;!]|\s+(?:in|since|where|with|and)\b|$)"
PROSE_IS_RE = re.compile(rf"(?:^|(?<=[.!?] ))(?P<name>{_NAME}) (?:is|serves as|has been) (?:the |our |a |an )?"
                         rf"(?:[\w-]+ ){{0,2}}?(?P<title>{_TITLE}) (?:of|at) {_PROSE_ORG}")
PROSE_IAM_RE = re.compile(rf"\b(?:I(?:'|’)m|I am) (?P<name>{_NAME}),? (?:the |a |an )?(?P<title>{_TITLE}) (?:of|at) {_PROSE_ORG}")
PROSE_FOUNDED_RE = re.compile(rf"(?:^|(?<=[.!?] ))(?P<org>[A-Z][\w&.'’ -]{{1,50}}?) (?:was |is )?(?:co-?)?founded by "
                              rf"(?P<name>{_NAME})(?=[.,;!]|\s+(?:in|and|with|after|back)\b|$)")

NAME_STOPWORDS = {
    "our", "team", "about", "the", "and", "meet", "contact", "services", "company", "studio",
    "founder", "ceo", "cto", "head", "director", "leadership", "us", "we", "careers", "blog",
    "work", "read", "more", "get", "started", "view", "all", "senior", "lead", "manager",
    "engineer", "developer", "designer", "story", "chief", "officer", "managing", "vice",
    "president", "owner", "principal", "partner", "agency", "software", "digital", "web",
    "case", "study", "studies", "learn", "book", "call", "free", "quote", "home", "privacy",
    "policy", "terms", "cookie", "inc", "llc", "ltd", "of", "at", "in", "for", "with",
}
# Tokens that make a "name" an ORGANISATION (e.g. a client brand heading above a title), not a person.
ORG_WORDS = {
    "hub", "labs", "lab", "partners", "group", "studio", "studios", "solutions", "technologies",
    "technology", "systems", "software", "digital", "ventures", "capital", "consulting", "agency",
    "media", "works", "network", "holdings", "enterprises", "industries", "global", "services",
    "platform", "collective", "foundation", "institute", "university", "bank", "press", "apps",
    "app", "cloud", "data", "ai", "io", "corp", "company", "co", "homes", "health", "financial", "practice",
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
    basis: str = ""  # why this person is attributed to the target company

    def to_dict(self) -> dict:
        return asdict(self)


def _role_class(title: str) -> tuple[str, int]:
    t = title.lower()
    if re.search(r"found(?:er|ing)|ceo|chief executive|owner|president|managing (?:director|partner)", t):
        return "founder_ceo", 1
    if re.search(r"cto|chief technology|engineering|technology|delivery", t):
        return "cto_eng", 2
    return "other_leader", 3


def valid_name(name: str) -> bool:
    tokens = [t.strip(".").lower() for t in name.split()]
    if not 2 <= len(tokens) <= 4 or len(name) > 40:
        return False
    return not any(t in NAME_STOPWORDS or t in ORG_WORDS for t in tokens)


def _norm_org(s: str) -> str:
    toks = [t for t in re.findall(r"[a-z0-9]+", s.lower()) if t not in
            {"inc", "llc", "ltd", "co", "corp", "company", "gmbh", "limited", "the"}]
    return "".join(toks)


def org_matches(org: str | None, company_key: str | None, company_name: str | None) -> bool:
    """Does the organisation named next to a title denote the target company? Conservative:
    unknown target => no match."""
    if not org:
        return False
    o = _norm_org(org)
    if not o:
        return False
    for form in name_forms(company_key or "", company_name):
        f = _norm_org(form)
        if len(f) >= 4 and (o == f or o.startswith(f) or f.startswith(o) and len(o) >= 4):
            return True
    return False


_BAD_JSONLD_KEYS = {"author", "creator", "review", "reviews", "contributor", "editor", "reviewedBy",
                    "performer", "speaker", "customer", "client", "sponsor", "funder", "citation",
                    "mentions", "about", "recipient", "attendee", "participant", "interviewee"}
_GOOD_JSONLD_KEYS = {"founder", "founders", "employee", "employees", "member", "members", "ceo", "leader"}
_ORG_TYPES = {"Organization", "Corporation", "LocalBusiness", "ProfessionalService", "Company",
              "OnlineBusiness", "NGO"}


def _types(node: dict) -> set[str]:
    t = node.get("@type")
    return set(t) if isinstance(t, list) else {t} if isinstance(t, str) else set()


def _jsonld_people(page, company_key, company_name):
    """Yield (name, title) for Person nodes credibly affiliated with the TARGET organisation."""
    def walk(node, keys, org):
        if isinstance(node, list):
            for v in node:
                yield from walk(v, keys, org)
        elif isinstance(node, dict):
            types = _types(node)
            if types & _ORG_TYPES and isinstance(node.get("name"), str):
                org = node["name"]
            if "Person" in types and not (set(keys) & _BAD_JSONLD_KEYS):
                name, title = node.get("name"), node.get("jobTitle")
                works_for = node.get("worksFor")
                wf = works_for.get("name") if isinstance(works_for, dict) else None
                affiliated = org_matches(wf, company_key, company_name) or (
                    bool(set(keys) & _GOOD_JSONLD_KEYS) and org_matches(org, company_key, company_name))
                if affiliated and isinstance(name, str) and isinstance(title, str):
                    yield name, title
            for k, v in node.items():
                if k.startswith("@"):
                    continue
                yield from walk(v, keys + [k], org)

    for raw in page.jsonld_raw:
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        yield from walk(data, [], None)


def find_decision_makers(snaps: list[PageSnapshot], limit: int = 3, *, company_key: str | None = None,
                         company_name: str | None = None) -> list[DecisionMaker]:
    found: dict[str, DecisionMaker] = {}

    def add(name: str, title: str, snap: PageSnapshot, parts: list[str], basis: str) -> None:
        name, title = norm_ws(name), norm_ws(title)
        if not valid_name(name):
            return
        cls, rank = _role_class(title)
        prev = found.get(name.lower())
        if prev is not None and not (rank <= prev.rank and len(title) > len(prev.title)):
            return  # already have this person; only replace with a more specific title
        found[name.lower()] = DecisionMaker(
            name=name, title=title, role_class=cls, source_url=snap.url, fetched_at=snap.fetched_at,
            excerpt=" … ".join(parts)[:200], excerpt_parts=[p[:200] for p in parts], rank=rank, basis=basis)

    def credible_basis(snap: PageSnapshot, i: int, org: str | None, kind: str) -> str | None:
        """None => cannot tie this person to the target company => unknown."""
        page = snap.page
        if org is not None:  # "<title> at <org>": the org must be the target, else it is someone else
            return "explicit_org_match" if org_matches(org, company_key, company_name) else None
        if kind == "team":
            return "team_page"
        if TEAM_SECTION_RE.search(page.section_at(i)):
            return "team_section"
        if kind == "about":
            return "about_page"
        return None

    for snap in snaps:
        page = snap.page
        kind = page_kind(snap.url, snap.is_homepage)
        if kind in NON_SELF_KINDS:
            continue  # blog/docs/careers/case-study pages never name THIS company's decision-makers
        blocks = page.blocks
        for i, block in enumerate(blocks):
            if len(block) > 300:
                continue
            if (page.ctx_at(i) & THIRD_PARTY_CTX) or THIRD_PARTY_SECTION_RE.search(page.section_at(i)):
                continue  # testimonial / client / partner / editorial structure
            if looks_like_quote_neighbour(page, i):
                continue  # attribution line under a quotation
            if looks_like_quote_neighbour(page, i):
                continue
            for pm in (PROSE_IS_RE.search(block), PROSE_IAM_RE.search(block)):
                if pm and org_matches(pm.group("org"), company_key, company_name):
                    add(pm.group("name"), pm.group("title"), snap, [block], "explicit_org_match")
            fm = PROSE_FOUNDED_RE.search(block)
            if fm and org_matches(fm.group("org"), company_key, company_name):
                add(fm.group("name"), "Founder", snap, [block], "explicit_org_match")
            if len(block) > 120:
                continue
            m = NAME_TITLE_RE.match(block) or TITLE_NAME_RE.match(block)
            if m:
                basis = credible_basis(snap, i, m.groupdict().get("org"), kind)
                if basis:
                    add(m.group("name"), m.group("title"), snap, [block], basis)
                continue
            if TITLE_ONLY_RE.match(block) and i + 1 < len(blocks):
                # Reversed card layout: the title block precedes the name block.
                nxt = blocks[i + 1]
                owned = i > 0 and NAME_ONLY_RE.match(blocks[i - 1])  # a name above owns this title (name-first card)
                if not owned and NAME_ONLY_RE.match(nxt) and not (page.ctx_at(i + 1) & THIRD_PARTY_CTX):
                    basis = credible_basis(snap, i, TITLE_ONLY_RE.match(block).groupdict().get("org"), kind)
                    if basis:
                        add(nxt, block, snap, [block, nxt], basis)
                continue
            if NAME_ONLY_RE.match(block) and i + 1 < len(blocks):
                nxt = blocks[i + 1]
                if len(nxt) <= 60 and not (page.ctx_at(i + 1) & THIRD_PARTY_CTX):
                    tm = TITLE_ONLY_RE.match(nxt)
                    if tm:
                        basis = credible_basis(snap, i, tm.groupdict().get("org"), kind)
                        if basis:
                            add(block, nxt, snap, [block, nxt], basis)
        # JSON-LD: only Person nodes affiliated with the TARGET organisation (never authors/reviews)
        raw = " ".join(page.jsonld_raw)
        for name, title in _jsonld_people(page, company_key, company_name):
            # Raw JSON-LD may carry non-ASCII names as \\uXXXX escapes; accept either spelling of the same text.
            def present(text: str) -> bool:
                return text in raw or json.dumps(text)[1:-1] in raw

            if TITLE_ONLY_RE.match(title.strip()) and present(name) and present(title):
                add(name, title, snap, [name, title], "jsonld_org")
    ranked = sorted(found.values(), key=lambda d: d.rank)  # stable: page order within a rank
    return ranked[:limit]
