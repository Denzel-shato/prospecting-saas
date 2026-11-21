"""Run the Issue #2 failure-pattern pages through a vm1 checkout and print what it concludes.

    python3 scripts/issue2_before_after.py            # current checkout
    python3 scripts/issue2_before_after.py /path/to/old/pilot   # e.g. a worktree of the pre-fix commit

The pages are RECONSTRUCTIONS from fragments quoted in Issue #2 (the real live pages were not
available). They show how each code version treats the failure PATTERN; they are not the live
companies. The last case is a CONTROL: a fictional, well-formed studio that must still qualify.
"""
import json, sys
from pathlib import Path

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from vm1.evidence import PageSnapshot, extract_evidence  # noqa: E402
from vm1.htmlparse import parse_html  # noqa: E402
from vm1.people import find_decision_makers  # noqa: E402
from vm1.score import score_company  # noqa: E402

TS = "2026-11-21T00:00:00+00:00"


def snap(body, path="/", home=True, host="https://x.example"):
    url = host + path
    return PageSnapshot(url=url, fetched_at=TS, page=parse_html(f"<html><head><title>T</title></head><body>{body}</body></html>", url), is_homepage=home)


CASES = {
 "entromy-pattern (range size + other-org partner)": ("Entromy", [
    snap("<h1>Delivery programmes</h1><p>Programme delivery: 20-50 people who own delivery.</p><p>HQ: 1 Main St, Austin, TX 78701.</p>"),
    snap("<div><h3>Michelle Noon</h3><p>Managing Partner &amp; Co-Founder at Clearhaven Partners</p></div>", "/team", False)]),
 "breadcrumbs-pattern (historical size of another co + bare 'Case studies' link)": ("Breadcrumbs", [
    snap('<nav><a href="/customers">Case studies</a></nav><p>AdEspresso grew from 3 to a team of 50 people before it was acquired.</p><p>HQ: 1 Main St, Austin, TX 78701.</p>')]),
 "probo-pattern (CEO of another organisation)": ("Probo", [
    snap("<h1>Probo</h1><p>HQ: 1 Main St, Austin, TX 78701.</p>"),
    snap("<p>Anthony Hall, CEO at On this day AI</p>", "/about", False)]),
 "engineawesome-pattern (client brand parsed as a person)": ("EngineAwesome", [
    snap('<h1>Engine Awesome</h1><p>HQ: 1 Main St, Austin, TX 78701.</p><div class="testimonial"><h3>Homeowners Hub</h3><p>Co-Founder / CEO</p></div>')]),
 "gitlab-pattern (product docs listing TypeScript, SaaS vendor wording)": ("ProductCo", [
    snap('<nav><a href="/pricing">Pricing</a><a href="/login">Log in</a><a href="/trial">Start free trial</a><a href="/demo">Request a demo</a></nav>'
         "<h1>The all-in-one DevOps platform</h1><p>Our platform supports many programming languages including TypeScript, Ruby and Go.</p>"
         "<p>Trusted by thousands of teams worldwide.</p><p>HQ: 1 Market St, San Francisco, CA 94105.</p><p>We are a team of 40 people.</p>")]),
 "okta-pattern (customer portals in a product)": ("IdCo", [
    snap('<nav><a href="/pricing">Pricing</a><a href="/login">Sign in</a><a href="/demo">Book a demo</a></nav>'
         "<h1>The identity platform</h1><p>Give customers a self-service customer portal with single sign-on and admin panels.</p>"
         "<p>HQ: 100 1st St, San Francisco, CA 94105. We have 400 employees.</p>")]),
 "CONTROL: fictional studio, must still qualify": ("Brightlane Studio", [
    snap("<h1>Brightlane is a software studio for SaaS products</h1><p>We build SaaS dashboards and client portals with React, Next.js and TypeScript.</p>"
         "<p>We are a team of 14 engineers and designers.</p><p>Office: 1 Main St, Austin, TX 78701.</p>"),
    snap("<div><h3>Maya Okafor</h3><p>Founder &amp; CEO</p></div>", "/team", False)]),
}

for label, (name, snaps) in CASES.items():
    try:
        evs = extract_evidence("x.example", snaps, company_name=name)
    except TypeError:
        evs = extract_evidence("x.example", snaps)
    try:
        dms = find_decision_makers(snaps, company_key="x.example", company_name=name)
    except TypeError:
        dms = find_decision_makers(snaps)
    r = score_company(evs, dms, homepage_ok=True)
    size = [e.value for e in evs if e.claim_type == "size:employees" and e.level != "unknown"]
    svc = sorted(e.claim_type.split(":")[1] for e in evs if e.claim_type.startswith("service:"))
    print(json.dumps({"case": label, "tier": r.tier, "score": r.total, "type": getattr(r, "company_type", "(n/a pre-fix)"),
                      "size": size or "unknown", "services": svc,
                      "client_work": any(e.claim_type == "signal:client_work" for e in evs),
                      "decision_makers": [f"{d.name} / {d.title}" for d in dms] or "unknown",
                      "exclusions": [x["rule"] for x in r.hard_exclusions]}))
