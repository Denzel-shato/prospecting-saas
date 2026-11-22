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
