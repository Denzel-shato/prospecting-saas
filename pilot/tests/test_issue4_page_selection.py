"""Issue #4: ICP-aware secondary-page selection.

[ISSUE] = URL paths stated in Issue #4 for the real Telos Labs site. Everything else (link texts, the
article URL, other pages) is [ASSUMED] scaffolding: the real homepage markup was not available, so these
tests prove the RULES, not live behaviour on the real site.
"""

import unittest

from vm1.htmlparse import parse_html
from vm1.pageselect import classify_link, plan_selection, rank_candidates
from vm1.pipeline import pick_secondary, rank_secondary

BASE = "https://x.example/"


def home(links):
    html = "".join(f'<a href="{h}">{t}</a>' for h, t in links)
    return parse_html(html, BASE)


def picks(links, limit=4):
    return [u.replace("https://x.example", "").rstrip("/") for u in pick_secondary(home(links), BASE, limit)]


TELOS = [  # [ISSUE] paths; link texts/article URL are [ASSUMED]
    ("/contact-us/", "Contact us. Our team is ready"),
    ("/blog/how-our-engineering-team-ships-with-people-first-habits", "Read how our team and people deliver"),
    ("/services/web-mobile-products", "Web & Mobile Products"),
    ("/services/mvp-foundry", "MVP Foundry"),
    ("/services/product-technology-partnership/", "Product & Technology Partnership"),
    ("/about", "About"),
    ("/team", "Team"),
    ("/careers", "Careers"),
]


class TelosObservedCandidates(unittest.TestCase):
    def test_service_pages_win_and_contact_and_article_are_not_fetched(self):
        got = picks(TELOS)
        for svc in ("/services/web-mobile-products", "/services/mvp-foundry", "/services/product-technology-partnership"):
            self.assertIn(svc, got)
        self.assertNotIn("/contact-us", got)
        self.assertFalse([g for g in got if g.startswith("/blog")])
        self.assertIn("/about", got, "company-identity page keeps a slot")
        self.assertLessEqual(len(got), 4)

    def test_contact_and_editorial_cannot_outrank_service_pages_in_ranking(self):
        ranked = rank_candidates(home(TELOS).links, BASE)
        cats = {r.url.replace("https://x.example", "").rstrip("/"): r for r in ranked}
        self.assertEqual(cats["/services/mvp-foundry"].category, "service_icp")
        self.assertEqual(cats["/contact-us"].category, "contact")
        self.assertNotIn("/careers", cats)
        self.assertFalse([k for k in cats if k.startswith("/blog")])
        self.assertLess(cats["/services/mvp-foundry"].priority, cats["/contact-us"].priority)

    def test_each_selection_records_a_reason(self):
        for s in plan_selection(rank_candidates(home(TELOS).links, BASE), 4):
            self.assertTrue(s.reason and s.category and s.slot)


class AdversarialLinkText(unittest.TestCase):
    def test_generic_words_in_long_link_text_never_classify(self):
        links = [("/the-people-behind-great-software-teams", "People"),          # headline slug, text is bare 'People'
                 ("/insights/people-first-product-teams", "Our team of people"),   # editorial path
                 ("/our-team-is-hiring-engineers-now", "Team"),                    # article-like slug
                 ("/news/team", "Team")]                                           # editorial first segment
        self.assertEqual(picks(links), [])

    def test_path_beats_text_both_ways(self):
        got = {u.replace("https://x.example", "").rstrip("/"): c for u, c in
               ((s.url, s.category) for s in rank_candidates(home([("/contact-us/", "Meet our team"),
                                                                    ("/about", "Contact us")]).links, BASE))}
        self.assertEqual(got["/contact-us"], "contact")
        self.assertEqual(got["/about"], "about")

    def test_substrings_in_path_slugs_do_not_match(self):
        for path in ("/teamwork-tips", "/workshop", "/company-culture-and-values-at-scale-today", "/aboutface",
                     "/peoplesoft", "/servicesnow"):
            self.assertIsNone(classify_link(path, ""), path)

    def test_controlled_text_is_used_only_for_opaque_paths(self):
        self.assertEqual(classify_link("/s/12", "Our Services →")[0], "service_hub")
        self.assertEqual(classify_link("/p/9", "Meet the team")[0], "team")
        self.assertIsNone(classify_link("/p/9", "Read how our team built a platform for people"))

    def test_locale_prefix_and_trailing_slash(self):
        self.assertEqual(classify_link("/en/services/web-development/", "")[0], "service_icp")
        self.assertEqual(classify_link("/en-us/about-us/", "")[0], "about")

    def test_excluded_subdomains_and_cross_site_links_are_skipped(self):
        links = [("https://blog.x.example/about", "About"), ("https://other.example/services", "Services"),
                 ("https://docs.x.example/services", "Services")]
        self.assertEqual(picks(links), [])

    def test_generic_service_without_icp_terms_ranks_below_icp_services_and_about(self):
        links = [("/services/seo", "SEO"), ("/services/custom-software", "Custom software"), ("/about", "About")]
        got = picks(links, 2)
        self.assertEqual(got, ["/services/custom-software", "/about"])


class BudgetAndIdentity(unittest.TestCase):
    def test_budget_never_exceeds_limit_and_is_unchanged_by_many_services(self):
        links = [(f"/services/web-app-{i}", f"S{i}") for i in range(12)] + [("/about", "About"), ("/team", "Team")]
        for limit in (1, 2, 3, 4):
            self.assertEqual(len(picks(links, limit)), limit)

    def test_about_keeps_a_slot_even_with_many_services(self):
        links = [(f"/services/web-app-{i}", f"S{i}") for i in range(12)] + [("/about", "About"), ("/team", "Team")]
        got = picks(links, 4)
        self.assertIn("/about", got)
        self.assertEqual(sum(g.startswith("/services") for g in got), 3)

    def test_team_page_gets_the_last_slot_when_few_service_pages_exist(self):
        links = [("/services", "Services"), ("/services/web-development", "Web"), ("/about", "About"),
                 ("/team", "Team"), ("/work", "Work"), ("/contact", "Contact")]
        self.assertEqual(picks(links, 4), ["/services", "/about", "/services/web-development", "/team"])

    def test_ordinary_agency_nav_keeps_identity_and_leadership_pages(self):
        links = [("/about", "About"), ("/team", "Team"), ("/services", "Services"), ("/work", "Work"),
                 ("/contact", "Contact"), ("/blog", "Blog"), ("/privacy", "Privacy")]
        got = picks(links, 4)
        self.assertEqual(got, ["/services", "/about", "/team", "/work"])

    def test_no_eligible_links_means_no_fetches(self):
        self.assertEqual(picks([("/blog", "Blog"), ("/privacy", "Privacy"), ("#x", "Top")]), [])

    def test_selection_is_deterministic(self):
        self.assertEqual(picks(TELOS), picks(TELOS))

    def test_issue3_compat_api(self):
        ranked = rank_secondary(home(TELOS), BASE)
        self.assertTrue(all(isinstance(p, int) and u.startswith("https://") for p, u in ranked))


if __name__ == "__main__":
    unittest.main()
