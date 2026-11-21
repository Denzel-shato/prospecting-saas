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
* ICP relevance (custom software, web/mobile product development, frontend, dashboards, MVPs, ...) orders
  service pages; a services hub is preferred, then ICP-relevant service detail pages.
* A slot plan keeps company-identity research alive inside the SAME budget: service, about, service,
  service-or-team, then work, contact. With no about page the slot goes to the next-best page.
Deterministic, no network, no new fetch paths; fetching still goes through PoliteFetcher.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from urllib.parse import unquote, urlsplit

from .canon import registrable_domain

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

# Tokens that make a service page relevant to the ICP (outsourced web/frontend/product development).
ICP_TOKENS = {"web", "mobile", "app", "apps", "software", "custom", "frontend", "react", "next", "nextjs",
              "typescript", "saas", "product", "products", "dashboard", "dashboards", "platform", "platforms", "mvp",
              "portal", "portals", "digital", "technology", "engineering", "development", "ecommerce", "fullstack"}
DEV_WORDS = {"development", "engineering"}

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
# slot plan: identity (about) is guaranteed a slot early; a 3rd service page beats team only when it exists
SLOT_ORDER = ["service", "about", "service", "service", "team", "service_other", "work", "contact", "detail"]
POOL_OF = {"service_icp": "service", "service_hub": "service", "service_other": "service_other", "about": "about",
           "team": "team", "work": "work", "contact": "contact", "detail": "detail"}


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


def classify_link(href: str, text: str, home_host: str = "") -> tuple[str, str, list] | None:
    """(category, reason, icp_terms) or None when the page should not be fetched."""
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
    icp = sorted(toks & ICP_TOKENS)

    if first in SERVICE_HUB_SEGS:
        if len(segs) == 1:
            return "service_hub", f"path segment '{first}' is a services hub", []
        if _article_like(segs[1:]) and len(segs[-1].split("-")) >= 7:
            return None
        child_toks = {t for s in segs[1:] for t in s.split("-") if t}
        hits = sorted(child_toks & ICP_TOKENS)
        if hits:
            return "service_icp", f"service page under '/{first}/' with ICP terms {hits}", hits
        return "service_other", f"service page under '/{first}/' without ICP terms", []
    for cat, names in (("about", ABOUT_SEGS), ("team", TEAM_SEGS), ("work", WORK_SEGS), ("contact", CONTACT_SEGS)):
        if first in names:
            if len(segs) == 1:
                return cat, f"path segment '{first}'", []
            return "detail", f"sub-page of '/{first}/' ({cat}); lower value", []
    if _article_like(segs):
        return None  # headline-style slug with no recognised section: never matched by link text
    leaf = segs[-1]
    leaf_toks = set(leaf.split("-"))
    if len(segs) <= 2 and len(leaf.split("-")) <= 5 and (leaf_toks & DEV_WORDS) and (leaf_toks & (ICP_TOKENS - DEV_WORDS)):
        return "service_icp", f"development-service page '{leaf}' with ICP terms {icp}", icp
    cat = TEXT_CATEGORY.get(_norm_text(text))
    if cat and len(segs) <= 2:
        if cat == "service_hub":
            return "service_hub", f"controlled link text '{_norm_text(text)}'", []
        return cat, f"controlled link text '{_norm_text(text)}'", []
    return None


def rank_candidates(links: list[tuple[str, str]], home_url: str) -> list[Selection]:
    """All eligible same-site pages, best first (priority, ICP-hit count, page order)."""
    home_host = urlsplit(home_url).hostname or ""
    base = registrable_domain(home_host)
    home_path = urlsplit(home_url).path.rstrip("/")
    best: dict[str, tuple[Selection, int]] = {}
    for idx, (href, text) in enumerate(links):
        sp = urlsplit(href)
        if registrable_domain(sp.hostname or "") != base:
            continue
        path = sp.path.rstrip("/")
        if not path or path == home_path:
            continue
        got = classify_link(href, text, home_host)
        if got is None:
            continue
        cat, reason, icp = got
        norm = f"{sp.scheme}://{sp.netloc}{sp.path}"
        sel = Selection(url=norm, category=cat, priority=PRIORITY[cat], reason=reason, icp_terms=icp)
        prev = best.get(norm)
        if prev is None or sel.priority < prev[0].priority:
            best[norm] = (sel, idx)
    rows = sorted(best.values(), key=lambda r: (r[0].priority, -len(r[0].icp_terms), r[1]))
    return [s for s, _ in rows]


def plan_selection(ranked: list[Selection], limit: int) -> list[Selection]:
    """Mark the pages to fetch (at most `limit`) using the identity-preserving slot plan."""
    pools: dict[str, list[Selection]] = {}
    for s in ranked:
        pools.setdefault(POOL_OF[s.category], []).append(s)
    # service pool: hub first, then ICP detail pages (already ordered by ICP-hit count)
    pools["service"] = sorted(pools.get("service", []), key=lambda s: (s.category != "service_hub",))
    chosen: list[Selection] = []
    i = 0
    while len(chosen) < limit and any(pools.values()):
        pool = SLOT_ORDER[i % len(SLOT_ORDER)]
        i += 1
        if i > len(SLOT_ORDER) * (limit + 2):
            break
        if pools.get(pool):
            s = pools[pool].pop(0)
            s.selected, s.slot = True, len(chosen) + 1
            chosen.append(s)
    return chosen
