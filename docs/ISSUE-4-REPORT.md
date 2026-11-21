# Issue #4: ICP-aware secondary-page selection

Branch `vm1-pilot-issue4`, base `vm1-pilot-issue3` @ `793454e`. Not merged to `main`. No spending, no sending, no new fetch paths.

## Verification status
- **Offline tests:** 165 pass (148 existing + 17 new in `pilot/tests/test_issue4_page_selection.py`).
- **No live run was possible here** (no network). The real Telos Labs homepage markup was not available: only the URL **paths** named in Issue #4 are facts (`/contact-us/`, `/services/web-mobile-products`, `/services/mvp-foundry`, `/services/product-technology-partnership/`). The article URL, link texts and every other site below are `[ASSUMED]` reconstructions. **Nothing here shows improved live relevance**; the fresh Mac run is the evidence.

## Root cause
`rank_secondary()` matched keywords as substrings of `path + link text`. "team"/"people"/"contact" inside a headline slug or sentence-length link text gave priority 0-4, so `/contact-us/` and an article consumed 2 of the 4 slots while `/services/...` pages (no keyword hit besides generic "services" only at priority 2, behind the others) were not fetched.

## Change (`pilot/vm1/pageselect.py`, wired in `pipeline.py`)
- Categories from **whole URL path segments** (locale prefix stripped), never substrings. Link text is used only when the path says nothing, and only for a short controlled set of whole phrases ("Services", "Our team", "About us", ...). Path always wins: a contact path cannot become "team" via text.
- Never selected: editorial (blog/news/insights/articles/...), careers, legal, pricing, docs/help, login, article-like slugs (>=5 hyphen tokens or dated), excluded subdomains (blog/docs/help/...), deep (>4 segment) paths, assets.
- ICP relevance: services hub, then service detail pages with ICP tokens (web, mobile, app, software, custom, frontend, react, nextjs, typescript, saas, product, dashboard, platform, mvp, portal, ...) ahead of generic service pages (e.g. `/services/seo`).
- **Same 4-page budget** (`max_secondary` unchanged). Slot plan: service, **about**, service, service-or-**team**, then team, other services, work, contact. Identity (about) always keeps a slot; the 4th goes to a third ICP service page if one exists, otherwise team. Contact is last resort.
- Diagnostics in `companies.json`: `secondary_candidates` (top 15, each with category, priority, reason, ICP terms, selected, slot); each fetched secondary now has `category`, `reason`, `slot`, `final_url`, `text_blocks`, `text_chars`, `links`. A fetched page with `text_blocks` near 0 indicates JS-rendered or unparseable content (use this for Velvet Disruption).

## Before / after page selection (limit 4; `scripts/issue4_before_after.py`)
| Site | Before (`793454e`) | After |
|---|---|---|
| Telos-like | `/contact-us/`, article, `/team`, `/about` | `/services/web-mobile-products`, `/about`, `/services/product-technology-partnership/`, `/services/mvp-foundry` |
| Ordinary agency nav | `/team`, `/about`, `/services`, `/work` | `/services`, `/about`, `/team`, `/work` |
| Article-heavy home | 3 headline/editorial pages + `/about-us` | `/services/custom-software-development`, `/about-us`, `/contact` |
| Hub + many services | `/team`, `/about`, `/services`, 1 service | `/services`, `/about`, 2 services |
| No about page, locale paths | `/en/team`, service, `/en/work`, `/en/contact` | service, `/en/team`, `/en/work`, `/en/contact` |

Trade-off to be aware of: when many ICP service pages exist, the team page can be dropped (see "hub + many services"). Leadership is then only found if it appears on the about page or homepage.

## Item 8: Epic Design Labs `service:web_app` (investigation; attribution NOT changed)
The actual Epic excerpt is not available here, so I cannot say what it says. What the extractor does (probed offline):
- "We build custom dashboards and web applications for our clients." -> `service:web_app` (correct).
- "We built our own SaaS...", "We're building our own web app...", "Our side project is a SaaS..." -> `mention:web_app` only (own-product wording is already excluded).
- **"We build a SaaS dashboard that helps merchants track returns." -> `service:web_app`.** This is syntactically the same as a client offering, so a sentence describing the company's *own product* in plain "we build ..." form can still be attributed as a client service. `web_app` also matches the bare words `saas` and `dashboards`, which makes it the easiest tag to attribute loosely.
**Action for the live run:** open Epic's `service:web_app` evidence excerpt and source URL in `companies.json` and judge whether it is a client offering or the company's own product. If it is the latter, the fix is a narrow rule (e.g. singular-article product noun + relative clause "a ... that helps ..." => mention), to be written against the real excerpt, not guessed. Epic's `possible` tier does not depend on `web_app` alone (identity + other services also count) but verify that too.

## Unchanged
SaaS-vendor exclusions, agency qualification gate, scoring, evidence extraction, polite fetching, robots, SSRF/DNS pinning, TLS, spend guard, no-send.

## Remaining risks
- Category sets and ICP tokens are hand-written starting points; sites with opaque or non-English URL schemes fall back to exact link texts or are skipped.
- Service pages not linked from the homepage (only from a hub) are not discovered (still homepage-links only).
- Article-like rule drops legitimate pages with long slugs (>=5 hyphen tokens) outside known section segments.
