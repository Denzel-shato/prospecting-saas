"""rehabcreative-style identity: "We help organizations plan, build, improve, and support websites and digital tools."
Only first-person business-to-client wording on the company's own pages establishes client-services identity."""

import unittest

from tests.util import snap
from vm1.evidence import extract_evidence, verify_evidence
from vm1.score import score_company

H = "https://x.example/"
HELP = "We help organizations plan, build, improve, and support websites and digital tools."
BUILD = "We build websites, custom applications, APIs, integrations."
SERVICES = "<h2>Services</h2><ul><li>React and Next.js development</li><li>Web applications</li></ul>"


def ident(snaps):
    ev = extract_evidence("x.example", snaps, company_name="Rehab Creative")
    return ev, {e.claim_type for e in ev}


class Recognised(unittest.TestCase):
    def test_homepage_wording_gives_client_services_identity_and_target_type(self):
        s = snap(f"<h1>Rehab Creative</h1><p>{HELP}</p><p>{BUILD}</p>{SERVICES}", H)
        ev, kinds = ident([s])
        self.assertIn("entity_type:client_services", kinds)
        ident_ev = next(e for e in ev if e.claim_type == "entity_type:client_services")
        self.assertIn("We help organizations", ident_ev.excerpt)
        self.assertTrue(verify_evidence(ident_ev, {s.url: s.page}))
        self.assertEqual(score_company(ev, [], homepage_ok=True).company_type, "agency_studio")

    def test_about_page_wording(self):
        _, kinds = ident([snap("<p>Welcome.</p>", H), snap(f"<p>{HELP}</p>", "https://x.example/about", False)])
        self.assertIn("entity_type:client_services", kinds)


class Rejected(unittest.TestCase):
    def test_bare_we_build_list_is_not_identity(self):
        _, kinds = ident([snap(f"<p>{BUILD}</p>{SERVICES}", H)])
        self.assertNotIn("entity_type:client_services", kinds)

    def test_testimonial_quote_and_client_statements(self):
        for html in (f"<blockquote>{HELP}</blockquote>",
                     f'<div class="testimonial"><p>{HELP}</p></div>',
                     "<p>They help organizations plan, build, improve, and support websites.</p>",
                     "<p>Clientco helps organizations plan and build websites.</p>"):
            _, kinds = ident([snap(html + SERVICES, H)])
            self.assertNotIn("entity_type:client_services", kinds, html)

    def test_employee_bio_is_not_company_identity(self):
        _, kinds = ident([snap("<h2>Meet the team</h2><h3>Sam Lee</h3><p>Sam helps organizations plan and build "
                               "websites.</p>", "https://x.example/team", False)])
        self.assertNotIn("entity_type:client_services", kinds)

    def test_non_self_pages_do_not_establish_identity(self):
        for url in ("https://x.example/blog/how-we-work", "https://x.example/docs/intro",
                    "https://x.example/work/clientco"):
            _, kinds = ident([snap("<p>Welcome.</p>", H), snap(f"<p>{HELP}</p>", url, False)])
            self.assertNotIn("entity_type:client_services", kinds, url)

    def test_product_feature_and_own_product_wording_is_vetoed(self):
        for text in ("We help organizations build websites with our platform.",
                     "We help organizations plan and build; our SDK is compatible with every framework.",
                     "We help organizations like yours; we also built our own SaaS app."):
            _, kinds = ident([snap(f"<p>{text}</p>", H)])
            self.assertNotIn("entity_type:client_services", kinds, text)

    def test_vendor_signals_still_block_target_type_despite_help_wording(self):
        body = (f"<p>{HELP}</p><p>Start your free trial. Request a demo. Log in. Our platform is trusted by "
                "thousands of teams worldwide.</p>")
        ev, _ = ident([snap(body, H)])
        r = score_company(ev, [], homepage_ok=True)
        self.assertNotEqual(r.company_type, "agency_studio")  # mixed identity + vendor wording: manual review at most
        self.assertEqual(r.tier, "weak")


if __name__ == "__main__":
    unittest.main()
