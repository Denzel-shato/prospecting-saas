import unittest
from urllib.parse import parse_qs, urlsplit

from vm1.discovery import AUTOMATED, DiscoveryBlocked, ApiClient, build_adapters
from vm1.pickanagency import PickAnAgencyAdapter
from vm1.evidence import apply_discovery_record


def record(name, website, country="United States", services=None, **extra):
    return dict(name=name, website=website, slug=name.lower().replace(" ", "-"),
                profile_url="https://www.pickanagency.com/agencies/" + name.lower().replace(" ", "-"),
                location={"country": country}, services=services or ["Web Design"], **extra)


class MockClient:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def request_json(self, method, url):
        self.calls.append((method, url))
        return self.data


class PickAnAgencyTests(unittest.TestCase):
    def test_api_host_allowlisted_and_registered(self):
        self.assertIn("www.pickanagency.com", ApiClient.ALLOWED_HOSTS)
        adapter, = build_adapters(["pickanagency"], client=MockClient({"results": []}), worldwide=True)
        self.assertEqual(adapter.name, "pickanagency")
        self.assertEqual(adapter.discover(), [])

    def test_company_website_and_attribution_not_directory_page(self):
        data = {"results": [
            record("Frontend Studio", "https://frontend.example", services=["Web Design", "Software Development"],
                   tagline="Next.js product development"),
            record("Indian Agency", "https://india.example", country="India"),
            record("Duplicate Agency", "https://www.frontend.example"),
            record("No Site", None),
            record("Social Link", "https://linkedin.com/company/not-a-website"),
            {"website": "https://noname.example"}
        ]}
        client = MockClient(data)
        adapter = PickAnAgencyAdapter(client, worldwide=True, sleeper=lambda _: None,
                                     search_terms=("web development",))
        (candidate,) = adapter.discover()
        self.assertEqual(candidate.domain, "frontend.example")
        self.assertEqual(candidate.url, "https://frontend.example")
        self.assertEqual(candidate.source_url, "https://www.pickanagency.com/agencies/frontend-studio")
        self.assertEqual(candidate.discovery_method, AUTOMATED)
        self.assertTrue(candidate.attrs["directory_frontend_hint"])
        self.assertTrue(candidate.attrs["directory_service_hint"])
        self.assertEqual(apply_discovery_record(candidate.domain, candidate, []), [])
        self.assertEqual(adapter.yield_stats["candidates"], 1)
        self.assertEqual(adapter.yield_stats["geography_rejected"], 1)
        self.assertEqual(adapter.yield_stats["duplicate_domain"], 1)
        self.assertEqual(len(client.calls), 1)
        method, url = client.calls[0]
        self.assertEqual(method, "GET")
        self.assertEqual(urlsplit(url).hostname, "www.pickanagency.com")
        self.assertEqual(parse_qs(urlsplit(url).query)["limit"], ["25"])

    def test_us_policy_rejects_unknown_and_non_us_locations(self):
        data = {"results": [
            record("US Studio", "https://us-studio.example", country="US"),
            record("German Studio", "https://german-studio.example", country="Germany"),
            record("Unknown", "https://unknown.example", country="")
        ]}
        adapter = PickAnAgencyAdapter(MockClient(data), sleeper=lambda _: None, search_terms=("studio",))
        result = adapter.discover()
        self.assertEqual([c.domain for c in result], ["us-studio.example"])
        self.assertEqual(adapter.yield_stats["geography_rejected"], 2)

    def test_source_url_never_third_party(self):
        row = record("Studio", "https://studio.example")
        row["profile_url"] = "https://external.example/spoof"
        adapter = PickAnAgencyAdapter(MockClient({"results": [row]}),
                                     worldwide=True, search_terms=("web",))
        result = adapter.discover()
        self.assertTrue(result[0].source_url.startswith("https://www.pickanagency.com/api/v1/search?"))

    def test_bad_response_fails_closed(self):
        for bad in ([], {}, {"results": {}}, {"results": [{}] * 26}):
            adapter = PickAnAgencyAdapter(MockClient(bad), worldwide=True, search_terms=("web",))
            with self.assertRaises(DiscoveryBlocked):
                adapter.discover()

    def test_bounded_requests_and_delay(self):
        client = MockClient({"results": []})
        sleeps = []
        adapter = PickAnAgencyAdapter(client, worldwide=True, sleeper=sleeps.append)
        adapter.discover()
        self.assertEqual(len(client.calls), 3)
        self.assertEqual(sleeps, [1.1, 1.1])
        self.assertTrue(all(urlsplit(url).hostname == "www.pickanagency.com" for _, url in client.calls))
        params = [parse_qs(urlsplit(url).query) for _, url in client.calls]
        self.assertEqual(params, [
            {"service": ["Software Development"], "limit": ["25"]},
            {"q": ["custom software"], "limit": ["25"]},
            {"q": ["software development"], "limit": ["25"]},
        ])
        self.assertTrue(all("Web Design" not in repr(p) for p in params))
        with self.assertRaises(ValueError):
            PickAnAgencyAdapter(client, search_terms=("a", "b", "c", "d"))

    def test_custom_search_terms_do_not_inherit_web_design_filter(self):
        client = MockClient({"results": [record("Build Studio", "https://build.example")]})
        adapter = PickAnAgencyAdapter(client, worldwide=True, search_terms=("custom software",))
        (candidate,) = adapter.discover()
        self.assertEqual(parse_qs(urlsplit(client.calls[0][1]).query),
                         {"q": ["custom software"], "limit": ["25"]})
        self.assertEqual(candidate.attrs["directory_discovery_query"], {"q": "custom software"})
        self.assertEqual(candidate.discovery_method, AUTOMATED)

    def test_default_category_query_retains_listing_provenance(self):
        client = MockClient({"results": [record("Dev Agency", "https://devagency.example",
                                               services=["Software Development"])]})
        adapter = PickAnAgencyAdapter(client, worldwide=True, sleeper=lambda _: None)
        (candidate,) = adapter.discover()
        self.assertEqual(candidate.attrs["directory_discovery_query"],
                         {"service": "Software Development"})
        self.assertEqual(adapter.yield_stats["duplicate_domain"], 2)
        self.assertEqual(adapter.yield_stats["candidates"], 1)

    def test_software_development_label_does_not_fake_frontend_hint(self):
        data = {"results": [
            record("General Software Agency", "https://general.example",
                   services=["Software Development"], tagline="Custom software projects"),
            record("Real Frontend Agency", "https://frontend.example",
                   services=["Software Development", "React development"]),
        ]}
        adapter = PickAnAgencyAdapter(MockClient(data), worldwide=True,
                                     search_terms=("custom software",))
        result = {c.domain: c for c in adapter.discover()}
        self.assertTrue(result["general.example"].attrs["directory_service_hint"])
        self.assertFalse(result["general.example"].attrs["directory_frontend_hint"])
        self.assertTrue(result["frontend.example"].attrs["directory_frontend_hint"])
        self.assertEqual(adapter.yield_stats["frontend_hint"], 1)

    def test_does_not_guess_domain_from_directory_profile(self):
        row = record("Missing Site", None)
        adapter = PickAnAgencyAdapter(MockClient({"results": [row]}),
                                     worldwide=True, search_terms=("web",))
        self.assertEqual(adapter.discover(), [])
        self.assertEqual(adapter.yield_stats["no_website"], 1)


if __name__ == "__main__":
    unittest.main()
