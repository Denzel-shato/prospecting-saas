import unittest

import tests.util as u
from vm1.discovery import DrupalOrgAdapter, WikidataAdapter
from vm1.evidence import extract_evidence
from vm1.policy import load_policy
from vm1.score import score_company


class WorldwideStudioTests(unittest.TestCase):
    def score(self, location):
        policy = load_policy(u.ROOT / "icp" / "frontend-studio-worldwide.json")
        page = u.snap("<p>We're a software development studio. We offer React and Next.js development.</p>"
                      "<p>We are a team of 15 engineers.</p>" + f"<p>{location}</p>")
        return score_company(extract_evidence("example.org", [page]), [], homepage_ok=True, policy=policy)

    def test_non_us_base_is_eligible_and_unknown_location_cannot_be_strong(self):
        self.assertEqual(self.score("We are based in Toronto, Canada.").tier, "strong")
        self.assertNotEqual(self.score("Get in touch.").tier, "strong")

    def test_indian_headquarters_excludes_even_with_a_us_address(self):
        result = self.score("Our headquarters are in Bengaluru, India. US office: Denver, CO 80202.")
        self.assertEqual(result.tier, "excluded")
        self.assertEqual(self.score("We are based in London. Our clients are based in India.").tier, "strong")

    def test_worldwide_wikidata_query_excludes_india_without_inventing_us_location(self):
        adapter = WikidataAdapter(None, worldwide=True)
        for enriched in (True, False):
            self.assertIn("FILTER NOT EXISTS { ?item wdt:P17 wd:Q668", adapter.build_query(enriched))
            self.assertNotIn("wd:Q30", adapter.build_query(enriched))
        item = {"item": {"value": "https://www.wikidata.org/entity/Q1"},
                "itemLabel": {"value": "Example Studio"}, "website": {"value": "https://example.org"}}
        candidate, = adapter.parse({"results": {"bindings": [item]}}, "2026-11-22")
        self.assertNotIn("country", candidate.attrs)

    def test_drupal_worldwide_accepts_canada_and_unknown_but_filters_indian_hq(self):
        locations = ["Toronto, Canada", "", "Pune, India"]
        rows = [{"type": "organization", "nid": str(i), "title": f"Studio {i}",
                 "field_link": {"url": f"https://studio{i}.example"},
                 "field_organization_headquarters": loc, "body": {"value": "<p>A digital agency.</p>"}}
                for i, loc in enumerate(locations)]

        class Client:
            def request_json(self, method, url):
                return {"list": rows}

        self.assertEqual([c.source_id for c in DrupalOrgAdapter(Client(), worldwide=True).discover()], ["0", "1"])


class WikidataWindowTests(unittest.TestCase):
    """The LIMIT window must not be spent on listed or oversized companies (ORDER BY ?item = lowest Q-ids)."""

    def test_enriched_query_filters_listed_and_oversized_before_the_limit(self):
        for worldwide in (False, True):
            q = WikidataAdapter(None, worldwide=worldwide, hard_max=250).build_query(enriched=True)
            self.assertIn("FILTER(!?listed)", q)
            self.assertIn("FILTER(!BOUND(?employees) || ?employees <= 250)", q)
            self.assertLess(q.index("FILTER(!?listed)"), q.index("LIMIT"))
            # unknown headcount is never an exclusion
            self.assertIn("!BOUND(?employees)", q)

    def test_basic_fallback_query_is_unchanged(self):
        q = WikidataAdapter(None, worldwide=True).build_query(enriched=False)
        self.assertNotIn("?listed", q)
        self.assertNotIn("?employees <=", q)

    def test_hard_max_is_configurable(self):
        self.assertIn("?employees <= 100", WikidataAdapter(None, hard_max=100).build_query())
