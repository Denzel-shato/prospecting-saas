"""Shared context helpers: who is "the company", what kind of page is this, and is a block the
company speaking about itself?

Design rule (Issue #2): a verbatim excerpt only proves the page SAYS something. Whether it is a
claim ABOUT THE TARGET COMPANY depends on context, so every extractor asks these helpers and
stays `unknown` when the answer is unclear.
"""

from __future__ import annotations

import re
from typing import Iterable
from urllib.parse import urlsplit

from .canon import registrable_domain
from .htmlparse import BLOG, DOCS, THIRD_PARTY, PageData, norm_ws

# Generic words stripped to get a company's distinctive short name ("Brightlane Studio" -> "brightlane").
_GENERIC = {
    "studio", "studios", "labs", "lab", "agency", "software", "digital", "group", "inc", "llc", "ltd", "co",
    "company", "consulting", "consultancy", "technologies", "technology", "tech", "solutions", "design",
    "development", "interactive", "creative", "works", "team", "the", "and", "corp", "corporation", "partners",
    "systems", "web", "app", "apps", "dev", "engineering", "services", "ai", "io", "hq",
}
_ORG_SPLIT = re.compile(r"\s*[|–—:·•]\s*|\s+-\s+")

PAGE_KIND_RULES = [  # first match wins; order matters (blog before team, etc.)
    ("blog", r"/(?:blog|news|articles?|insights|posts?|press|changelog|resources|stories|updates)(?:/|$)"),
    ("docs", r"/(?:docs?|documentation|developers?|api|help|support|learn|guides?|reference)(?:/|$)"),
    ("customers", r"/(?:customers?|testimonials?|reviews?|success-stories)(?:/|$)"),
    ("team", r"/(?:team|our-team|leadership|people|who-we-are|founders?|staff|management|meet-the-team)(?:/|$)"),
    ("about", r"/(?:about(?:-us)?|company|our-story|story)(?:/|$)"),
    ("services", r"/(?:services?|what-we-do|capabilit\w+|expertise|solutions?|offerings?)(?:/|$)"),
    ("work", r"/(?:work|case-stud\w*|portfolio|projects?|clients?)(?:/|$)"),
    ("contact", r"/(?:contact(?:-us)?|get-in-touch|hire-us)(?:/|$)"),
]
NON_COMPANY_SPEECH_KINDS = {"blog", "docs", "customers"}
NON_COMPANY_SPEECH_FLAGS = {THIRD_PARTY, BLOG, DOCS}


def page_kind(url: str, is_homepage: bool = False) -> str:
    if is_homepage:
        return "home"
    path = urlsplit(url).path.lower().rstrip("/") + "/"
    for kind, pat in PAGE_KIND_RULES:
        if re.search(pat, path):
            return kind
    return "other"


def assertive(ctx: frozenset, kind: str) -> bool:
    """True when the block can be the company describing itself (not testimonial/blog/docs/customer page)."""
    return kind not in NON_COMPANY_SPEECH_KINDS and not (ctx & NON_COMPANY_SPEECH_FLAGS)


def _norm(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").lower()))


def short_name(name: str) -> str:
    toks = [t for t in _norm(name).split() if t not in _GENERIC]
    return " ".join(toks)


def derive_self_names(*, candidate_name: str = "", domain: str | None = None,
                      homepage: PageData | None = None) -> set[str]:
    """Normalised names the company is known by: candidate name, domain label, <title>/og:site_name segments."""
    raw: list[str] = [candidate_name or ""]
    if domain:
        raw.append(domain.split(".")[0].replace("-", " "))
    if homepage is not None:
        raw.append(homepage.site_name)
        raw.extend(_ORG_SPLIT.split(homepage.title)[:1])
    names: set[str] = set()
    for r in raw:
        n = _norm(r)
        if len(n) >= 3:
            names.add(n)
        sn = short_name(r)
        if len(sn) >= 4:
            names.add(sn)
    return names


def matches_self(text: str, names: Iterable[str] | None) -> bool:
    """True if ``text`` mentions one of the company's own names (word-bounded, normalised)."""
    if not names:
        return False
    t = f" {_norm(text)} "
    return any(f" {n} " in t for n in names if n)


def name_alternation(names: Iterable[str] | None) -> str:
    """Regex alternation of self names for use inside patterns; never matches when no names."""
    parts = sorted({re.escape(n).replace(r"\ ", r"[\s\-]+") for n in (names or []) if len(n) >= 3},
                   key=len, reverse=True)
    return "|".join(parts) if parts else r"(?!x)x"


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'“])", text)
    return [p.strip() for p in parts if p.strip()]


def same_site(url_a: str, url_b: str) -> bool:
    return registrable_domain(urlsplit(url_a).hostname or "") == registrable_domain(urlsplit(url_b).hostname or "")
