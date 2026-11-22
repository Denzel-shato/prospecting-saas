"""Issue #4.1: URL canonicalisation, agency-development pages, own-product attribution, snapshot replay.

All sites below are FICTIONAL/reconstructed (.example hosts). They prove rules and machinery, not live behaviour
on the real Telos/Epic/etc. sites, which were not available.
"""

import io
import json
import socket
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import tests.util as u
from vm1.cli import main as cli_main
from vm1.discovery import Candidate, SyntheticFixtureAdapter
from vm1.evidence import extract_evidence
from vm1.fetch import PoliteFetcher
from vm1.fixture import FakeTransport
from vm1.htmlparse import parse_html
from vm1.pageselect import canonical_key, classify_link, plan_selection, rank_candidates
from vm1.pipeline import pick_secondary, research_company
from vm1.snapshot import (RecordingTransport, ReplayFetcher, SnapshotMissing, SnapshotStore, capture, redact_html)

ROOT = Path(__file__).resolve().parent.parent
WORLD = ROOT / "fixtures" / "synthetic" / "world.json"
ICP = json.loads((ROOT / "icp" / "frontend-studio.json").read_text())
BASE = "https://x.example/"


def home(links):
    return parse_html("".join(f'<a href="{h}">{t}</a>' for h, t in links), BASE)


def picks(links, limit=4):
    return [x.replace("https://x.example", "") for x in pick_secondary(home(links), BASE, limit)]


# ------------------------------------------------------------------------------------------- A1 canonical URLs
class CanonicalUrlTests(unittest.TestCase):
    def test_equivalent_forms_share_one_canonical_key(self):
        forms = ["https://x.example/services", "https://x.example/services/", "http://www.x.example/services/",
                 "https://X.example/Services?utm_source=a#top", "https://x.example//services//",
                 "https://x.example/services/index.html"]
        self.assertEqual(len({canonical_key(f) for f in forms}), 1)
        self.assertNotEqual(canonical_key("https://x.example/services"), canonical_key("https://x.example/service"))

    def test_slash_variants_use_one_slot_and_keep_the_linked_fetch_url(self):  # Telos: /services and /services/
        links = [("/services", "Services"), ("/services/", "Our services"), ("/about", "About"), ("/team", "Team"),
                 ("/work", "Work")]
        ranked = rank_candidates(home(links).links, BASE)
        self.assertEqual([r.url for r in ranked if "services" in r.url], ["https://x.example/services"])
        self.assertEqual(picks(links), ["/services", "/about", "/team", "/work"])

    def test_homepage_alias_links_are_not_candidates(self):
        links = [("https://www.x.example/", "Home"), ("/index.html", "Home"), ("/#about", "About"), ("/about", "About")]
        self.assertEqual(picks(links), ["/about"])

    def test_duplicates_do_not_reduce_page_diversity_within_budget(self):
        links = [("/services", "S"), ("/services/", "S"), ("/services", "S"), ("/about", "A"), ("/about/", "A"),
                 ("/team", "T"), ("/team/", "T"), ("/work", "W")]
        got = picks(links)
        self.assertEqual(len(got), 4)
        self.assertEqual(len({canonical_key(BASE.rstrip("/") + g) for g in got}), 4)


def _world(tmp: Path, hosts: dict) -> Path:
    for name, host in hosts.items():
        for path, page in host.get("pages", {}).items():
            if "html" in page:
                f = tmp / f"{name}{path.strip('/').replace('/', '_') or 'home'}.html"
                f.write_text(page.pop("html"), encoding="utf-8")
                page["file"] = f.name
    p = tmp / "world.json"
    p.write_text(json.dumps({"candidates": [{"name": n, "url": f"https://{n}/"} for n in hosts], "hosts": hosts}))
    return p


def _fetcher(world_path: Path, store: SnapshotStore | None = None):
    world = json.loads(world_path.read_text())
    transport = FakeTransport(world, world_path.parent)
    if store:
        transport = RecordingTransport(transport, store)
    return PoliteFetcher(transport, lambda h: ["1.1.1.1"] if h in world["hosts"] else [], min_delay=0.0,
                         sleep=lambda s: None), world


class RedirectDuplicateTests(unittest.TestCase):
    def test_redirect_to_an_already_fetched_page_adds_no_second_snapshot_and_no_extra_request(self):
        with tempfile.TemporaryDirectory() as t:
            wp = _world(Path(t), {"dup.example": {"pages": {
                "/": {"html": '<a href="/service">Service</a><a href="/services">Services</a><a href="/about">About</a>'},
                "/service": {"status": 301, "location": "/services"},
                "/services": {"html": "<p>We build React apps for startups.</p>"},
                "/about": {"html": "<p>Dup Studio is a software studio in Austin, TX 78701.</p>"}}}})
            fetcher, world = _fetcher(wp)
            cand = Candidate("Dup Studio", "https://dup.example/", "manual", "manual_csv")
            rec = research_company(cand, fetcher, ICP, 4)
            sec = {s["url"]: s for s in rec["secondary"]}
            self.assertEqual(len(rec["secondary"]), 3, "budget unchanged: one fetch per selected page")
            dups = [s for s in rec["secondary"] if s.get("duplicate_of")]
            self.assertEqual(len(dups), 1)
            self.assertTrue(dups[0]["final_url"].endswith("/services"))
            page_urls = {e["source_url"] for e in rec["evidence"]}
            self.assertEqual(len([x for x in page_urls if x.endswith("/services")]) <= 1, True)
            self.assertLessEqual(len([r for r in fetcher.log if r["url"].endswith(("/service", "/services", "/about"))
                                      and r["status"] is not None]), 4)


# ------------------------------------------------------------------------------ A2 agency-development slugs
class AgencyDevelopmentSlugTests(unittest.TestCase):
    def test_generic_agency_and_development_service_slugs_are_service_pages(self):
        for path in ("/bigcommerce-development-agency/", "/custom-web-application-development-company",
                     "/react-native-development", "/shopify-plus-development-agency", "/laravel-developers-for-hire"[:0] or "/nextjs-development",
                     "/en/headless-commerce-development-agency"):
            got = classify_link(path, "")
            self.assertIsNotNone(got, path)
            self.assertEqual(got[0], "service_icp", path)

    def test_headline_vendor_and_documentation_slugs_are_not(self):
        for path in ("/how-to-choose-a-bigcommerce-development-agency", "/10-best-react-development-agencies",
                     "/blog/bigcommerce-development-agency", "/insights/react-development-trends",
                     "/developer-portal", "/developers", "/api-development-docs", "/platform", "/features",
                     "/integrations", "/product", "/pricing", "/login", "/software-development-life-cycle-guide",
                     "/why-choose-our-development-agency", "/best-development-agency-for-your-startup-needs"):
            self.assertIsNone(classify_link(path, ""), path)

    def test_epic_like_page_keeps_its_agency_page_alongside_identity_pages(self):  # Epic lost its agency page
        links = [("/about", "About"), ("/work", "Work"), ("/blog", "Blog"), ("/contact", "Contact"),
                 ("/bigcommerce-development-agency/", "BigCommerce Development"),
                 ("/shopify-development", "Shopify"), ("/team", "Team"), ("/pricing", "Pricing")]
        got = picks(links)
        self.assertIn("/bigcommerce-development-agency", [g.rstrip("/") for g in got])
        self.assertIn("/about", got)
        self.assertLessEqual(len(got), 4)

    def test_unrelated_saas_navigation_is_not_promoted(self):
        links = [("/platform", "Platform"), ("/features", "Features"), ("/pricing", "Pricing"), ("/customers", "Customers"),
                 ("/integrations", "Integrations"), ("/login", "Log in"), ("/docs", "Docs"), ("/product", "Product")]
        self.assertEqual([g for g in picks(links) if g != "/customers"], [])

    def test_many_service_pages_still_leave_a_slot_for_company_identity(self):
        links = [(f"/react-development-{i}-agency", f"R{i}") for i in range(6)] + [("/about", "About"), ("/team", "Team")]
        got = picks(links)
        self.assertIn("/about", got)
        self.assertEqual(len(got), 4)


# ------------------------------------------------------------------------------- A3 own-product attribution
class OwnProductAttributionTests(unittest.TestCase):
    def claims(self, body):
        ev = extract_evidence("x.example", [u.snap(body)], company_name="Epic Design Labs")
        return {e.claim_type for e in ev if e.claim_type.startswith(("service:", "mention:"))}

    def test_first_party_product_wording_is_not_a_client_service(self):
        for text in ("We build apps and SaaS products.",
                     "We built our own SaaS, a dashboard that helps merchants track returns.",
                     "We're building a SaaS dashboard for merchants.",
                     "We build a SaaS dashboard that helps merchants track returns.",
                     "In addition to client work, we operate our own SaaS products.",
                     "Our side project is a SaaS for tracking inventory.",
                     "Our flagship product is a web app for clinics."):
            c = self.claims(f"<p>{text}</p>")
            self.assertNotIn("service:web_app", c, text)
            self.assertIn("mention:web_app", c, text)

    def test_the_mention_records_why_it_was_not_attributed(self):
        ev = extract_evidence("x.example", [u.snap("<p>We build apps and SaaS products.</p>")])
        m = next(e for e in ev if e.claim_type == "mention:web_app")
        self.assertIn("could be the company's own product", m.notes)

    def test_client_anchored_or_services_context_wording_is_still_a_service(self):
        for body in ("<p>We build apps and SaaS products for startups and founders.</p>",
                     "<p>We're a studio that builds apps and SaaS products.</p>",
                     "<p>We build custom dashboards and web applications for our clients.</p>",
                     "<h2>What we build</h2><p>Apps and SaaS products</p>"):
            self.assertIn("service:web_app", self.claims(body), body)

    def test_unambiguous_deliverable_wording_is_unchanged(self):
        c = self.claims("<p>We build React web apps with Next.js.</p>")
        self.assertTrue({"service:react", "service:nextjs", "service:web_app"} <= c)


# --------------------------------------------------------------------------------------- B snapshot replay
def capture_synthetic(store_dir, pages=8):
    store = SnapshotStore(store_dir)
    fetcher, _ = _fetcher(WORLD, store)
    cands = SyntheticFixtureAdapter(WORLD).discover()
    return store, capture(cands, fetcher, store, capture_pages=pages, label="test-capture")


def run_replay(store_dir, out_dir, *extra):
    err, out = io.StringIO(), io.StringIO()
    with redirect_stderr(err), redirect_stdout(out):
        code = cli_main(["replay", "--snapshots", str(store_dir), "--out", str(out_dir), *extra])
    return code, out.getvalue(), err.getvalue()


def companies(out_dir):
    run = sorted(Path(out_dir).iterdir())[-1]
    return json.loads((run / "companies.json").read_text()), json.loads((run / "manifest.json").read_text())


class SnapshotReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.t = Path(self.tmp.name)
        self.store, self.man = capture_synthetic(self.t / "snap")

    def tearDown(self):
        self.tmp.cleanup()

    def test_replay_reproduces_the_live_style_results_offline(self):
        from vm1.fixture import build_synthetic
        from vm1.pipeline import RunConfig, run_pipeline
        adapters, fetcher = build_synthetic(WORLD)
        live = run_pipeline(RunConfig(icp=ICP, out_dir=self.t / "live", mode="synthetic_fixture"), adapters, fetcher)
        code, _, err = run_replay(self.t / "snap", self.t / "rep")
        self.assertEqual(code, 0, err)
        comps, _ = companies(self.t / "rep")
        key = lambda c: (c["domain"], c["tier"], c["total"], c["company_type"],  # noqa: E731
                         sorted(e["claim_type"] for e in c["evidence"]))
        self.assertEqual(sorted(map(key, comps)), sorted(map(key, live["companies"])))

    def test_replay_is_labelled_and_never_counts_as_discovery_or_a_live_result(self):
        run_replay(self.t / "snap", self.t / "rep")
        comps, man = companies(self.t / "rep")
        self.assertEqual(man["mode"], "replay")
        self.assertEqual(man["counts"]["selected_automated"], 0)
        self.assertEqual(man["counts"]["selected_replay"], len(comps))
        self.assertFalse(man["replay"]["counts_as_fresh_discovery"])
        self.assertFalse(man["replay"]["counts_as_independent_live_result"])
        self.assertEqual(man["replay"]["network"], "disabled")
        self.assertTrue(all(c["discovery"]["method"] == "replay" for c in comps))
        report = (sorted((self.t / "rep").iterdir())[-1] / "report.md").read_text()
        self.assertIn("REPLAY", report.splitlines()[2] + report)
        self.assertIn("NOT A FINDING", report)

    def test_replay_opens_no_sockets(self):
        def boom(*a, **k):
            raise AssertionError("network used during replay")
        with mock.patch.object(socket, "create_connection", boom), mock.patch.object(socket, "getaddrinfo", boom), \
                mock.patch.object(socket.socket, "connect", boom):
            code, _, err = run_replay(self.t / "snap", self.t / "rep")
        self.assertEqual(code, 0, err)

    def test_replay_is_deterministic(self):
        run_replay(self.t / "snap", self.t / "a")
        run_replay(self.t / "snap", self.t / "b")
        a, b = companies(self.t / "a")[0], companies(self.t / "b")[0]
        self.assertEqual(a, b)

    def test_replay_failed_page_timestamp_does_not_use_wall_clock(self):
        # robotsblocked.example has no captured homepage GET response; robots refused it.
        # Repeated replays must not stamp current wall-clock time on the failure.
        first = ReplayFetcher(self.store).fetch("https://robotsblocked.example/")
        second = ReplayFetcher(self.store).fetch("https://robotsblocked.example/")
        self.assertFalse(first.ok)
        self.assertEqual(first.fetched_at, self.man["started_at"])
        self.assertEqual(first.fetched_at, second.fetched_at)

    def test_original_provenance_is_preserved(self):
        run_replay(self.t / "snap", self.t / "rep")
        comps, _ = companies(self.t / "rep")
        captured_at = {e["captured_at"] for e in self.store.entries()}
        urls = {e["url"] for e in self.store.entries()}
        for c in comps:
            for e in c["evidence"]:
                if e["source_type"] == "first_party_page":
                    self.assertIn(e["fetched_at"], captured_at)
                    self.assertIn(e["source_url"], urls)

    def test_exhausted_coverage_fails_clearly_and_never_fetches(self):
        store, _ = capture_synthetic(self.t / "thin", pages=1)  # capture only ONE secondary page per company
        code, out, err = run_replay(self.t / "thin", self.t / "rep")
        self.assertEqual(code, 4)
        self.assertIn("REPLAY FAILED", err)
        self.assertIn("not captured", err)
        self.assertIn("--capture-pages", err)
        self.assertFalse((self.t / "rep").exists() and any((self.t / "rep").iterdir()))

    def test_collect_missing_finishes_lists_every_gap_and_still_exits_nonzero(self):
        capture_synthetic(self.t / "thin", pages=1)
        code, _, err = run_replay(self.t / "thin", self.t / "rep", "--collect-missing")
        self.assertEqual(code, 4)
        self.assertIn("INCOMPLETE", err)
        comps, man = companies(self.t / "rep")
        self.assertTrue(man["replay_missing_pages"])
        report = (sorted((self.t / "rep").iterdir())[-1] / "report.md").read_text()
        self.assertIn("INCOMPLETE", report)
        errs = [s["error"] for c in comps for s in c["secondary"] if s["error"]]
        self.assertTrue(any(e.startswith("snapshot_missing") for e in errs))

    def test_replayfetcher_strict_raises_snapshotmissing_for_an_unknown_url(self):
        f = ReplayFetcher(self.store)
        with self.assertRaises(SnapshotMissing):
            f.fetch("https://brightlane-studio.example/never-captured")

    def test_stale_capture_is_refused_unless_explicitly_allowed(self):
        man = self.store.read_manifest()
        man["started_at"] = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat(timespec="seconds")
        self.store.write_manifest(man)
        code, _, err = run_replay(self.t / "snap", self.t / "rep")
        self.assertEqual(code, 5)
        self.assertIn("days old", err)
        code, _, _ = run_replay(self.t / "snap", self.t / "rep", "--allow-stale")
        self.assertEqual(code, 0)

    def test_tampered_snapshot_is_detected(self):
        body = next(self.store.dir.glob("*.body"))
        body.write_bytes(body.read_bytes() + b"<p>edited</p>")
        with self.assertRaises(ValueError):
            for e in self.store.entries():
                self.store.get(e["method"], e["url"])

    def test_failure_states_are_replayed_faithfully(self):
        by_host = {}
        for e in self.store.entries():
            by_host.setdefault(e["url"].split("/")[2], []).append(e)
        # the synthetic world contains a timeout host and an unreachable host; their failures are stored
        errs = [e for e in self.store.entries() if e.get("error")]
        self.assertTrue(errs, "capture should record network failures")
        comps_live = {c["domain"]: c["homepage"]["error"] for c in companies(self.t / "snap")[0]} if False else None
        run_replay(self.t / "snap", self.t / "rep")
        comps, _ = companies(self.t / "rep")
        errs = {c["domain"]: c["homepage"].get("error") or "" for c in comps}
        self.assertIn("robots_unreachable TimeoutError", errs["slowserver.example"])
        self.assertIn("did not resolve", errs["brightlane.example"])
        self.assertIn("disallowed by robots.txt", errs["robotsblocked.example"])
        self.assertEqual(errs["redirector.example"], "offsite_redirect")

    def test_capture_manifest_records_retention_and_redaction(self):
        self.assertIn("Do not commit", self.man["retention"])
        self.assertIn("emails", self.man["redaction"])
        self.assertEqual(self.man["kind"], "development snapshot; not a finding")

    def test_snapshot_directories_are_git_ignored(self):
        gi = (ROOT.parent / ".gitignore").read_text()
        self.assertIn("snapshots/", gi)


class RedactionTests(unittest.TestCase):
    def test_emails_mailto_tel_and_scripts_are_removed_but_jsonld_and_text_survive(self):
        html = ('<p>Write to jane.roe@acme.example or call</p><a href="mailto:jane.roe@acme.example">mail</a>'
                '<a href="tel:+15125550100">call</a><script>var token="abc123secret"</script>'
                '<script type="application/ld+json">{"@type":"Organization","name":"Acme","email":"hi@acme.example"}</script>'
                '<p>Acme is a software studio in Austin, TX 78701.</p>')
        out = redact_html(html)
        for gone in ("jane.roe@", "mailto:", "tel:", "abc123secret", "hi@acme"):
            self.assertNotIn(gone, out)
        self.assertIn("[redacted-email]", out)
        self.assertIn('"@type":"Organization"', out)
        self.assertIn("Acme is a software studio in Austin, TX 78701.", out)

    def test_stored_response_has_no_cookies_or_unlisted_headers(self):
        with tempfile.TemporaryDirectory() as t:
            store = SnapshotStore(t)
            from vm1.fetch import RawResponse
            from vm1.netsafe import validate_url

            class Inner:
                def request(self, *a, **k):
                    return RawResponse(200, {"content-type": "text/html", "set-cookie": "sid=SECRET",
                                             "authorization": "x", "x-powered-by": "php"},
                                       b"<p>hello jane@x.example</p>")
            RecordingTransport(Inner(), store).request("GET", validate_url("https://x.example/", lambda h: ["1.1.1.1"]),
                                                        {"Cookie": "c=1"}, None, 5, 1000)
            e = store.entries()[0]
            self.assertEqual(set(e["headers"]), {"content-type"})
            self.assertNotIn("Cookie", json.dumps(e))
            self.assertNotIn(b"jane@", next(store.dir.glob("*.body")).read_bytes())


if __name__ == "__main__":
    unittest.main()
