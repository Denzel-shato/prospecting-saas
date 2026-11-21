"""Decision-maker extraction from FIRST-PARTY pages only.

A person is reported only when the company's own site names them next to a target role.
The result means "the company's site says so" (source_supported), never "verified current".
No email addresses or other contact details are extracted, inferred, or guessed.
If nothing is found the answer is an explicit "unknown" (no person), never a guess.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

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
TITLE_ONLY_RE = re.compile(rf"^(?P<title>{_TITLE})(?:\s+(?i:at|of)\s+[\w&.' -]{{2,40}})?$")
_NAME = r"[A-Z][a-zA-Z'’\-]+(?: [A-Z]\.)?(?: [A-Z][a-zA-Z'’\-]+){1,2}"
_SEP = r"\s*[,|–—\-:·•]\s*"
NAME_TITLE_RE = re.compile(rf"^(?P<name>{_NAME}){_SEP}(?P<title>{_TITLE})(?:\s+(?i:at|of)\s+[\w&.' -]{{2,40}})?$")
TITLE_NAME_RE = re.compile(rf"^(?P<title>{_TITLE}){_SEP}(?P<name>{_NAME})$")
NAME_ONLY_RE = re.compile(rf"^{_NAME}$")

NAME_STOPWORDS = {
    "our", "team", "about", "the", "and", "meet", "contact", "services", "company", "studio",
    "founder", "ceo", "cto", "head", "director", "leadership", "us", "we", "careers", "blog",
    "work", "read", "more", "get", "started", "view", "all", "senior", "lead", "manager",
    "engineer", "developer", "designer", "story", "chief", "officer", "managing", "vice",
    "president", "owner", "principal", "partner", "agency", "software", "digital", "web",
    "case", "study", "studies", "learn", "book", "call", "free", "quote", "home", "privacy",
    "policy", "terms", "cookie", "inc", "llc", "ltd", "of", "at", "in", "for", "with",
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
    return not any(t in NAME_STOPWORDS for t in tokens)


def find_decision_makers(snaps: list[PageSnapshot], limit: int = 3) -> list[DecisionMaker]:
    found: dict[str, DecisionMaker] = {}

    def add(name: str, title: str, snap: PageSnapshot, parts: list[str]) -> None:
        name, title = norm_ws(name), norm_ws(title)
        if not valid_name(name):
            return
        cls, rank = _role_class(title)
        prev = found.get(name.lower())
        if prev is not None and not (rank <= prev.rank and len(title) > len(prev.title)):
            return  # already have this person; only replace with a more specific title
        found[name.lower()] = DecisionMaker(
            name=name, title=title, role_class=cls, source_url=snap.url, fetched_at=snap.fetched_at,
            excerpt=" … ".join(parts)[:200], excerpt_parts=[p[:200] for p in parts], rank=rank)

    for snap in snaps:
        blocks = snap.page.blocks
        for i, block in enumerate(blocks):
            if len(block) > 120:
                continue
            m = NAME_TITLE_RE.match(block) or TITLE_NAME_RE.match(block)
            if m:
                add(m.group("name"), m.group("title"), snap, [block])
                continue
            if NAME_ONLY_RE.match(block) and i + 1 < len(blocks):
                nxt = blocks[i + 1]
                if len(nxt) <= 60 and TITLE_ONLY_RE.match(nxt):
                    add(block, nxt, snap, [block, nxt])
        # JSON-LD Person / founder nodes; both fields must appear verbatim in the raw JSON-LD
        for node in snap.page.jsonld_nodes():
            name, title = node.get("name"), node.get("jobTitle")
            if isinstance(name, str) and isinstance(title, str) and TITLE_ONLY_RE.match(title.strip()):
                raw = " ".join(snap.page.jsonld_raw)
                if name in raw and title in raw:
                    add(name, title, snap, [name, title])
    ranked = sorted(found.values(), key=lambda d: d.rank)  # stable: page order within a rank
    return ranked[:limit]
