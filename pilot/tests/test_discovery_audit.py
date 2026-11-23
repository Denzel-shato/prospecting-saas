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


# ----------------------------------------------------------------------------------------------- other adapters
from vm1.discovery import DrupalOrgAdapter, OverpassAdapter, WikidataAdapter  # noqa: E402


def b(item, label, site, **kw):
    row = {"item": {"value": f"http://www.wikidata.org/entity/{item}"}, "itemLabel": {"value": label},
           "website": {"value": site}}
    for k, v in kw.items():
        row[k] = {"value": v}
    return row


class WikidataHygieneTests(unittest.TestCase):
    def parse(self, rows, **kw):
        ad = WikidataAdapter(ApiClient(transport=object()), **kw)
        return ad, ad.parse({"results": {"bindings": rows}}, "t")

    def test_multi_valued_rows_merge_to_one_candidate_with_order_independent_result(self):
        rows = [b("Q1", "Foo", "https://www.foo.example/b", employees="9"),
                b("Q1", "Foo", "https://foo.example/a", employees="4000", listed="false"),
                b("Q1", "Foo", "https://foo.example/a", employees="9")]
        ad, got = self.parse(rows)
        _, got_rev = self.parse(list(reversed(rows)))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].attrs["employees"], 4000, "largest headcount wins: stale small values never promote")
        self.assertEqual((got[0].url, got[0].attrs), (got_rev[0].url, got_rev[0].attrs))
        self.assertEqual(ad.yield_stats["merged_duplicate_rows"], 2)
        self.assertEqual(ad.yield_stats["multi_headcount_items"], 1)

    def test_distinct_items_and_invalid_rows_are_counted_not_merged(self):
        ad, got = self.parse([b("Q1", "A", "https://a.example"), b("Q2", "B", "https://b.example"),
                              {"item": {"value": "x"}}])
        self.assertEqual([c.name for c in got], ["A", "B"])
        self.assertEqual((ad.yield_stats["rows"], ad.yield_stats["invalid_rows"]), (3, 1))

    def test_enriched_query_excludes_only_explicitly_dissolved_companies_basic_query_unchanged(self):
        ad = WikidataAdapter(None)
        self.assertIn("FILTER NOT EXISTS { ?item wdt:P576 ?dissolved . }", ad.build_query(enriched=True))
        self.assertNotIn("P576", ad.build_query(enriched=False))
        self.assertIn("ORDER BY ?item", ad.build_query(enriched=True))


class DrupalRecordTextTests(unittest.TestCase):
    def discover(self, rows, **kw):
        class Client:
            def request_json(self, method, url):
                return {"list": rows}
        ad = DrupalOrgAdapter(Client(), **kw)
        return ad, {c.domain: c for c in ad.discover()}

    def row(self, i, title, text, location="Denver, CO"):
        return {"type": "organization", "nid": str(i), "title": title, "field_link": {"url": f"https://d{i}.example"},
                "field_organization_headquarters": location, "body": {"value": f"<p>{text}</p>"}}

    def test_profile_excerpt_and_identity_hints_reach_the_record_text_fields(self):
        long = "We are a custom software development studio. " + "x" * 400
        rows = [self.row(1, "Build Co", long), self.row(2, "Growth Co", "A marketing agency for brands.")]
        ad, got = self.discover(rows)
        self.assertEqual(len(got["d1.example"].attrs["directory_tagline"]), 200)
        self.assertTrue(got["d1.example"].attrs["directory_software_focus_hint"])
        self.assertTrue(got["d2.example"].attrs["directory_marketing_focus_hint"])
        self.assertFalse(got["d2.example"].attrs["directory_software_focus_hint"])
        self.assertEqual((ad.yield_stats["software_focus_hint"], ad.yield_stats["marketing_focus_hint"]), (1, 1))
        self.assertEqual(got["d1.example"].source_url, "https://www.drupal.org/node/1")
        self.assertIn("CC BY-SA", got["d1.example"].source_license)

    def test_unknown_headquarters_in_worldwide_mode_is_kept_but_counted(self):
        ad, got = self.discover([self.row(1, "Anywhere", "A development agency.", location="")], worldwide=True)
        self.assertIn("d1.example", got)
        self.assertEqual(ad.yield_stats["location_unknown_kept"], 1)

    def test_discovery_text_never_becomes_size_or_location_evidence(self):
        _, got = self.discover([self.row(1, "Studio", "A development agency, 500 employees.")])
        ev = apply_discovery_record("d1.example", got["d1.example"], [])
        self.assertFalse([e for e in ev if e.claim_type.startswith("size")])


class OverpassHygieneTests(unittest.TestCase):
    def parse(self, els):
        ad = OverpassAdapter(ApiClient(transport=object()), True)
        return ad, ad.parse({"elements": els}, "t")

    def test_branch_duplicates_retail_tags_and_social_pages_are_counted_not_researched(self):
        els = [{"type": "node", "id": 1, "tags": {"name": "Code HQ", "website": "https://codehq.example"}},
               {"type": "way", "id": 2, "tags": {"name": "Code HQ (annex)", "website": "http://www.codehq.example/about"}},
               {"type": "node", "id": 3, "tags": {"name": "PC Fix", "website": "https://pcfix.example", "shop": "computer"}},
               {"type": "node", "id": 4, "tags": {"name": "Page", "website": "https://facebook.com/page"}},
               {"type": "node", "id": 5, "tags": {"name": "No site"}},
               {"type": "node", "id": 6, "tags": {"name": "Labs", "website": "labs.example",
                                                   "description": "Web app development studio"}}]
        ad, got = self.parse(els)
        self.assertEqual([c.domain for c in got], ["codehq.example", "labs.example"])
        self.assertEqual(got[0].source_id, "node/1", "first object keeps provenance")
        self.assertEqual(got[1].attrs["description"], "Web app development studio")
        self.assertEqual(got[0].attrs["country"], "US")
        s = ad.yield_stats
        self.assertEqual((s["elements"], s["duplicate_domain"], s["retail_tagged"], s["no_website_domain"],
                          s["no_name_or_website"], s["candidates"]), (6, 1, 1, 1, 1, 2))

    def test_query_and_acknowledgement_gate_are_unchanged(self):
        ad = OverpassAdapter(ApiClient(transport=object()), False)
        self.assertIn('nwr["office"="it"]["website"](area.us)', ad.build_query())
        with self.assertRaises(DiscoveryBlocked):
            ad.discover()


class PoolArtifactTests(unittest.TestCase):
    def test_every_run_saves_the_full_pool_with_discovery_attributes_and_it_feeds_the_benchmark(self):
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path

        from vm1 import discovery_benchmark as bench
        from vm1.cli import main

        out = Path(tempfile.mkdtemp())
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["synthetic", "--out", str(out)]), 0)
        (run,) = [p for p in out.iterdir() if p.is_dir()]
        pool = json.loads((run / "pool.json").read_text())
        selected = json.loads((run / "candidates.json").read_text())
        self.assertGreaterEqual(len(pool), len(selected))
        self.assertTrue(all({"domain", "attrs", "source", "discovery_method"} <= set(p) for p in pool))
        self.assertEqual({p["domain"] for p in pool} >= {s["domain"] for s in selected}, True)
        self.assertEqual(len(bench.load_pool(run / "pool.json")), len(pool))
