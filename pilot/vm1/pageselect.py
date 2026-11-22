"""ICP-aware choice of which same-site pages to fetch after the homepage (Issue #4).

The crawl budget is tiny (default 4 secondary pages), so WHICH pages are fetched decides what
evidence can exist at all. The previous ranking matched keywords as substrings of URL paths and link
text, so "/contact-us/" and an article whose link text said "team"/"people" outranked real
development-service pages.

Rules here:
* Categories come from WHOLE URL path segments (never substrings of slugs) and, only when the path says
  nothing, from a short CONTROLLED set of whole link-text phrases. Path wins over text; a contact or
  editorial path can never be promoted by its link text.
* Editorial/legal/careers/docs/pricing/login paths and article-like slugs are never selected.
* ICP relevance orders service pages; a services hub is preferred, then ICP-relevant service detail pages.
  WHAT counts as relevant (tokens), extra path synonyms, the slot order and the software "<x>-development-agency"
  slug heuristic come from the ICP policy (vm1.policy.PageSelectionConfig); with no policy the frontend-studio
  baseline applies. The safety rules below are shared and NOT configurable: a policy can add synonyms but can never
  promote an editorial/legal/docs/pricing/login path, and the fetch budget, same-site rule, de-duplication and
  robots handling live elsewhere (pipeline/fetch) and ignore the policy.
* A slot plan keeps company-identity research alive inside the SAME budget: service, about, service,
  service-or-team, then work, contact. With no about page the slot goes to the next-best page.
Deterministic, no network, no new fetch paths; fetching still goes through PoliteFetcher.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote, urlsplit

from functools import lru_cache

from .canon import registrable_domain
from .policy import PageSelectionConfig, baseline_policy

_ASSET_RE = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|mp4|mov|docx?|xlsx?|pptx?)$", re.I)

EDITORIAL_SEGS = {
    "blog", "blogs", "news", "press", "articles", "article", "insights", "resources", "resource", "podcast",
    "podcasts", "events", "webinars", "newsletter", "stories", "updates", "journal", "media", "learn", "library",
    "whitepapers", "ebooks", "guides", "changelog", "release-notes", "thoughts", "perspectives", "magazine",
}
EXCLUDED_SEGS = {
    "careers", "career", "jobs", "join-us", "privacy", "privacy-policy", "terms", "terms-of-service", "terms-of-use",
    "legal", "cookies", "cookie-policy", "pricing", "login", "log-in", "signin", "sign-in", "signup", "sign-up",
    "register", "docs", "documentation", "help", "support", "status", "cart", "checkout", "search", "tag", "tags",
    "category", "categories", "author", "authors", "feed", "wp-content", "wp-json", "wp-admin", "account",
}
EXCLUDED_SUBDOMAINS = {"blog", "docs", "help", "support", "status", "careers", "jobs", "app", "login", "shop", "store"}
SERVICE_HUB_SEGS = {
    "services", "service", "what-we-do", "capabilities", "expertise", "solutions", "offerings", "what-we-build",
    "what-we-offer", "our-services", "service-offerings", "development", "engineering", "practices", "disciplines",
}
ABOUT_SEGS = {"about", "about-us", "company", "who-we-are", "our-story", "story", "studio", "agency", "our-company",
              "our-studio", "our-agency", "why-us"}
TEAM_SEGS = {"team", "our-team", "leadership", "leadership-team", "people", "our-people", "management", "founders",
             "meet-the-team", "meet-us", "executives"}
WORK_SEGS = {"work", "our-work", "case-studies", "case-study", "portfolio", "projects", "clients", "customers",
             "approach", "how-we-work", "process", "our-process", "our-approach", "showcase", "success-stories"}
CONTACT_SEGS = {"contact", "contact-us", "get-in-touch", "hire-us", "start-a-project"}

# ICP relevance tokens, development words and the slot order now come from the ICP policy (vm1.policy).

# Controlled whole-phrase link texts (normalised); used only when the PATH carries no category.
TEXT_CATEGORY = {
    "services": "service_hub", "our services": "service_hub", "what we do": "service_hub",
    "what we build": "service_hub", "capabilities": "service_hub", "our capabilities": "service_hub",
    "expertise": "service_hub", "our expertise": "service_hub", "solutions": "service_hub", "offerings": "service_hub",
    "about": "about", "about us": "about", "company": "about", "who we are": "about", "our story": "about",
    "studio": "about", "agency": "about",
    "team": "team", "our team": "team", "the team": "team", "meet the team": "team", "meet our team": "team",
    "leadership": "team", "our leadership": "team", "leadership team": "team", "our people": "team",
    "people": "team", "management": "team", "founders": "team",
    "work": "work", "our work": "work", "case studies": "work", "portfolio": "work", "projects": "work",
    "approach": "work", "our approach": "work", "process": "work", "how we work": "work",
    "contact": "contact", "contact us": "contact", "get in touch": "contact",
}

# category -> priority (lower = earlier); used for the ranked candidate list and fill order
PRIORITY = {"service_icp": 0, "service_hub": 1, "about": 2, "team": 3, "service_other": 4, "work": 5,
            "contact": 6, "detail": 7}
# The slot plan (order in which page pools are served) is policy-configurable; baseline: service, about, service,
# service, team, service_other, work, contact, detail. About/identity is guaranteed an early slot by that baseline.
POOL_OF = {"service_icp": "service", "service_hub": "service", "service_other": "service_other", "about": "about",
           "team": "team", "work": "work", "contact": "contact", "detail": "detail"}


@dataclass(frozen=True)
class _Resolved:
    tokens: frozenset
    dev_words: frozenset
    dev_people: frozenset
    agency_words: frozenset
    slug_enabled: bool
    hub: frozenset
    cat_segs: tuple
    slot_order: tuple


@lru_cache(maxsize=32)
def _resolve(cfg: PageSelectionConfig) -> _Resolved:
    extra = dict(cfg.extra_segments)
    core = frozenset(cfg.service_slug[0]) if cfg.service_slug else frozenset()
    people = (core | frozenset(cfg.service_slug[1])) if cfg.service_slug else frozenset()
    agency = frozenset(cfg.service_slug[2]) if cfg.service_slug else frozenset()
    return _Resolved(
        tokens=frozenset(cfg.relevance_tokens), dev_words=core, dev_people=people, agency_words=agency,
        slug_enabled=cfg.service_slug is not None, hub=SERVICE_HUB_SEGS | frozenset(extra.get("service_hub", ())),
        cat_segs=(("about", ABOUT_SEGS | frozenset(extra.get("about", ()))),
                  ("team", TEAM_SEGS | frozenset(extra.get("team", ()))),
                  ("work", WORK_SEGS | frozenset(extra.get("work", ()))),
                  ("contact", CONTACT_SEGS | frozenset(extra.get("contact", ())))),
        slot_order=tuple(cfg.slot_order))


def _r(ps: PageSelectionConfig | None) -> _Resolved:
    return _resolve(ps if ps is not None else baseline_policy().page_selection)


@dataclass
class Selection:
    url: str
    category: str
    priority: int
    reason: str
    icp_terms: list = field(default_factory=list)
    selected: bool = False
    slot: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


_INDEX_LEAF_RE = re.compile(r"/(?:index|default|home)\.(?:html?|php|aspx?)$")


def canonical_key(url: str) -> str:
    """Identity of a page for de-duplication ONLY (never used as the fetch URL): scheme, 'www.', case,
    trailing slashes, repeated slashes, index documents, query and fragment are ignored."""
    sp = urlsplit(url)
    host = (sp.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/{2,}", "/", unquote(sp.path or "/")).lower()
    path = _INDEX_LEAF_RE.sub("/", path).rstrip("/")
    return f"{host}{path or '/'}"


_ARTICLE_STARTERS = {"how", "why", "what", "when", "best", "top", "guide", "tips", "ways", "vs", "versus", "complete",
                     "ultimate", "things", "reasons", "benefits", "checklist", "hire", "hiring", "cost", "costs",
                     "choose", "choosing", "ultimate", "should", "is", "are", "can", "do", "does"}
_SLUG_STOP = {"the", "our", "and", "of", "for", "in", "to", "with", "a", "an", "us", "about", "team", "api", "sdk",
              "docs", "guide", "tips", "portal", "login", "software"}


def _dev_service_slug(tokens: list[str], r: _Resolved | None = None) -> str | None:
    """Generic 'what an agency page is called' recognition, no company or platform list:
    '<anything>-development-agency', 'custom-web-application-development-company', 'react-native-development'.
    Returns a reason or None. Headline slugs ('how-to-choose-...', numbers) never qualify."""
    r = r or _r(None)
    if not r.slug_enabled or not 2 <= len(tokens) <= 5:
        return None
    if tokens[0] in _ARTICLE_STARTERS or any(t.isdigit() for t in tokens):
        return None
    tset = set(tokens)
    if tset & r.dev_people and tset & r.agency_words:
        return "development/agency-service slug (development word + agency/service word)"
    if tset & r.dev_words and len(tokens) <= 4 and (tset - r.dev_words - _SLUG_STOP):
        return "development-service slug (<specialty>-development)"
    return None


def _norm_text(text: str) -> str:
    t = re.sub(r"[^a-z0-9& ]+", " ", (text or "").lower().replace("&", " and "))
    return re.sub(r"\s+", " ", t).strip()


def _segments(path: str) -> list[str]:
    segs = [unquote(s).lower() for s in path.split("/") if s]
    if segs and re.fullmatch(r"[a-z]{2}(?:-[a-z]{2})?", segs[0]) and len(segs) > 1:
        segs = segs[1:]  # locale prefix: /en/services -> services
    return segs


def _article_like(segs: list[str]) -> bool:
    if any(re.fullmatch(r"(?:19|20)\d\d", s) for s in segs):
        return True  # dated URL
    leaf_tokens = [t for t in segs[-1].split("-") if t] if segs else []
    return len(leaf_tokens) >= 5  # long slug = headline, not a section


def classify_link(href: str, text: str, home_host: str = "",
                  ps: PageSelectionConfig | None = None) -> tuple[str, str, list] | None:
    """(category, reason, icp_terms) or None when the page should not be fetched."""
    r = _r(ps)
    sp = urlsplit(href)
    host_labels = (sp.hostname or "").split(".")
    if len(host_labels) > 2 and host_labels[0] in EXCLUDED_SUBDOMAINS and host_labels[0] != (home_host or "").split(".")[0]:
        return None
    segs = _segments(sp.path)
    if not segs or len(segs) > 4:
        return None
    if _ASSET_RE.search(sp.path):
        return None
    for s in segs:
        if s in EDITORIAL_SEGS or s in EXCLUDED_SEGS:
            return None
    first = segs[0]
    toks = {t for s in segs for t in s.split("-") if t}
    icp = sorted(toks & r.tokens)

    if first in r.hub:
        if len(segs) == 1:
            return "service_hub", f"path segment '{first}' is a services hub", []
        if _article_like(segs[1:]) and len(segs[-1].split("-")) >= 7:
            return None
        child_toks = {t for s in segs[1:] for t in s.split("-") if t}
        hits = sorted(child_toks & r.tokens)
        if hits:
            return "service_icp", f"service page under '/{first}/' with ICP terms {hits}", hits
        return "service_other", f"service page under '/{first}/' without ICP terms", []
    for cat, names in r.cat_segs:
        if first in names:
            if len(segs) == 1:
                return cat, f"path segment '{first}'", []
            return "detail", f"sub-page of '/{first}/' ({cat}); lower value", []
    leaf_tokens = [t for t in segs[-1].split("-") if t]
    why = _dev_service_slug(leaf_tokens, r) if len(segs) <= 2 else None
    if why:
        return "service_icp", f"{why}: '{segs[-1]}'", sorted(set(leaf_tokens) & (r.tokens | r.dev_people | r.agency_words))
    if _article_like(segs):
        return None  # headline-style slug with no recognised section: never matched by link text
    leaf = segs[-1]
    leaf_toks = set(leaf.split("-"))
    if len(segs) <= 2 and len(leaf.split("-")) <= 5 and (leaf_toks & r.dev_words) and (leaf_toks & (r.tokens - r.dev_words)):
        return "service_icp", f"development-service page '{leaf}' with ICP terms {icp}", icp
    cat = TEXT_CATEGORY.get(_norm_text(text))
    if cat and len(segs) <= 2:
        if cat == "service_hub":
            return "service_hub", f"controlled link text '{_norm_text(text)}'", []
        return cat, f"controlled link text '{_norm_text(text)}'", []
    return None


def rank_candidates(links: list[tuple[str, str]], home_url: str,
                    ps: PageSelectionConfig | None = None) -> list[Selection]:
    """All eligible same-site pages, best first (priority, ICP-hit count, page order)."""
    home_host = urlsplit(home_url).hostname or ""
    base = registrable_domain(home_host)
    home_key = canonical_key(home_url)
    best: dict[str, tuple[Selection, int]] = {}
    for idx, (href, text) in enumerate(links):
        sp = urlsplit(href)
        if registrable_domain(sp.hostname or "") != base:
            continue
        key = canonical_key(href)
        if key == home_key or not sp.path.strip("/"):
            continue
        got = classify_link(href, text, home_host, ps)
        if got is None:
            continue
        cat, reason, icp = got
        # fetch URL = the first-seen actual form of the link; de-duplication identity = canonical_key
        norm = f"{sp.scheme}://{sp.netloc}{sp.path}"
        sel = Selection(url=norm, category=cat, priority=PRIORITY[cat], reason=reason, icp_terms=icp)
        prev = best.get(key)
        if prev is None:
            best[key] = (sel, idx)
        elif sel.priority < prev[0].priority:
            sel.url = prev[0].url  # better classification, but keep the URL form first linked
            best[key] = (sel, prev[1])
    rows = sorted(best.values(), key=lambda r: (r[0].priority, -len(r[0].icp_terms), r[1]))
    return [s for s, _ in rows]


def plan_selection(ranked: list[Selection], limit: int, ps: PageSelectionConfig | None = None) -> list[Selection]:
    """Mark the pages to fetch (at most `limit`) using the policy's slot plan (baseline: identity-preserving)."""
    slot_order = _r(ps).slot_order
    pools: dict[str, list[Selection]] = {}
    for s in ranked:
        pools.setdefault(POOL_OF[s.category], []).append(s)
    # service pool: hub first, then ICP detail pages (already ordered by ICP-hit count)
    pools["service"] = sorted(pools.get("service", []), key=lambda s: (s.category != "service_hub",))
    chosen: list[Selection] = []
    i = 0
    while len(chosen) < limit and any(pools.values()):
        pool = slot_order[i % len(slot_order)]
        i += 1
        if i > len(slot_order) * (limit + 2):
            break
        if pools.get(pool):
            s = pools[pool].pop(0)
            s.selected, s.slot = True, len(chosen) + 1
            chosen.append(s)
    return chosen
