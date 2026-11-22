"""Local-fixture reproductions of three live false-negative patterns (creative-agency identity, nav/card service
labels, Drupal-only agency) together with the guards that keep bios, client work and bare technology words from
becoming service claims. Fictional pages; no live data."""

import unittest

from tests.util import snap
from vm1.evidence import extract_evidence, verify_evidence
from vm1.score import score_company

H = "https://x.example/"


def run(snaps, name="Acme Creative"):
    ev = extract_evidence("x.example", snaps, company_name=name)
    return ev, score_company(ev, [], homepage_ok=True)


def kinds(ev):
    return {(e.claim_type, str(e.value)) for e in ev}


AGENCY = "<p>Acme is a digital agency in Austin, TX 78701.</p>"


class CreativeAgencyIdentity(unittest.TestCase):
    def test_creative_agency_with_offered_services_gets_identity(self):
        ev, r = run([snap("<p>Acme Creative is a creative agency in Austin, TX 78701.</p><h2>What we do</h2>"
                          "<ul><li>React and Next.js development</li><li>Web applications</li></ul>", H)])
        self.assertIn(("entity_type:studio_or_agency", "studio_or_agency"), kinds(ev))
        self.assertEqual(r.company_type, "agency_studio")
        self.assertEqual(r.tier, "possible")  # thresholds unchanged: no size => never strong

    def test_clients_and_directories_do_not_supply_identity(self):
        ev, _ = run([snap("<p>Trusted by every creative agency we know. Find a design studio in our directory.</p>", H)])
        self.assertNotIn(("entity_type:studio_or_agency", "studio_or_agency"), kinds(ev))


class EmployeeBiosAndClientWork(unittest.TestCase):
    BIO = "<h2>Meet the team</h2><h3>Sam Lee</h3><p>Sam is a front-end developer who loves React and Next.js.</p>"

    def test_bio_on_team_page_is_only_a_mention_even_with_agency_identity(self):
        ev, _ = run([snap(AGENCY, H), snap(self.BIO, "https://x.example/team", False)])
        k = kinds(ev)
        for tag in ("react", "nextjs", "frontend"):
            self.assertNotIn((f"service:{tag}", tag), k)
            self.assertIn((f"mention:{tag}", tag), k)

    def test_bio_in_about_team_section_is_not_a_service(self):
        ev, _ = run([snap(AGENCY, H), snap(self.BIO, "https://x.example/about", False)])
        self.assertFalse({c for c, _ in kinds(ev)} & {"service:react", "service:nextjs", "service:frontend"})

    def test_client_case_study_and_testimonial_are_not_services(self):
        ev, _ = run([snap(AGENCY, H),
                     snap("<h1>Case study</h1><p>We rebuilt their React dashboard.</p>",
                          "https://x.example/work/clientco", False),
                     snap("<blockquote>Their React development was great.</blockquote>", H)])
        self.assertNotIn("service:react", {c for c, _ in kinds(ev)})


class ServiceLabels(unittest.TestCase):
    def test_card_labels_on_homepage_count_for_an_agency(self):
        ev, r = run([snap(AGENCY + "<div><h3>React Development</h3><h3>Software Development</h3>"
                          "<h3>Frontend Expertise</h3></div>", H)])
        k = kinds(ev)
        for tag in ("react", "custom_software", "frontend"):
            self.assertIn((f"service:{tag}", tag), k)

    def test_nav_labels_count_only_with_agency_identity_and_no_vendor_signals(self):
        nav = ("<nav><ul><li><a href='/r'>React Development</a></li><li><a href='/s'>Software Development</a></li>"
               "<li><a href='/f'>Frontend</a></li></ul></nav>")
        ev, _ = run([snap(AGENCY + nav, H)])
        k = kinds(ev)
        self.assertIn(("service:react", "react"), k)
        self.assertIn(("service:custom_software", "custom_software"), k)
        self.assertIn(("mention:frontend", "frontend"), k)  # a bare technology word is never a label
        self.assertNotIn(("service:frontend", "frontend"), k)
        ev2, _ = run([snap("<p>Welcome.</p>" + nav, H)])  # no identity => nav alone proves nothing
        self.assertFalse({c for c, _ in kinds(ev2)} & {"service:react", "service:custom_software"})
        vendor = "<p>Start your free trial. Request a demo. Log in. Trusted by thousands of teams worldwide.</p>"
        ev3, _ = run([snap(AGENCY + vendor + nav, H)])
        self.assertNotIn("service:react", {c for c, _ in kinds(ev3)})

    def test_nav_service_evidence_is_still_verifiable_against_the_page(self):
        s = snap(AGENCY + "<nav><a href='/r'>React Development</a></nav>", H)
        ev, _ = run([s])
        react = next(e for e in ev if e.claim_type == "service:react")
        self.assertTrue(verify_evidence(react, {s.url: s.page}))

    def test_product_feature_and_third_party_wording_still_vetoed(self):
        ev, _ = run([snap(AGENCY + "<p>Our SDK supports React development for your team.</p>", H),
                     snap("<h3>React Development</h3>", "https://x.example/docs/react", False)])
        self.assertNotIn("service:react", {c for c, _ in kinds(ev)})


class DrupalOnly(unittest.TestCase):
    def test_drupal_alone_is_not_react_nextjs_or_frontend_capability(self):
        ev, r = run([snap("<p>Zoo is a digital agency in London. We specialise in Drupal.</p><h2>Our services</h2>"
                          "<ul><li>Drupal development</li><li>Drupal migrations</li><li>Support and hosting</li></ul>", H)],
                    name="Zoo")
        self.assertFalse({c for c, _ in kinds(ev)} & {"service:react", "service:nextjs", "service:typescript",
                                                      "service:frontend", "service:web_app", "service:custom_software"})
        self.assertNotEqual(r.tier, "strong")

    def test_bespoke_web_application_work_is_recognised(self):
        ev, _ = run([snap("<p>Zoo is a digital agency in London.</p><h2>Our services</h2>"
                          "<ul><li>Bespoke software development</li></ul>", H)], name="Zoo")
        self.assertIn(("service:custom_software", "custom_software"), kinds(ev))


if __name__ == "__main__":
    unittest.main()
