"""Issue #3 before/after probe. Runs reconstructed pages through a vm1 checkout and prints what it concludes.

    python3 scripts/issue3_before_after.py                      # current checkout
    python3 scripts/issue3_before_after.py /path/to/old/pilot   # e.g. a worktree of commit 4e67181

HONESTY NOTES
* The real fetched pages for teloslabs.co / epicdesignlabs.com / interline.io / velvetdisruption.com are NOT
  available here. Only the excerpts quoted in Issue #3 are used as facts (marked [ISSUE]). Everything else on
  these pages is [ASSUMED] scaffolding needed to run the classifier and is NOT a claim about the real sites.
* Velvet Disruption has no excerpt in the issue, so it cannot be reconstructed; see docs/ISSUE-3-REPORT.md.
* Negative controls are fictional wording written for this probe.
* Results show how a code version treats these PATTERNS. They are not live relevance and say nothing about precision.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from vm1.evidence import PageSnapshot, extract_evidence  # noqa: E402
from vm1.htmlparse import parse_html  # noqa: E402
from vm1.people import find_decision_makers  # noqa: E402
from vm1.score import score_company  # noqa: E402

TS = "2026-11-21T00:00:00+00:00"
ADDR = "<p>Office: 1 Main St, Austin, TX 78701.</p>"


def snap(body, path="/", home=True, host="https://x.example"):
    url = host + path
    page = parse_html(f"<html><head><title>T</title></head><body>{body}</body></html>", url)
    return PageSnapshot(url=url, fetched_at=TS, page=page, is_homepage=home)


VENDOR_NAV = ('<nav><a href="/pricing">Pricing</a> <a href="/login">Log in</a> <a href="/trial">Start free trial</a> '
              '<a href="/demo">Request a demo</a></nav>')

CASES = {
    # ---- the diagnostic companies: only [ISSUE] excerpts are facts ---------------------------------
    "TELOS: [ISSUE] 'Trusted by teams shipping to production' + [ASSUMED] address only": ("Telos Labs", [
        snap("<h1>Telos Labs</h1><p>Trusted by teams shipping to production</p>" + ADDR)]),
    "EPIC: [ISSUE] storefront + 'not the platform' excerpts, [ASSUMED] NO identity sentence": ("Epic Design Labs", [
        snap("<h1>Epic Design Labs</h1><h2>What we build</h2>"
             "<p>Custom storefronts on BigCommerce, Shopify, or headless on Next.js. Built to convert and built so your team "
             "can still merchandise after launch.</p><p>It's not the platform. It's not the design.</p>" + ADDR)]),
    "EPIC + [ASSUMED] identity sentence 'Epic Design Labs is a design and development studio.'": ("Epic Design Labs", [
        snap("<h1>Epic Design Labs</h1><p>Epic Design Labs is a design and development studio.</p><h2>What we build</h2>"
             "<p>Custom storefronts on BigCommerce, Shopify, or headless on Next.js. Built to convert and built so your team "
             "can still merchandise after launch.</p><p>It's not the platform. It's not the design.</p>" + ADDR)]),
    "INTERLINE: [ISSUE] bio excerpt on /team, [ASSUMED] no vendor cues": ("Interline", [
        snap("<h1>Interline</h1>" + ADDR),
        snap("<h2>Our team</h2><p>Drew manages the firm's consulting engagements and product development.</p>", "/team", False)]),
    "INTERLINE + [ASSUMED] genuine product/platform signals (trial, demo, pricing, login)": ("Interline", [
        snap("<h1>Interline</h1>" + VENDOR_NAV + ADDR),
        snap("<h2>Our team</h2><p>Drew manages the firm's consulting engagements and product development.</p>", "/team", False)]),
    # ---- negative controls (fictional) --------------------------------------------------------------
    "NEG vendor: trial/demo/pricing/login + 'Create custom dashboards for your team.'": ("VendorCo", [
        snap("<h1>VendorCo</h1>" + VENDOR_NAV + "<p>Create custom dashboards for your team. Built to convert.</p>" + ADDR)]),
    "NEG vendor + consulting wording: trial/demo/login + 'the firm's consulting engagements'": ("VendorCo2", [
        snap("<h1>VendorCo2</h1>" + VENDOR_NAV + "<p>Our founder runs the firm's consulting engagements and product development.</p>" + ADDR)]),
    "NEG docs page: 'Our SDK supports Next.js and TypeScript.'": ("DocsCo", [
        snap("<h1>DocsCo</h1>" + ADDR), snap("<p>Our SDK supports Next.js and TypeScript.</p><p>Custom storefronts on Next.js are supported.</p>", "/docs/frameworks", False)]),
    "NEG testimonial: blockquote about custom storefronts on Next.js": ("QuoteCo", [
        snap('<h1>QuoteCo</h1><blockquote>They built custom storefronts on Next.js for us.</blockquote>' + ADDR)]),
    "NEG team bio: 'Sam previously built React apps at Acme.' / 'Jordan loves TypeScript.'": ("BioCo", [
        snap("<h1>BioCo</h1>" + ADDR), snap("<h2>Our team</h2><p>Sam previously built React apps at Acme.</p><p>Jordan loves TypeScript.</p>", "/team", False)]),
    "NEG vague marketing: 'We build things people love. Built to convert.'": ("VagueCo", [
        snap("<h1>VagueCo</h1><p>We build things people love. Built to convert.</p>" + ADDR)]),
    "NEG negated vendor cue: 'No free trial needed. It's not a platform.'": ("NegCo", [
        snap("<h1>NegCo</h1><p>No free trial needed. It's not a platform.</p>" + ADDR)]),
}

for label, (name, pages) in CASES.items():
    key = name.lower().replace(" ", "") + ".example"
    ev = extract_evidence(key, pages, company_name=name)
    dms = find_decision_makers(pages, company_name=name) if "company_name" in find_decision_makers.__code__.co_varnames else find_decision_makers(pages)
    sc = score_company(ev, dms, homepage_ok=True)
    by = lambda prefix: sorted({f"{e.claim_type.split(':', 1)[1]}" if ':' in e.claim_type else e.claim_type for e in ev if e.claim_type.startswith(prefix)})  # noqa: E731
    print(f"\n## {label}")
    print(f"   tier={sc.tier} total={sc.total} type={getattr(sc, 'company_type', '?')} excl={[x['rule'] for x in sc.hard_exclusions]}")
    print(f"   identity={by('entity_type:')} services={by('service:')} mentions={by('mention:')} vendor={sorted(e.value for e in ev if e.claim_type == 'company_type:saas_vendor_signal')}")
