"""First-party pages served as static documents (about.html, work.html, ...) must be selectable.

Cause of the miss: category matching uses WHOLE path segments, and the segment "about.html" is not the
segment "about". The fix strips a trailing page-document extension (and index documents) before matching, nothing
else: link text is still only a fallback for opaque paths, the editorial/legal/excluded lists, same-site rule,
asset filter and fetch budget are unchanged.

Fixtures are synthetic local HTML (no captured third-party markup, no network). The real homepage markup of the
site that exposed the miss was not used, so these tests prove the RULES, not live behaviour on that site.
"""

import unittest

from vm1.htmlparse import parse_html
from vm1.pageselect import canonical_key, classify_link, plan_selection, rank_candidates
from vm1.pipeline import pick_secondary

BASE = "https://studio.example/"

STATIC_HOME = """<!doctype html><html><body>
<nav><a href="index.html">Home</a><a href="about.html">About</a><a href="/work.html">Work</a>
<a href="services.html">Services</a><a href="team.html">Team</a><a href="contact.html">Contact</a>
<a href="blog.html">Journal</a><a href="privacy.html">Privacy</a></nav>
<a href="https://other.example/about.html">Partner</a>
<a href="https://blog.studio.example/about.html">Blog</a>
</body></html>"""

U = "https://studio.example"
EXPECTED_4 = [f"{U}/services.html", f"{U}/about.html", f"{U}/team.html", f"{U}/work.html"]


class StaticPageExtensions(unittest.TestCase):
    def test_identity_work_and_service_pages_with_extensions_are_classified(self):
        for path, cat in [("/about.html", "about"), ("/work.html", "work"), ("/services.html", "service_hub"),
                          ("/team.html", "team"), ("/case-study.html", "work"), ("/case-studies.htm", "work"),
                          ("/portfolio.php", "work"), ("/about-us.aspx", "about"), ("/en/about.html", "about"),
                          ("/ABOUT.HTML", "about"), ("/contact.html", "contact")]:
            got = classify_link(path, "")
            self.assertIsNotNone(got, path)
            self.assertEqual(got[0], cat, path)

    def test_service_detail_pages_and_index_documents(self):
        self.assertEqual(classify_link("/services/web-development.html", "")[0], "service_icp")
        self.assertEqual(classify_link("/services/branding.html", "")[0], "service_other")
        self.assertEqual(classify_link("/services/index.html", "")[0], "service_hub")
        self.assertIsNone(classify_link("/index.html", ""))
        self.assertIsNone(classify_link("/home.html", ""))

    def test_local_homepage_fixture_selects_identity_pages_within_the_same_budget(self):
        home = parse_html(STATIC_HOME, BASE)
        ranked = rank_candidates(home.links, BASE)
        self.assertEqual({s.url for s in ranked}, {*EXPECTED_4, f"{U}/contact.html"})
        self.assertEqual([s.url for s in plan_selection(ranked, 4)], EXPECTED_4)
        self.assertEqual(pick_secondary(home, BASE, 4), EXPECTED_4)
        for limit in (1, 2, 3, 4):
            self.assertEqual(len(plan_selection(rank_candidates(home.links, BASE), limit)), limit)

    def test_fetch_url_keeps_the_linked_form(self):
        for s in plan_selection(rank_candidates(parse_html(STATIC_HOME, BASE).links, BASE), 4):
            self.assertTrue(s.url.endswith(".html") and "?" not in s.url and s.reason and s.slot, s.url)

    def test_extension_variants_are_one_page_so_they_cannot_double_spend_the_budget(self):
        self.assertEqual(canonical_key(f"{U}/about.html"), canonical_key("https://www.studio.example/About/"))
        self.assertEqual(canonical_key(f"{U}/index.html"), canonical_key(BASE))
        ranked = rank_candidates([(f"{U}/about", "About"), (f"{U}/about.html", "About us"),
                                  (f"{U}/work", "Work"), (f"{U}/work.htm", "Work")], BASE)
        self.assertEqual([s.url for s in ranked], [f"{U}/about", f"{U}/work"])


class SafetyUnchanged(unittest.TestCase):
    def test_editorial_legal_and_excluded_paths_stay_excluded_with_an_extension(self):
        for path in ("/blog.html", "/privacy.html", "/terms.php", "/careers.html", "/pricing.htm", "/login.aspx",
                     "/news/about.html", "/insights/team.html", "/docs/work.html"):
            self.assertIsNone(classify_link(path, "About us"), path)

    def test_link_text_never_overrides_an_extension_path(self):
        self.assertEqual(classify_link("/contact.html", "Meet our team")[0], "contact")
        self.assertEqual(classify_link("/about.html", "Contact us")[0], "about")

    def test_substrings_and_headline_slugs_still_do_not_match(self):
        for path in ("/aboutface.html", "/teamwork-tips.html", "/workshop.html", "/peoplesoft.php",
                     "/company-culture-and-values-at-scale-today.html"):
            self.assertIsNone(classify_link(path, ""), path)
        self.assertIsNone(classify_link("/our-team-is-hiring-engineers-now.html", "Team"))
        self.assertIsNone(classify_link("/about.html/team", ""), "only the LAST segment's extension is stripped")

    def test_assets_cross_site_and_excluded_subdomains_still_skipped(self):
        self.assertIsNone(classify_link("/work.pdf", "Work"))
        links = [("https://other.example/about.html", "About"), ("https://blog.studio.example/work.html", "Work")]
        self.assertEqual(rank_candidates(links, BASE), [])


if __name__ == "__main__":
    unittest.main()
