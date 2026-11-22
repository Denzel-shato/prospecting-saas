"""Issue #3 regressions: recover genuine client-development agencies WITHOUT weakening vendor exclusions.

Excerpts marked [ISSUE] are quoted from the Issue #3 text. Surrounding markup is reconstructed; the real fetched
pages were not available, so these tests pin the PATTERNS, not the live companies. Negative controls are fictional.
"""
import unittest

import tests.util as u
from vm1.evidence import extract_evidence
from vm1.pipeline import pick_secondary, rank_secondary
from vm1.score import score_company
from vm1.htmlparse import parse_html

ADDR = "<p>Office: 1 Main St, Austin, TX 78701.</p>"
VENDOR_NAV = ('<nav><a href="/pricing">Pricing</a> <a href="/login">Log in</a> <a href="/trial">Start free trial</a> '
              '<a href="/demo">Request a demo</a></nav>')
EPIC_SENTENCE = ("Custom storefronts on BigCommerce, Shopify, or headless on Next.js. Built to convert and built so "
                 "your team can still merchandise after launch.")  # [ISSUE]


def analyze(pages, name="Acme Studio"):
    key = name.lower().replace(" ", "") + ".example"
    ev = extract_evidence(key, pages, company_name=name)
    return ev, score_company(ev, [], homepage_ok=True)


def claims(ev, prefix):
    return {e.claim_type.split(":", 1)[1] for e in ev if e.claim_type.startswith(prefix)}


def vendor(ev):
    return {e.value for e in ev if e.claim_type == "company_type:saas_vendor_signal"}


class TelosVendorSignal(unittest.TestCase):
    def test_trusted_by_teams_shipping_is_not_a_vendor_signal(self):  # [ISSUE]
        ev, sc = analyze([u.snap("<p>Trusted by teams shipping to production</p>" + ADDR)])
        self.assertNotIn("customers_at_scale", vendor(ev))

    def test_scaled_customer_claims_remain_vendor_signals(self):
        for text in ("Trusted by 10,000+ teams worldwide", "Used by millions of developers",
                     "Loved by teams around the world", "Trusted by over 5,000 companies"):
            ev, _ = analyze([u.snap(f"<p>{text}</p>")])
            self.assertIn("customers_at_scale", vendor(ev), text)


class VendorSignalNegation(unittest.TestCase):
    def test_not_the_platform_is_not_our_platform(self):  # [ISSUE] "It's not the platform. It's not the design."
        ev, _ = analyze([u.snap("<p>It's not the platform. It's not the design.</p>")])
        self.assertNotIn("our_platform", vendor(ev))

    def test_the_platform_alone_is_not_a_signal_but_our_platform_is(self):
        ev, _ = analyze([u.snap("<p>We build on the Shopify platform for merchants.</p>")])
        self.assertNotIn("our_platform", vendor(ev))
        ev, _ = analyze([u.snap("<p>Our platform lets teams automate onboarding.</p>")])
        self.assertIn("our_platform", vendor(ev))

    def test_negated_trial_and_demo_are_not_signals_but_real_ones_are(self):
        ev, _ = analyze([u.snap("<p>No free trial needed. We never do a demo reel.</p>")])
        self.assertFalse(vendor(ev) & {"free_trial", "request_demo"})
        ev, _ = analyze([u.snap("<p>Start your free trial today.</p><p>Request a demo.</p>")])
        self.assertTrue({"free_trial", "request_demo"} <= vendor(ev))

    def test_real_saas_signals_still_exclude_a_vendor(self):
        ev, sc = analyze([u.snap("<h1>VendorCo</h1>" + VENDOR_NAV + "<p>Our platform helps teams ship.</p>" + ADDR)], "VendorCo")
        self.assertEqual((sc.tier, sc.company_type), ("excluded", "saas_vendor"))


class EpicStorefrontOffering(unittest.TestCase):
    def test_custom_storefront_sentence_is_an_offered_nextjs_service(self):  # [ISSUE]
        ev, _ = analyze([u.snap(f"<p>{EPIC_SENTENCE}</p>" + ADDR)], "Epic Design Labs")
        self.assertIn("nextjs", claims(ev, "service:"))
        self.assertNotIn("nextjs", claims(ev, "mention:"))
        e = next(x for x in ev if x.claim_type == "service:nextjs")
        self.assertIn("headless on Next.js", e.excerpt)
        self.assertTrue(e.source_url and e.fetched_at)

    def test_offering_alone_never_promotes_without_agency_identity(self):
        pages = [u.snap(f"<h2>What we build</h2><p>{EPIC_SENTENCE}</p><p>We're a team of 14.</p>" + ADDR)]
        ev, sc = analyze(pages, "Epic Design Labs")
        self.assertIn("nextjs", claims(ev, "service:"))
        self.assertEqual((sc.company_type, sc.tier), ("unclear", "weak"))
        self.assertTrue(any("manual_review" in f for f in sc.flags))

    def test_with_independent_agency_identity_it_qualifies_as_possible(self):
        pages = [u.snap("<p>Epic Design Labs is a design and development studio.</p>"
                        f"<h2>What we build</h2><p>{EPIC_SENTENCE}</p><p>Name Person, Founder</p>" + ADDR)]
        _, sc = analyze(pages, "Epic Design Labs")
        self.assertEqual((sc.company_type, sc.tier), ("agency_studio", "possible"))

    def test_second_person_product_copy_is_not_an_offering(self):
        ev, _ = analyze([u.snap("<p>Create custom storefronts on Next.js with your own theme.</p>")])
        self.assertNotIn("nextjs", claims(ev, "service:"))
        self.assertIn("nextjs", claims(ev, "mention:"))

    def test_heading_and_list_lead_in_provide_offering_context(self):
        ev, _ = analyze([u.snap("<h2>What we build</h2><p>React dashboards</p>")])
        self.assertIn("react", claims(ev, "service:"))
        ev, _ = analyze([u.snap("<p>We design and build:</p><p>Next.js web apps</p>")])
        self.assertIn("nextjs", claims(ev, "service:"))

    def test_heading_context_does_not_override_third_party_or_product_wording(self):
        ev, _ = analyze([u.snap("<h2>Customers</h2><p>React dashboards</p>")])
        self.assertNotIn("react", claims(ev, "service:"))
        ev, _ = analyze([u.snap("<h2>What we build</h2><p>Our SDK supports React and Next.js.</p>")])
        self.assertFalse(claims(ev, "service:") & {"react", "nextjs"})


class InterlineEngagements(unittest.TestCase):
    BIO = "<h2>Our team</h2><p>Drew manages the firm's consulting engagements and product development.</p>"  # [ISSUE]

    def pages(self, extra=""):
        return [u.snap("<h1>Interline</h1>" + extra + ADDR), u.snap(self.BIO, "https://x.example/team", home=False)]

    def test_firm_possessive_engagements_give_weak_identity_and_offered_service(self):
        ev, sc = analyze(self.pages(), "Interline")
        self.assertIn("consulting_engagements", claims(ev, "entity_type:"))
        self.assertIn("custom_software", claims(ev, "service:"))
        self.assertEqual(sc.company_type, "agency_studio")
        self.assertNotEqual(sc.tier, "strong")

    def test_weak_identity_never_shields_a_product_vendor(self):
        ev, sc = analyze(self.pages(VENDOR_NAV), "Interline")
        self.assertEqual((sc.tier, sc.company_type), ("excluded", "saas_vendor"))

    def test_strong_identity_with_vendor_signals_is_manual_review_not_agency(self):
        pages = [u.snap("<p>Acme is a software studio.</p>" + VENDOR_NAV + ADDR)]
        _, sc = analyze(pages, "Acme")
        self.assertEqual((sc.company_type, sc.tier), ("unclear", "weak"))

    def test_possessive_in_a_testimonial_or_bio_of_a_person_is_not_identity(self):
        ev, _ = analyze([u.snap("<blockquote>The firm's consulting engagements were great.</blockquote>")])
        self.assertNotIn("consulting_engagements", claims(ev, "entity_type:"))
        ev, _ = analyze([u.snap("<h2>Our team</h2><p>Sam previously built React apps at Acme.</p><p>Jordan loves TypeScript.</p>",
                                "https://x.example/team", home=False)])
        self.assertFalse(claims(ev, "service:"))


class NegativeControls(unittest.TestCase):
    def test_product_vendor_feature_copy_stays_excluded(self):
        _, sc = analyze([u.snap("<h1>VendorCo</h1>" + VENDOR_NAV + "<p>Create custom dashboards for your team.</p>" + ADDR)], "VendorCo")
        self.assertEqual(sc.tier, "excluded")

    def test_documentation_page_is_not_an_offering(self):
        pages = [u.snap("<h1>DocsCo</h1>" + ADDR),
                 u.snap("<p>Our SDK supports Next.js and TypeScript.</p><p>Custom storefronts on Next.js are supported.</p>",
                        "https://x.example/docs/frameworks", home=False)]
        ev, _ = analyze(pages, "DocsCo")
        self.assertFalse(claims(ev, "service:"))

    def test_customer_testimonial_is_not_an_offering(self):
        ev, _ = analyze([u.snap("<blockquote>They built custom storefronts on Next.js for us.</blockquote>")])
        self.assertFalse(claims(ev, "service:"))

    def test_vague_marketing_language_yields_nothing(self):
        ev, sc = analyze([u.snap("<p>We build things people love. Built to convert.</p>" + ADDR)])
        self.assertFalse(claims(ev, "service:") | claims(ev, "entity_type:"))
        self.assertEqual(sc.tier, "weak")

    def test_delivery_model_words_need_a_first_person_subject(self):
        ev, _ = analyze([u.snap("<p>Fixed-price hosting plans for Next.js apps.</p>")])
        self.assertNotIn("nextjs", claims(ev, "service:"))
        ev, _ = analyze([u.snap("<p>We take fixed-price projects built with Next.js.</p>")])
        self.assertIn("nextjs", claims(ev, "service:"))

    def test_tech_keywords_customers_and_software_engineering_alone_do_not_promote(self):
        body = ("<p>React, Next.js, TypeScript, SaaS, software engineering, customers and case studies.</p>"
                "<p>We are a team of 14.</p><p>Jane Roe, CEO</p>" + ADDR)
        _, sc = analyze([u.snap(body)])
        self.assertIn(sc.tier, ("weak",))
        self.assertNotIn(sc.tier, ("possible", "strong"))


class PageSelection(unittest.TestCase):
    HOME = parse_html('<a href="/capabilities">Capabilities</a><a href="/expertise">Expertise</a><a href="/about">About</a>'
                      '<a href="/team">Team</a><a href="/contact">Contact</a><a href="/work">Work</a><a href="/blog">Blog</a>'
                      '<a href="/pricing">Pricing</a>', "https://x.example/")

    def test_capability_style_pages_are_now_eligible(self):
        urls = [x for _, x in rank_secondary(self.HOME, "https://x.example/")]
        self.assertIn("https://x.example/capabilities", urls)
        self.assertIn("https://x.example/expertise", urls)
        self.assertNotIn("https://x.example/blog", urls)
        self.assertNotIn("https://x.example/pricing", urls)

    def test_per_site_fetch_limit_is_unchanged(self):
        self.assertLessEqual(len(pick_secondary(self.HOME, "https://x.example/", 4)), 4)
        self.assertEqual(len(pick_secondary(self.HOME, "https://x.example/", 2)), 2)


class FirstPartyServiceIdentity(unittest.TestCase):
    def test_software_service_heading_with_client_audience_establishes_identity(self):
        heading = "<h1>Custom web application development services for mid-market teams</h1>"
        homepage = u.snap("<p>We offer custom software development.</p>" + ADDR)
        services = u.snap(heading, "https://acme.example/services/web-app-development/", home=False)
        ev, result = analyze([homepage, services])
        self.assertIn("client_services", claims(ev, "entity_type:"))
        self.assertEqual(result.tier, "possible")

    def test_service_heading_in_client_work_or_testimonial_does_not_establish_identity(self):
        heading = "<h1>Custom web application development services for mid-market teams</h1>"
        excerpts = (
            (heading, "https://acme.example/work/client-project/"),
            (f"<blockquote>{heading}</blockquote>", "https://acme.example/services/web-app-development/"),
            ("<h1>Custom web application development services</h1>", "https://acme.example/services/"),
        )
        for html, url in excerpts:
            with self.subTest(html=html, url=url):
                ev, _ = analyze([u.snap(html, url, home=False)])
                self.assertNotIn("client_services", claims(ev, "entity_type:"))

    def test_product_pivot_overrides_a_broad_offering_heading(self):
        html = ("<h2>We build businesses.</h2>"
                "<p>We're evolving beyond pure agency into product. We're building apps and SaaS solutions "
                "to replace the clunky legacy software that's been around too long.</p>")
        ev, _ = analyze([u.snap(html, "https://acme.example/about/", home=False)])
        self.assertNotIn("web_app", claims(ev, "service:"))
        self.assertIn("web_app", claims(ev, "mention:"))

    def test_own_product_studio_stays_weak(self):
        html = "<p>We're a development studio behind our own tabletop design product.</p>"
        _, result = analyze([u.snap(html + ADDR)])
        self.assertEqual(result.tier, "weak")

    def test_mobile_react_and_backend_typescript_do_not_earn_frontend_credit(self):
        html = ("<p>We build iOS and Android apps in React Native for clients.</p>"
                "<p>We offer backend development using NestJS and TypeScript.</p>"
                "<p>We deliver custom web application development for startups.</p>")
        ev, _ = analyze([u.snap(html, "https://acme.example/services/")])
        self.assertIn("web_app", claims(ev, "service:"))
        self.assertFalse({"react", "typescript"} & claims(ev, "service:"))

    def test_web_react_and_full_stack_typescript_still_earn_credit(self):
        html = "<p>We offer frontend development with React and TypeScript alongside a Node.js API.</p>"
        ev, _ = analyze([u.snap(html, "https://acme.example/services/")])
        self.assertTrue({"react", "typescript"} <= claims(ev, "service:"))


if __name__ == "__main__":
    unittest.main()
