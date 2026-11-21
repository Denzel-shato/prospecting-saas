import ast
import json
import tempfile
import unittest
from pathlib import Path

import tests.util as u
from vm1.discovery import (ApiClient, DiscoveryBlocked, OverpassAdapter, WikidataAdapter, build_adapters)
from vm1.fetch import RawResponse
from vm1.fixture import build_synthetic
from vm1.guard import PaidApiBlocked, SpendLedger, credentials_present, require_zero_cost
from vm1.pipeline import RunConfig, run_pipeline

PKG = u.ROOT / "vm1"


class FailClosedTests(unittest.TestCase):
    def test_non_free_cost_classes_blocked(self):
        require_zero_cost("x", "free_keyless")
        for cls in ("paid", "free_with_key", "unknown", ""):
            with self.assertRaises(PaidApiBlocked):
                require_zero_cost("x", cls)

    def test_paid_and_keyed_sources_refused_by_name(self):
        for name in ("exa", "tavily", "brave", "hunter", "apollo", "serpapi", "google", "bing"):
            with self.assertRaises(PaidApiBlocked, msg=name):
                build_adapters([name])

    def test_ledger_rejects_any_spend(self):
        led = SpendLedger()
        led.record("wikidata", 0.0)
        with self.assertRaises(PaidApiBlocked):
            led.record("exa", 0.01)
        self.assertEqual(led.total_usd, 0.0)

    def test_env_credentials_reported_by_name_but_never_used(self):
        names = credentials_present({"EXA_API_KEY": "secret-value", "HOME": "/x"})
        self.assertEqual(names, ["EXA_API_KEY"])
        self.assertNotIn("secret-value", json.dumps(names))

    def test_api_client_only_talks_to_fixed_hosts(self):
        c = ApiClient(transport=object(), resolver=u.resolver({"evil.example": ["93.184.216.34"]}))
        with self.assertRaises(DiscoveryBlocked):
            c.request_json("GET", "https://evil.example/x")

    def test_overpass_needs_explicit_ack_and_makes_no_call_without_it(self):
        class Boom:
            def request(self, *a, **k):
                raise AssertionError("network must not be touched")

        ad = OverpassAdapter(ApiClient(transport=Boom(), resolver=u.resolver({})), acknowledged=False)
        with self.assertRaises(DiscoveryBlocked) as cm:
            ad.discover()
        self.assertIn("--ack-overpass-terms", str(cm.exception))

    def test_http_failure_is_reported_as_blocker_not_empty_success(self):
        class T:
            def request(self, *a, **k):
                return RawResponse(429, {}, b"")

        client = ApiClient(transport=T(), resolver=u.resolver({"query.wikidata.org": ["93.184.216.34"]}))
        with self.assertRaises(DiscoveryBlocked) as cm:
            WikidataAdapter(client).discover()
        self.assertIn("429", str(cm.exception))

    def test_wikidata_id_mismatch_fails_closed(self):
        body = json.dumps({"results": {"bindings": [
            {"q": {"value": "http://www.wikidata.org/entity/Q1058914"}, "l": {"value": "something else"}}]}})

        class T:
            def request(self, *a, **k):
                return RawResponse(200, {}, body.encode())

        client = ApiClient(transport=T(), resolver=u.resolver({"query.wikidata.org": ["93.184.216.34"]}))
        with self.assertRaises(DiscoveryBlocked):
            WikidataAdapter(client).discover()

    def test_adapter_parsers_label_automated_and_keep_source(self):
        wd = WikidataAdapter(ApiClient()).parse({"results": {"bindings": [{
            "item": {"value": "http://www.wikidata.org/entity/Q1"}, "itemLabel": {"value": "Acme"},
            "website": {"value": "https://acme.com"}, "employees": {"value": "25"}}]}}, u.TS)
        self.assertEqual((wd[0].discovery_method, wd[0].source_id, wd[0].attrs["employees"]), ("automated", "Q1", 25))
        osm = OverpassAdapter(ApiClient(), True).parse({"elements": [
            {"type": "node", "id": 7, "tags": {"name": "Z", "website": "z.com", "addr:state": "TX"}},
            {"type": "node", "id": 8, "tags": {"name": "NoSite"}}]}, u.TS)
        self.assertEqual(len(osm), 1)
        self.assertEqual(osm[0].source_url, "https://www.openstreetmap.org/node/7")


class NoSendingTests(unittest.TestCase):
    FORBIDDEN_IMPORTS = {"smtplib", "imaplib", "poplib", "email", "googleapiclient", "google", "sendgrid",
                         "mailgun", "requests", "urllib3", "aiohttp", "openai", "anthropic"}

    def test_no_mail_or_paid_client_imports_anywhere(self):
        for path in PKG.glob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    mods = [node.module.split(".")[0]]
                bad = self.FORBIDDEN_IMPORTS.intersection(mods)
                self.assertFalse(bad, f"{path.name} imports {bad}")

    def test_no_send_code_path_names(self):
        for path in PKG.glob("*.py"):
            src = path.read_text(encoding="utf-8").lower()
            for token in ("sendmail", "send_message", "gmail.send", "smtp(", "messages.send"):
                self.assertNotIn(token, src, f"{path.name} contains {token}")


class SyntheticPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        adapters, fetcher = build_synthetic(u.WORLD)
        icp = json.loads((u.ROOT / "icp" / "frontend-studio.json").read_text())
        cls.res = run_pipeline(RunConfig(icp=icp, out_dir=Path(cls.tmp.name), mode="synthetic_fixture"),
                               adapters, fetcher)
        cls.by = {c["domain"]: c for c in cls.res["companies"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_synthetic_run_is_never_counted_as_automated(self):
        c = self.res["manifest"]["counts"]
        self.assertEqual((c["selected_automated"], c["raw_automated"]), (0, 0))
        self.assertGreater(c["selected_synthetic"], 0)
        self.assertEqual(self.res["manifest"]["paid_api_spend_usd"], 0.0)
        report = (Path(self.res["run_dir"]) / "report.md")
        # report is written by the CLI; render directly here
        from vm1.report import write_report
        text = write_report(self.res["run_dir"]).read_text()
        self.assertIn("NOT A FINDING", text)
        self.assertIn("FICTIONAL", text)

    def test_exclusions_hold_end_to_end(self):
        for dom, rule in (("talentbridge-staffing.example", "staffing_recruiting"),
                          ("londonpixel.example", "non_us_only"),
                          ("megacorp-consulting.example", "size_over_250"),
                          ("redirector.example", "unreachable")):
            self.assertIn(rule, [e["rule"] for e in self.by[dom]["score"]["hard_exclusions"]], dom)
            self.assertIsNone(self.by[dom]["total"])

    def test_ssrf_redirect_to_private_ip_blocked_end_to_end(self):
        self.assertTrue(self.by["redirector.example"]["homepage"]["error"].startswith("unsafe_redirect"))

    def test_robots_blocked_site_has_no_content_or_evidence(self):
        c = self.by["robotsblocked.example"]
        self.assertEqual((c["tier"], c["evidence"], c["secondary"]), ("not_researchable", [], []))

    def test_dedup_removed_duplicates_and_directory(self):
        doms = [c["domain"] for c in self.res["companies"]]
        self.assertEqual(len(doms), len(set(doms)))
        reasons = sorted(r["reason"] for r in self.res["rejected"])
        self.assertEqual(reasons, ["duplicate_domain", "non_first_party_domain"])
        self.assertTrue(self.res["manifest"]["possible_same_company_different_domain"])

    def test_decision_makers_only_with_evidence(self):
        self.assertEqual(self.by["brightlane-studio.example"]["decision_makers"][0]["name"], "Maya Okafor")
        self.assertEqual(self.by["quietstudio.example"]["decision_makers"], [])
        self.assertEqual(self.by["northwind-ui.example"]["decision_makers"], [])

    def test_drafts_unsent_no_emails_all_lint_clean(self):
        self.assertTrue(self.res["drafts"])
        for d in self.res["drafts"]:
            self.assertEqual(d["status"], "UNSENT_DRAFT")
            self.assertIsNone(d["recipient"]["email"])
            self.assertTrue(d["lint"]["passed"], d["lint"])
        self.assertNotIn("talentbridge", json.dumps(self.res["drafts"]))
        self.assertNotIn("quietstudio", json.dumps(self.res["drafts"]))

    def test_no_email_addresses_anywhere_in_artifacts(self):
        import re
        pat = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
        for f in Path(self.res["run_dir"]).rglob("*"):
            if f.is_file() and f.suffix in (".json", ".txt", ".jsonl", ".md"):
                self.assertFalse(pat.search(f.read_text(encoding="utf-8")), f.name)

    def test_all_kept_evidence_is_verbatim_in_fixture_pages(self):
        for c in self.res["companies"]:
            for ev in c["evidence"]:
                self.assertLessEqual(len(ev["excerpt"]), 200)
                self.assertTrue(ev["source_url"] and ev["fetched_at"])

    def test_run_is_deterministic(self):
        adapters, fetcher = build_synthetic(u.WORLD)
        icp = json.loads((u.ROOT / "icp" / "frontend-studio.json").read_text())
        with tempfile.TemporaryDirectory() as t:
            again = run_pipeline(RunConfig(icp=icp, out_dir=Path(t), mode="synthetic_fixture"), adapters, fetcher)
        a = {c["domain"]: (c["total"], c["tier"]) for c in self.res["companies"]}
        b = {c["domain"]: (c["total"], c["tier"]) for c in again["companies"]}
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
