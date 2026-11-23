"""Discovery audit regressions: PickAnAgency query strategy/metadata, Wikidata/Drupal/OSM adapter hygiene.

Offline only. Fictional records. These tests prove adapter behaviour, not real-world lead quality.
"""
import unittest
from urllib.parse import parse_qs, urlsplit

from vm1.discovery import ApiClient, DiscoveryBlocked
from vm1.evidence import apply_discovery_record
from vm1.pickanagency import PickAnAgencyAdapter


def rec(name, site, country="United States", **extra):
    slug = name.lower().replace(" ", "-")
    return dict(name=name, website=site, slug=slug, profile_url=f"https://www.pickanagency.com/agencies/{slug}",
                location={"country": country, "city": "Town"}, services=["Software Development"], **extra)


class QueueClient:
    """Returns one canned response per call, in order."""

    def __init__(self, *responses):
        self.responses, self.urls = list(responses), []

    def request_json(self, method, url, form=None, accept=""):
        self.urls.append(url)
        return self.responses[len(self.urls) - 1]


def params(url):
    return {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}


class PickAnAgencyStrategyTests(unittest.TestCase):
    def run_adapter(self, client, **kw):
        ad = PickAnAgencyAdapter(client, sleeper=lambda _: None, **kw)
        return ad, ad.discover()

    def test_us_mode_sends_documented_country_filter_but_worldwide_does_not(self):
        c = QueueClient({"results": []}, {"results": []}, {"results": []})
        self.run_adapter(c)
        self.assertTrue(all(params(u)["country"] == "United States" for u in c.urls))
        c = QueueClient({"results": []}, {"results": []}, {"results": []})
        self.run_adapter(c, worldwide=True)
        self.assertTrue(all("country" not in params(u) for u in c.urls))

    def test_client_side_geography_screen_still_runs_in_us_mode(self):
        c = QueueClient({"results": [rec("Berlin Dev", "https://b.example", country="Germany")]},
                        {"results": []}, {"results": []})
        ad, got = self.run_adapter(c)
        self.assertEqual(got, [])
        self.assertEqual(ad.yield_stats["geography_rejected"], 1)

    def test_default_profile_is_the_unchanged_legacy_query_set(self):
        self.assertEqual(PickAnAgencyAdapter.QUERY_PROFILES["legacy"], PickAnAgencyAdapter.SEARCH_QUERIES)
        c = QueueClient({"results": []}, {"results": []}, {"results": []})
        ad, _ = self.run_adapter(c, worldwide=True)
        self.assertEqual(ad.query_profile, "legacy")
        self.assertEqual([params(u).get("q") for u in c.urls], [None, "custom software", "software development"])

    def test_complementary_profile_uses_documented_industry_filter_and_is_bounded(self):
        c = QueueClient({"results": []}, {"results": []}, {"results": []})
        ad, _ = self.run_adapter(c, worldwide=True, query_profile="complementary")
        self.assertEqual(len(c.urls), 3)
        last = params(c.urls[2])
        self.assertEqual((last["service"], last["industry"], last["limit"]),
                         ("Software Development", "SaaS", "25"))
        self.assertIn("complementary", ad.run_note)
        with self.assertRaises(ValueError):
            PickAnAgencyAdapter(c, query_profile="made-up")

    def test_per_query_yield_and_cross_query_attribution(self):
        shared = rec("Shared Studio", "https://shared.example", team_size="11-50")
        only_q2 = rec("Second Studio", "https://second.example")
        c = QueueClient({"results": [shared]}, {"results": [shared, only_q2]}, {"results": [only_q2]})
        ad, got = self.run_adapter(c, worldwide=True)
        pq = ad.yield_stats["per_query"]
        self.assertEqual([(q["records"], q["new_candidates"], q["duplicate_domain"]) for q in pq],
                         [(1, 1, 0), (2, 1, 1), (1, 0, 1)])
        by = {x.domain: x for x in got}
        self.assertEqual(len(by["shared.example"].attrs["directory_discovery_queries"]), 2)
        self.assertEqual(len(by["second.example"].attrs["directory_discovery_queries"]), 2)
        # first-seen provenance field is unchanged
        self.assertEqual(by["shared.example"].attrs["directory_discovery_query"], {"service": "Software Development"})
        self.assertEqual(ad.yield_stats["duplicate_domain"], 2)

    def test_team_size_screen_only_removes_unambiguously_oversized_and_never_becomes_headcount(self):
        rows = [rec("Micro", "https://micro.example", team_size="1-10"),
                rec("Small", "https://small.example", team_size="11-50"),
                rec("Mid", "https://mid.example", team_size="51-200"),
                rec("Edge", "https://edge.example", team_size="201-500"),
                rec("Big", "https://big.example", team_size="500+"),
                rec("Unknown", "https://unknown.example", team_size=None),
                rec("Junk", "https://junk.example", team_size="lots")]
        ad, got = self.run_adapter(QueueClient({"results": rows}, {"results": []}, {"results": []}), worldwide=True)
        domains = {c.domain: c for c in got}
        self.assertNotIn("big.example", domains)
        self.assertEqual(set(domains), {"micro.example", "small.example", "mid.example", "edge.example",
                                        "unknown.example", "junk.example"})
        self.assertEqual(ad.yield_stats["size_rejected"], 1)
        self.assertEqual(ad.yield_stats["team_size_known"], 4)
        self.assertEqual(domains["small.example"].attrs["directory_team_size"], "11-50")
        self.assertEqual(domains["junk.example"].attrs["directory_team_size"], "")
        for cand in got:
            self.assertNotIn("employees", cand.attrs)
            self.assertFalse([e for e in apply_discovery_record(cand.domain, cand, []) if e.claim_type.startswith("size")])

    def test_india_aliases_are_rejected_in_worldwide_mode_and_unknown_country_is_counted(self):
        rows = [rec("Alias", "https://alias.example", country="IN"),
                rec("Long", "https://long.example", country="Republic of India"),
                rec("Nowhere", "https://nowhere.example", country=""),
                rec("Fine", "https://fine.example", country="Canada")]
        ad, got = self.run_adapter(QueueClient({"results": rows}, {"results": []}, {"results": []}), worldwide=True)
        self.assertEqual({c.domain for c in got}, {"nowhere.example", "fine.example"})
        self.assertEqual(ad.yield_stats["geography_rejected"], 2)
        self.assertEqual(ad.yield_stats["country_unknown_kept"], 1)

    def test_extra_metadata_is_typed_and_bounded(self):
        row = rec("Meta", "https://meta.example", industries=["SaaS", 3, "", "Healthcare"], rating=4.5,
                  is_verified=True)
        _, (cand,) = self.run_adapter(QueueClient({"results": [row]}, {"results": []}, {"results": []}), worldwide=True)
        self.assertEqual(cand.attrs["directory_industries"], ["SaaS", "Healthcare"])
        self.assertEqual((cand.attrs["directory_rating"], cand.attrs["directory_verified"], cand.attrs["directory_city"]),
                         (4.5, True, "Town"))
        bad = rec("Bad", "https://bad.example", rating=True, is_verified="yes")
        _, (cand,) = self.run_adapter(QueueClient({"results": [bad]}, {"results": []}, {"results": []}), worldwide=True)
        self.assertNotIn("directory_rating", cand.attrs)
        self.assertNotIn("directory_verified", cand.attrs)

    def test_request_budget_never_exceeds_three_and_host_is_allowlisted(self):
        c = QueueClient({"results": []}, {"results": []}, {"results": []})
        self.run_adapter(c, query_profile="complementary")
        self.assertEqual(len(c.urls), 3)
        self.assertTrue(all(urlsplit(u).hostname in ApiClient.ALLOWED_HOSTS for u in c.urls))


if __name__ == "__main__":
    unittest.main()
