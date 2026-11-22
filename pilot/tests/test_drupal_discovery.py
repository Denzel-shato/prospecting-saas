import unittest
from urllib.parse import parse_qs, urlsplit

from vm1.discovery import AUTOMATED, DiscoveryBlocked, DrupalOrgAdapter, build_adapters
from vm1.evidence import apply_discovery_record
from vm1.prequalify import prequalify


class DrupalDiscoveryTests(unittest.TestCase):
    def test_directory_hints_prioritize_without_qualifying(self):
        def organization(nid, url, location, text):
            return {"type": "organization", "nid": nid, "title": f"Studio {nid}",
                    "field_link": {"url": url}, "field_organization_headquarters": location,
                    "body": {"value": f"<p>{text}</p>"}}

        rows = [
            organization("1", "https://example.org", "Denver, CO", "We build React applications."),
            organization("2", "https://www.example.org", "Denver, CO", "A development agency."),
            organization("3", "https://foreign.example", "Vancouver, Canada", "A React agency."),
            organization("4", "https://vendor.example", "Austin, TX", "Download our CMS."),
            organization("5", "https://www.drupal.org", "Austin, TX", "A React agency."),
        ]

        class Client:
            def request_json(self, method, url):
                assert method == "GET"
                assert urlsplit(url).hostname == "www.drupal.org"
                assert parse_qs(urlsplit(url).query)["page"] == ["0"]
                return {"list": rows}

        adapter, = build_adapters(["drupal_org"], client=Client())
        candidate, = adapter.discover()
        self.assertEqual(candidate.domain, "example.org")
        self.assertEqual(candidate.discovery_method, AUTOMATED)
        self.assertEqual(candidate.source_url, "https://www.drupal.org/node/1")
        self.assertEqual(prequalify(candidate.attrs)[0], 4)
        self.assertEqual(apply_discovery_record(candidate.domain, candidate, []), [])
        self.assertIn("5 directory records screened", adapter.run_note)

    def test_pagination_is_bounded_and_ignores_external_next_link(self):
        class Client:
            def __init__(self):
                self.pages = []

            def request_json(self, method, url):
                self.pages.append(url)
                return {"list": [{}], "next": "https://elsewhere.example/"}

        client = Client()
        DrupalOrgAdapter(client).discover()
        self.assertEqual(len(client.pages), 4)
        self.assertTrue(all(urlsplit(url).hostname == "www.drupal.org" for url in client.pages))

    def test_invalid_response_is_reported_as_blocked(self):
        class Client:
            def request_json(self, method, url):
                return {"error": "invalid response"}

        with self.assertRaisesRegex(DiscoveryBlocked, "expected an organization list"):
            DrupalOrgAdapter(Client()).discover()


class DrupalYieldAndVendorTests(unittest.TestCase):
    @staticmethod
    def _org(nid, url, loc, text):
        return {"type": "organization", "nid": nid, "title": f"Org {nid}", "field_link": {"url": url},
                "field_organization_headquarters": loc, "body": {"value": f"<p>{text}</p>"}}

    def _run(self, rows, **kw):
        class Client:
            def request_json(self, method, url):
                return {"list": rows}

        adapter = DrupalOrgAdapter(Client(), **kw)
        return adapter, adapter.discover()

    def test_vendor_without_agency_noun_is_kept_but_gets_no_service_boost(self):
        rows = [self._org("1", "https://vendor.example", "Austin, TX", "We build our platform, a SaaS for hosting sites."),
                self._org("2", "https://agency.example", "Austin, TX", "A digital agency building React apps."),
                self._org("3", "https://mixed.example", "Austin, TX", "A consulting agency that also sells our product.")]
        adapter, cands = self._run(rows)
        by = {c.source_id: c for c in cands}
        self.assertEqual(len(cands), 3)
        self.assertTrue(by["1"].attrs["directory_vendor_hint"])
        self.assertFalse(by["1"].attrs["directory_service_hint"])
        self.assertLess(prequalify(by["1"].attrs)[0], prequalify(by["2"].attrs)[0])
        self.assertEqual(prequalify(by["2"].attrs)[0], 4)  # unchanged: service +3, frontend +1
        self.assertFalse(by["3"].attrs["directory_vendor_hint"])  # an agency noun shields mixed wording
        self.assertEqual(prequalify(by["1"].attrs)[0], -3)

    def test_drupal_platform_alone_is_not_vendor_wording(self):
        adapter, (c,) = self._run([self._org("1", "https://a.example", "Austin, TX",
                                             "We build sites for clients on the Drupal platform.")])
        self.assertFalse(c.attrs["directory_vendor_hint"])
        self.assertTrue(c.attrs["directory_service_hint"])

    def test_yield_stats_account_for_every_rejection(self):
        rows = [self._org("1", "https://ok.example", "Denver, CO", "A React agency."),
                self._org("2", "https://india.example", "Pune, India", "A React agency."),
                self._org("3", "https://nolink.example", "", "A React agency."),
                self._org("4", "https://noservice.example", "Toronto, Canada", "Sells widgets."),
                self._org("5", "https://www.ok.example", "Denver, CO", "A studio."),
                {"type": "other"}]
        rows[2]["field_link"] = {}
        adapter, cands = self._run(rows, worldwide=True)
        y = adapter.yield_stats
        self.assertEqual(len(cands), 1)
        self.assertEqual((y["records"], y["candidates"], y["geography_rejected"], y["no_website"],
                          y["no_service_wording"], y["duplicate_domain"], y["invalid_record"]), (6, 1, 1, 1, 1, 1, 1))
        self.assertEqual(y["frontend_hint"], 1)
