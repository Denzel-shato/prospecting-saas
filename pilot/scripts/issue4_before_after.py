"""Which secondary pages (limit 4) does a vm1 checkout fetch for a given homepage link set?

    python3 scripts/issue4_before_after.py [/path/to/other/pilot]   # e.g. a worktree of the base commit 793454e

[ISSUE] = URL paths stated in Issue #4 for the real Telos Labs site. All other links/texts are [ASSUMED]
reconstructions: the real homepages were not available. This shows rule behaviour, NOT live relevance.
"""
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root))
from vm1.htmlparse import parse_html  # noqa: E402
from vm1.pipeline import pick_secondary  # noqa: E402

BASE = "https://x.example/"
SITES = {
    "TELOS-like ([ISSUE] paths; texts/article/other links ASSUMED)": [
        ("/contact-us/", "Contact us. Our team is ready"), ("/blog/how-our-engineering-team-ships-with-people-first-habits", "Read how our team and people deliver"),
        ("/services/web-mobile-products", "Web & Mobile Products"), ("/services/mvp-foundry", "MVP Foundry"),
        ("/services/product-technology-partnership/", "Product & Technology Partnership"),
        ("/about", "About"), ("/team", "Team"), ("/careers", "Careers")],
    "ordinary agency nav [ASSUMED]": [("/about", "About"), ("/team", "Team"), ("/services", "Services"), ("/work", "Work"),
                                      ("/contact", "Contact"), ("/blog", "Blog"), ("/privacy", "Privacy")],
    "article-heavy home [ASSUMED]": [("/the-people-behind-great-software-teams", "People"), ("/blog/our-team-culture", "Our team"),
                                     ("/insights/people-first-product-teams", "Team"), ("/services/custom-software-development", "Custom software"),
                                     ("/about-us", "About us"), ("/contact", "Contact")],
    "hub + many services [ASSUMED]": [("/services", "Services")] + [(f"/services/web-app-{i}", f"S{i}") for i in range(5)]
                                     + [("/about", "About"), ("/team", "Team")],
    "no-about site, locale paths [ASSUMED]": [("/en/services/web-development", "Web"), ("/en/team", "Team"), ("/en/work", "Work"),
                                              ("/en/contact", "Contact")],
}
for label, links in SITES.items():
    html = "".join(f'<a href="{h}">{t}</a>' for h, t in links)
    got = pick_secondary(parse_html(html, BASE), BASE, 4)
    print(label)
    for u in got:
        print("   ", u.replace("https://x.example", ""))
