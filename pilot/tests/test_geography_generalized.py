"""Regression tests: worldwide location detection (vm1.geo). Fictional pages only."""

import unittest

import tests.util as u
from vm1.evidence import extract_evidence, verify_evidence
from vm1.policy import load_policy
from vm1.score import score_company

BASE = ("<p>We are a product studio. We build web apps, dashboards and SaaS products with React and Next.js "
        "for startups.</p><p>We are a team of 14 people.</p>")
WORLD = load_policy(u.ROOT / "icp" / "frontend-studio-worldwide.json")
JSONLD = '<script type="application/ld+json">%s</script>'


def locs(extra, **kw):
    snap = u.snap(BASE + extra, **kw)
    ev = extract_evidence("example.org", [snap])
    return ev, {e.claim_type: e.value for e in ev if e.claim_type.startswith("location")}, snap


def tier(extra):
    return score_company(extract_evidence("example.org", [u.snap(BASE + extra)]), [], homepage_ok=True,
                         policy=WORLD)


class GeneralizedLocationTests(unittest.TestCase):
    def test_hyphenated_and_unlisted_places_are_found(self):
        for text, place in [("<p>Copenhagen-based product studio.</p>", "Copenhagen"),
                            ("<p>We're a Berlin-based digital agency.</p>", "Berlin"),
                            ("<p>We are based in Tallinn.</p>", "Tallinn"),
                            ("<footer><p>Bahnhofstrasse 10, 8001 Zürich, Switzerland</p></footer>", "Switzerland"),
                            ("<p>Auckland, New Zealand</p>", "New Zealand")]:
            with self.subTest(text=text):
                _, found, _ = locs(text)
                self.assertEqual(found.get("location:non_us"), place)
                self.assertEqual(tier(text).tier, "strong")

    def test_client_testimonial_and_us_town_wording_is_not_a_base(self):
        for text in ["<p>We recently built an app for a London-based client.</p>",
                     "<p>We worked with a Berlin-based startup.</p>",
                     "<p>We are based in Dublin, CA 94568.</p>",
                     "<blockquote><p>Great team! Jane Doe, CEO, Acme, Germany</p></blockquote>",
                     "<p>Cloud-based tools for our team.</p>"]:
            with self.subTest(text=text):
                _, found, _ = locs(text)
                self.assertNotIn("location:non_us", found)

    def test_unknown_location_still_cannot_be_strong(self):
        self.assertNotEqual(tier("<p>We are a fully remote team.</p>").tier, "strong")

    def test_jsonld_org_address_is_verbatim_and_verifies(self):
        ld = JSONLD % ('{"@type":"Organization","name":"X","address":{"@type":"PostalAddress",'
                       '"addressLocality":"Cape Town","addressCountry":"ZA"}}')
        ev, found, snap = locs(ld)
        self.assertEqual(found.get("location:non_us"), "ZA")
        item = next(e for e in ev if e.claim_type == "location:non_us")
        self.assertTrue(verify_evidence(item, {snap.url: snap.page}))

    def test_jsonld_non_org_address_is_ignored(self):
        ld = JSONLD % ('{"@type":"Review","author":{"@type":"Person","name":"A"},'
                       '"itemReviewed":{"@type":"Organization","address":{"addressCountry":"DE"}}}')
        self.assertNotIn("location:non_us", locs(ld)[1])

    def test_us_state_after_city_vetoes_nonus_and_jsonld_us_is_us(self):
        ld = JSONLD % '{"@type":"Organization","address":{"addressCountry":"US"}}'
        self.assertEqual(locs(ld)[1].get("location:us"), "US")

    def test_india_based_wording_excludes_in_worldwide_icp(self):
        for text in ["<p>We're a Bengaluru-based software studio.</p>",
                     JSONLD % '{"@type":"Organization","address":{"addressCountry":"IN"}}']:
            with self.subTest(text=text):
                self.assertEqual(tier(text).tier, "excluded")

    def test_india_office_among_other_addresses_is_not_a_headquarters(self):
        ld = JSONLD % ('{"@type":"Organization","address":[{"addressCountry":"GB"},{"addressCountry":"IN"}]}')
        self.assertNotEqual(tier(ld).tier, "excluded")
        self.assertEqual(tier("<p>A Pune-based client trusts us.</p><p>We are based in London.</p>").tier, "strong")


if __name__ == "__main__":
    unittest.main()
