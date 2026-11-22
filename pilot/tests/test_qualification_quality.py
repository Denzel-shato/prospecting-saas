"""Regression tests for qualification quality: identity wording, hyphenated headcounts, and keeping confirmed
disqualification apart from missing information. All offline, all fictional pages."""

from __future__ import annotations

import unittest

from tests.util import snap
from vm1.evidence import extract_evidence
from vm1.score import (DISQUALIFIED, LOW_FIT, MANUAL_REVIEW, NOT_ASSESSABLE, QUALIFIED, score_company)


def run(body: str, **kw):
    ev = extract_evidence("x.example", [snap(body)], company_name=None)
    return ev, score_company(ev, [], homepage_ok=kw.pop("homepage_ok", True), **kw)


def claims(ev):
    return {e.claim_type: e.value for e in ev}


STUDIO = ('<p>{ident} in Austin, TX 78701.</p><h2>Our services</h2><ul><li>React development</li>'
          '<li>Next.js engineering</li></ul><p>{size}</p>')


class IdentityWording(unittest.TestCase):
    def test_digital_product_agency_is_an_identity(self):
        ev, _ = run(STUDIO.format(ident="Acme is a digital product agency", size=""))
        self.assertIn("entity_type:studio_or_agency", claims(ev))

    def test_client_or_directory_mention_of_agency_is_not_identity(self):
        ev, _ = run("<blockquote>Our client, a digital product agency, loved the tool.</blockquote>"
                    "<p>Plans start with a free trial. Request a demo. Pricing. Log in.</p>")
        self.assertNotIn("entity_type:studio_or_agency", claims(ev))


class HyphenatedHeadcount(unittest.TestCase):
    def test_our_25_person_team_is_self_referential(self):
        ev, _ = run(STUDIO.format(ident="Acme is a software studio", size="Our 25-person team ships for clients."))
        self.assertEqual(claims(ev).get("size:employees"), 25)

    def test_we_are_a_12_person_studio(self):
        ev, _ = run(STUDIO.format(ident="Acme is a software studio", size="We are a 12-person studio."))
        self.assertEqual(claims(ev).get("size:employees"), 12)

    def test_third_party_hyphenated_counts_stay_unknown(self):
        for text in ("Our client, a 40-person startup, hired us.",
                     "They are a 30-person team that grew from 5.",
                     "We help 50-person companies scale.",
                     "Our 10-20 person team."):  # range: never a headcount
            ev, _ = run(STUDIO.format(ident="Acme is a software studio", size=text))
            self.assertNotIn("size:employees", claims(ev), text)

    def test_range_is_not_invented(self):
        ev, _ = run(STUDIO.format(ident="Acme is a software studio", size="A team of 10-20."))
        self.assertIsNone(claims(ev).get("size:employees"))


class StrictStrongPreserved(unittest.TestCase):
    def test_new_identity_without_size_is_never_strong(self):
        _, r = run(STUDIO.format(ident="Acme is a digital product agency", size=""))
        self.assertNotEqual(r.tier, "strong")
        self.assertIn("size: no single explicit headcount (not guessed)", r.unknowns)

    def test_new_identity_and_size_with_two_services_is_strong_only_when_all_gates_met(self):
        _, r = run(STUDIO.format(ident="Acme is a digital product agency", size="We are a 18-person studio."))
        self.assertEqual(r.company_type, "agency_studio")
        self.assertEqual(r.tier, "strong")

    def test_plausible_studio_without_identity_stays_manual_review_not_strong(self):
        body = ('<p>We help startups design and build digital products from Denver, CO 80202.</p>'
                '<h2>What we do</h2><ul><li>Frontend development</li><li>Web applications</li></ul>')
        _, r = run(body)
        self.assertEqual(r.company_type, "unclear")
        self.assertIn(r.tier, ("weak",))
        self.assertTrue(any(f.startswith("manual_review") for f in r.flags))
        self.assertEqual(r.disposition, MANUAL_REVIEW)


class DispositionSeparatesMissingFromConfirmed(unittest.TestCase):
    def test_unreachable_homepage_is_not_assessable_not_disqualified(self):
        _, r = run("", homepage_ok=False)
        self.assertEqual(r.tier, "excluded")
        self.assertEqual(r.disposition, NOT_ASSESSABLE)

    def test_robots_blocked_is_not_assessable(self):
        _, r = run("", robots_blocked=True)
        self.assertEqual(r.disposition, NOT_ASSESSABLE)

    def test_evidence_based_staffing_exclusion_is_disqualified(self):
        _, r = run("<p>We are an IT staffing agency in Austin, TX 78701.</p>")
        self.assertEqual(r.tier, "excluded")
        self.assertEqual(r.disposition, DISQUALIFIED)

    def test_unreachable_plus_confirmed_exclusion_is_disqualified(self):
        _, r = run("<p>We are a staffing agency. Executive search.</p>", homepage_ok=False)
        self.assertEqual(r.disposition, DISQUALIFIED)

    def test_qualified_and_low_fit(self):
        _, q = run(STUDIO.format(ident="Acme is a software studio", size="We are a 14-person studio."))
        self.assertEqual(q.disposition, QUALIFIED)
        _, lf = run('<p>Acme is a software studio.</p><h2>Our services</h2><ul><li>React development</li></ul>')
        self.assertEqual(lf.company_type, "agency_studio")
        self.assertEqual(lf.tier, "weak")
        self.assertEqual(lf.disposition, LOW_FIT)


if __name__ == "__main__":
    unittest.main()
