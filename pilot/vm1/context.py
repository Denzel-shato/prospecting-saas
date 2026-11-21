"""Context helpers shared by evidence and people extraction.

A keyword match proves only that a page CONTAINS words. These helpers decide whether the words are
plausibly the company talking about ITSELF (first-party self-description) rather than a testimonial,
client case study, blog post, documentation page, partner/logo grid or navigation label.
Everything is rule-based and deterministic; when context is unclear callers must treat the claim as
unknown rather than as positive evidence.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

# ---- page kind (from URL path only) -------------------------------------------------------------
_KIND_RULES: list[tuple[str, re.Pattern]] = [
    ("editorial", re.compile(r"(?:^|/)(?:blog|news|press|articles?|insights?|resources?|podcasts?|events?|"
                             r"webinars?|updates?|stories|newsletter)(?:/|$|-)")),
    ("docs", re.compile(r"(?:^|/)(?:docs?|documentation|help|support|api|developers?|changelog|release-notes|"
                        r"guides?|tutorials?|learn|kb|reference|integrations?|marketplace)(?:/|$|-)")),
    ("legal", re.compile(r"(?:^|/)(?:privacy|terms|cookies?|legal|security|gdpr)(?:/|$|-)")),
    ("careers", re.compile(r"(?:^|/)(?:careers?|jobs?)(?:/|$|-)")),
    ("pricing", re.compile(r"(?:^|/)(?:pricing|plans)(?:/|$|-)")),
    ("team", re.compile(r"(?:^|/)(?:team|our-team|leadership|people|our-people|management|founders?|"
                        r"meet-the-team|meet-us|executives?)(?:/|$|-)")),
    ("work", re.compile(r"(?:^|/)(?:work|our-work|case-stud(?:y|ies)|portfolio|projects?|clients?|customers?|"
                        r"showcase|success-stories)(?:/|$|-)")),
    ("services", re.compile(r"(?:^|/)(?:services?|what-we-do|capabilities|expertise|solutions|offerings|"
                            r"development)(?:/|$|-)")),
    ("about", re.compile(r"(?:^|/)(?:about|about-us|company|who-we-are|our-story|story|studio|agency)(?:/|$|-)")),
    ("contact", re.compile(r"(?:^|/)(?:contact|contact-us|get-in-touch)(?:/|$|-)")),
]

# Page kinds whose text is NOT the company describing the services it sells.
NON_OFFERING_KINDS = frozenset({"editorial", "docs", "legal", "careers", "pricing", "work"})
# Page kinds whose text must never supply a person, an identity claim or a size.
NON_SELF_KINDS = frozenset({"editorial", "docs", "legal", "careers", "work"})
# Block-level context labels (see htmlparse) that mark someone else's content.
THIRD_PARTY_CTX = frozenset({"quote", "client", "editorial"})
UNRELIABLE_CTX = THIRD_PARTY_CTX | {"nav", "footer", "aside"}

THIRD_PARTY_SECTION_RE = re.compile(
    r"\b(?:testimonials?|what (?:our )?(?:clients?|customers?|partners?) (?:say|are saying)|"
    r"(?:our )?clients?|customers?|partners?|trusted by|case stud(?:y|ies)|reviews?|"
    r"blog|latest (?:posts|articles|news|stories)|news|press|speakers?|podcasts?|advis(?:o|e)rs?|"
    r"investors?|backed by|featured|as seen|in the news|resources|events?|webinars?|guests?|authors?|"
    r"written by|contributors?|alumni|portfolio companies)\b", re.I)
TEAM_SECTION_RE = re.compile(
    r"\b(?:team|leadership|our people|people|founders?|meet|management|who we are|about us|executives?|"
    r"principals?|our story)\b", re.I)


def page_kind(url: str, is_homepage: bool = False) -> str:
    path = (urlsplit(url).path or "/").lower().rstrip("/") or "/"
    if is_homepage or path == "/":
        return "home"
    for kind, pat in _KIND_RULES:
        if pat.search(path):
            return kind
    return "other"


def sentence_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    """[lo, hi) of the sentence/clause-block containing text[start:end]."""
    lo = 0
    for m in re.finditer(r"[.!?]\s+|[|•·]\s*", text[:start]):
        lo = m.end()
    m = re.search(r"[.!?](?:\s|$)|\s[|•·]\s", text[end:])
    hi = end + m.start() + 1 if m else len(text)
    return lo, min(hi, len(text))


def block_is_third_party(page, i: int) -> bool:
    """True when block i sits inside a quote/client/editorial structure or under such a heading."""
    if page.ctx_at(i) & THIRD_PARTY_CTX:
        return True
    return bool(THIRD_PARTY_SECTION_RE.search(page.section_at(i)))


def looks_like_quote_neighbour(page, i: int) -> bool:
    """A name/title block right after a quotation (quote-marked text, or a blockquote/testimonial
    element) is almost always a testimonial attribution, even when the attribution line itself
    sits outside the quote element."""
    blocks = page.blocks
    for j in (i - 1, i - 2):
        if 0 <= j < len(blocks):
            if page.ctx_at(j) & {"quote"}:
                return True
            prev = blocks[j].strip()
            if len(prev) >= 40 and (prev[0] in "“\"‘'«" or prev[-1] in "”\"’'»"):
                return True
    return False
