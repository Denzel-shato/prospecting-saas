import json
import tempfile
import unittest
from pathlib import Path

from tests import util
from tests.test_issue41_stabilization import _fetcher, _world
from vm1.discovery import Candidate
from vm1.evidence import extract_evidence, verify_evidence
from vm1.pipeline import research_company
from vm1.policy import PolicyError, load_policy
from vm1.score import score_company
from vm1.snapshot import ReplayFetcher, SnapshotStore, capture
from vm1.weekly import high_fit, ready_to_contact, review_row


POLICY_FILE = util.ROOT / "icp" / "frontend-studio-worldwide.json"
POLICY = load_policy(POLICY_FILE)
CLAIM = "capability:client_application_delivery"
HOME = "https://x.example/"
CASE = HOME + "work/atlas"
BODY = "<article><h1>Atlas</h1><p>Our client, Atlas, runs a fleet.</p><p>We built a dispatch dashboard.</p></article>"


def case_evidence(html, url=CASE):
    return extract_evidence("x.example", [util.snap(html, url, home=False)], company_name="Pine Studio")


class ClientProjectEvidence(unittest.TestCase):
    def test_case_records_two_verifiable_excerpts_and_cannot_supply_the_studios_location_or_type(self):
        snap = util.snap(BODY + "<p>The client is based in London. Staffing agency.</p>"
                        "<p>NASDAQ: AAA. Request a demo</p>", CASE, home=False)
        evidence = extract_evidence("x.example", [snap])
        delivery, = [e for e in evidence if e.claim_type == CLAIM]
        self.assertTrue(verify_evidence(delivery, {CASE: snap.page}))
        self.assertEqual(len(delivery.excerpt_parts), 2)
        self.assertLessEqual(len(delivery.excerpt), 200)
        self.assertEqual(delivery.source_url, CASE)
        self.assertFalse(any(e.claim_type.startswith(("location:", "negative:", "company_type:", "service:"))
                             for e in evidence))
        self.assertEqual(score_company(evidence, [], homepage_ok=True, policy=POLICY).company_type, "unclear")

    def test_separate_offering_and_delivery_can_establish_fit_but_size_and_geography_stay_unknown(self):
        snaps = [util.snap("<p>We offer React development.</p>"), util.snap(BODY, CASE, home=False)]
        evs = extract_evidence("x.example", snaps)
        got = score_company(evs, [], homepage_ok=True, policy=POLICY)
        self.assertEqual(got.company_type, "agency_studio")
        self.assertNotEqual(got.tier, "strong")
        self.assertEqual([x["status"] for x in got.criteria if x["criterion"] in {"size", "geography"}], ["unknown"] * 2)

    def test_rejects_quotes_internal_work_hypotheticals_plans_editorials_and_mixed_portfolio_entries(self):
        for fragment in (
            "<blockquote>We built a dashboard for Atlas.</blockquote>",
            "<p>We built our own dashboard.</p>", "<p>If we built a dashboard, it would be easier.</p>",
            "<p>We built a dashboard for our staff.</p>", "<p>We plan to build a dashboard.</p>",
            "<p>We built a logo for a client who launched a dashboard.</p>",
            "<aside>We built a dashboard for Atlas.</aside>",
            "<h2>Other projects</h2><p>We built a dashboard for Atlas.</p>",
        ):
            with self.subTest(fragment=fragment):
                html = "<h1>Atlas</h1><p>Our client, Atlas, makes instruments.</p>" + fragment
                self.assertFalse(any(e.claim_type == CLAIM for e in case_evidence(html)))
        for url in (HOME, HOME + "blog/atlas", HOME + "services/atlas", HOME + "work"):
            self.assertFalse(any(e.claim_type == CLAIM for e in case_evidence(BODY, url)))

    def test_catalog_entry_requires_the_same_named_client_and_rescue_requires_a_completed_release(self):
        named = "<h3>Atlas Rail</h3><p>A custom application for Atlas Rail handles reservations.</p>"
        self.assertTrue(any(e.claim_type == CLAIM for e in case_evidence(named, HOME + "projects")))
        unrelated = named.replace("for Atlas Rail", "for startups")
        self.assertFalse(any(e.claim_type == CLAIM for e in case_evidence(unrelated, HOME + "projects")))
        scope = "<p>Atlas turned to Pine Studio to recover its frontend codebase.</p>"
        for tail in ("", "<p>Northwind launched its product with Pine Studio.</p>"):
            self.assertFalse(any(e.claim_type == CLAIM for e in case_evidence(scope + tail)))
        outcome = "<p>Atlas launched its product after partnering with Pine Studio.</p>"
        self.assertTrue(any(e.claim_type == CLAIM for e in case_evidence(scope + outcome)))

    def test_client_brief_needs_a_completed_application_result(self):
        brief = "<p>Our task was to help Atlas make its operations visible.</p>"
        for result, expected in (("The result was a scheduling dashboard for dispatchers.", True),
                                 ("The result was a new brand identity.", False),
                                 ("The result could be a dashboard.", False)):
            evs = case_evidence(brief + f"<p>{result}</p>")
            self.assertEqual(any(e.claim_type == CLAIM for e in evs), expected)
        mobile = ("<h2>Services</h2><p>Mobile app development</p>"
                  "<p>Pine Studio helped the client modernize dispatch with a custom app.</p>")
        self.assertFalse(any(e.claim_type == CLAIM for e in case_evidence(mobile)))
        self.assertTrue(any(e.claim_type == CLAIM for e in case_evidence(mobile.replace("Mobile app", "Web"))))

    def test_commissioned_web_application_with_client_appositive(self):
        # Realistic CR Software / Passicity phrasing. The client's name and
        # requested software appear together, even without "our client".
        html = ("<h1>Custom Web Application &amp; Data Analytics</h1>"
                "<p>We partnered with Passicity, a racing analytics startup, "
                "to create a custom web application and a robust analytics engine.</p>")
        claims = case_evidence(html, HOME + "case-studies/passicity/")
        projects = [e for e in claims if e.claim_type == CLAIM]
        self.assertEqual(len(projects), 1)
        self.assertIn("Passicity", projects[0].excerpt)
        self.assertIn("web application", projects[0].excerpt)
        self.assertTrue(verify_evidence(projects[0], {
            HOME + "case-studies/passicity/":
            util.snap(html, HOME + "case-studies/passicity/", home=False).page}))
        for fragment in (
            "We partnered with Passicity, a startup, to create a logo for its dashboard.",
            "We partnered with Passicity to create branding, not a web application.",
            "We partnered with Passicity to create a website.",
        ):
            with self.subTest(fragment=fragment):
                self.assertFalse(any(e.claim_type == CLAIM for e in case_evidence(
                    "<p>" + fragment + "</p>", HOME + "case-studies/passicity/")))

    def test_confidential_client_requires_both_delivery_and_explicit_nda(self):
        # Realistic Build Me App wording; confidential clients remain unnamed.
        case = HOME + "case-studies/on-demand-alcohol-delivery-platform/"
        delivered = ("We designed and built a full-stack alcohol delivery platform "
                     "for Canada and the United States, native iOS and Android apps, "
                     "a web storefront, franchise management portal, and real-time order tracking.")
        nda = "Client and product names are kept confidential under NDA."
        html = f"<h1>On-Demand Alcohol Delivery Platform</h1><p>{delivered}</p><p>{nda}</p>"
        projects = [e for e in case_evidence(html, case) if e.claim_type == CLAIM]
        self.assertEqual(len(projects), 1)
        self.assertEqual(len(projects[0].excerpt_parts), 2)
        self.assertIn("portal", projects[0].excerpt_parts[0])
        self.assertIn("NDA", projects[0].excerpt_parts[1])
        self.assertTrue(verify_evidence(projects[0], {case: util.snap(html, case, home=False).page}))
        for fragment in (
            f"<p>{delivered}</p>",  # without client context, own-product ambiguity
            f"<p>We built our own dashboard.</p><p>{nda}</p>",
            f"<p>If we built a franchise portal, it would be easier.</p><p>{nda}</p>",
            f"<blockquote>We designed and built a dashboard.</blockquote><p>{nda}</p>",
        ):
            with self.subTest(fragment=fragment):
                self.assertFalse(any(e.claim_type == CLAIM for e in case_evidence(
                    fragment, case)))

    def test_publicly_traded_clients_do_not_make_the_studio_a_listed_company(self):
        for text, expected in (("Our clients include publicly traded companies.", False),
                               ("We are a publicly traded company.", True)):
            es = extract_evidence("x.example", [util.snap("<p>" + text + "</p>")])
            self.assertEqual(any(e.value == "listed_company" for e in es), expected)

    def test_policy_cannot_use_one_project_as_both_identity_and_offered_service(self):
        for change in ("strong", "reuse", "zero"):
            data = json.loads(POLICY_FILE.read_text())
            target = data["target_type"]
            if change == "strong":
                target["identity"][-1]["strength"] = "strong"
            elif change == "reuse":
                target["capabilities"].append({"id": "delivery", "claim": CLAIM, "points": 10})
            else:
                target["min_capabilities"] = 0
            with self.subTest(change=change), self.assertRaises(PolicyError):
                load_policy(data)


class ProjectRouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.home = ('<a href="/services">Services</a><a href="/about">About</a>'
                     '<a href="/team">Team</a><a href="/services/react">React</a>'
                     '<a href="/work">Work</a>')
        self.index = ('<a href="/work">Work</a><a href="https://elsewhere.example/work/top">Dashboard</a>'
                      '<a href="/blog/case">Dashboard</a><a href="/work/login">Client portal</a>'
                      '<a href="/work/logo">Identity</a><a href="/work/atlas">Dispatch dashboard</a>')
        self.cand = Candidate("Pine Studio", HOME, "manual", "manual_csv")

    def world(self, home=None, index=None, robots="User-agent: *\nAllow: /"):
        pages = {"/": {"html": self.home if home is None else home},
                 "/work": {"html": self.index if index is None else index},
                 "/work/atlas": {"html": BODY}, "/team": {"html": "<p>Our team</p>"},
                 "/about": {"html": "<p>Pine Studio</p>"}, "/services": {"html": "<p>React development</p>"},
                 "/services/react": {"html": "<p>React development</p>"}}
        return _world(self.root, {"x.example": {"ip": "1.1.1.1", "robots": robots, "pages": pages}})

    def test_index_and_detail_fit_the_original_budget_and_capture_replays_it(self):
        world = self.world()
        live = research_company(self.cand, _fetcher(world)[0], POLICY, 4)
        wanted = [HOME + p for p in ("services", "team", "work", "work/atlas")]
        self.assertEqual([s["url"] for s in live["secondary"]], wanted)
        self.assertEqual([s["slot"] for s in live["secondary"]], [1, 2, 3, 4])
        self.assertIn("linked from " + HOME + "work", live["secondary"][-1]["reason"])
        self.assertEqual({c["url"] for c in live["secondary_candidates"] if c["selected"]}, set(wanted))
        row = review_row(live, "x.example", "test", "control", {})
        self.assertEqual(row["suggested_project_url"], CASE)
        self.assertEqual(row["client_project_url"], "")
        self.assertFalse(ready_to_contact(row) or high_fit(row))
        store = SnapshotStore(self.root / "capture")
        capture([self.cand], _fetcher(world, store)[0], store, capture_pages=4, policy=POLICY)
        replay = ReplayFetcher(store)
        rec = research_company(self.cand, replay, POLICY, 4)
        self.assertEqual([s["url"] for s in rec["secondary"]], wanted)
        self.assertTrue(any(e["claim_type"] == CLAIM and e["source_url"] == CASE for e in rec["evidence"]))
        self.assertEqual(replay.missing, [])

    def test_direct_project_uses_one_slot_and_leaves_room_for_team(self):
        world = self.world(self.home + '<a href="/work/atlas">Read more</a>'
                           '<a href="/work/atlas/">Client portal</a>')
        rec = research_company(self.cand, _fetcher(world)[0], POLICY, 4)
        self.assertEqual([s["url"] for s in rec["secondary"]], [HOME + p for p in ("services", "team", "work/atlas", "services/react")])

    def test_looks_for_people_on_about_when_no_team_page_is_linked(self):
        world = self.world(self.home.replace('<a href="/team">Team</a>', ""))
        rec = research_company(self.cand, _fetcher(world)[0], POLICY, 4)
        self.assertEqual([s["category"] for s in rec["secondary"]],
                         ["service_hub", "about", "project_index", "project_detail"])

    def test_short_budget_blocked_index_and_empty_index_do_not_trigger_extra_requests(self):
        world = self.world()
        for cap in range(4):
            rec = research_company(self.cand, _fetcher(world)[0], POLICY, cap)
            self.assertLessEqual(len(rec["secondary"]), cap)
            self.assertNotIn(CASE, [r["url"] for r in rec["secondary"]])
        for options in ({"index": '<a href="https://elsewhere.example/work/top">Dashboard</a>'},
                        {"robots": "User-agent: *\nDisallow: /work"}):
            rec = research_company(self.cand, _fetcher(self.world(**options))[0], POLICY, 4)
            self.assertEqual([r["category"] for r in rec["secondary"]], ["service_hub", "team", "project_index", "service_icp"])
