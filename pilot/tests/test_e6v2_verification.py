"""Engine #6 V2 deterministic verification: synthetic passages only (fictional people/companies, no AI, no network)."""
import json
import unittest

from tests.util import snap, team_snap
from vm1.e6v2 import prepare_evidence
from vm1.e6v2_verify import ACCEPTED, MANUAL_REVIEW, REJECTED, verify_decision_makers

KEY, COMPANY = "acme.example", "Acme Studio"

TEAM_HTML = """<h1>Meet the Team</h1>
<div class="person"><div class="person-info-name">Jane Doe</div><div class="person-info-title">Co-Founder &amp; CEO</div></div>
<div class="person"><div class="person-info-name">Pat Lee</div><div class="person-info-title">Senior Engineer</div></div>
<div class="person"><div class="person-info-name">Sam Poe</div><div class="person-info-title">CTO at Globex Corp</div></div>"""
TESTIMONIAL_HTML = """<h1>What clients say</h1><blockquote><p>Great work from the whole crew, truly.</p>
<p>Mary Major, CEO of Globex Corp</p></blockquote>"""
FOOTER_HTML = "<h1>Home</h1><footer><p>Site by Kim Park, Founder of Pixel Works</p></footer>"


def by_text(result, needle):
    return next(p for p in result.passages if needle in p.text)


class VerifyBase(unittest.TestCase):
    def setUp(self):
        self.team = prepare_evidence([team_snap(TEAM_HTML)])
        self.p_jane = by_text(self.team, "Jane Doe")

    def claim(self, **over):
        c = {"name": "Jane Doe", "role": "Co-Founder & CEO", "company": "Acme Studio",
             "passage_id": self.p_jane.passage_id, "quote": "Jane Doe Co-Founder & CEO"}
        c.update(over)
        return c

    def verify(self, claims, passages=None):
        return verify_decision_makers({"decision_makers": claims}, passages or self.team, KEY, COMPANY)

    def one(self, **over):
        return self.verify([self.claim(**over)])[0]


class PositiveTests(VerifyBase):
    def test_exact_claim_is_accepted(self):
        v = self.one()
        self.assertEqual((v.status, v.reason), (ACCEPTED, "supported_by_first_party_quote"))

    def test_whitespace_newline_and_role_case_differences_accepted(self):
        self.assertEqual(self.one(quote="Jane Doe\nCo-Founder & CEO", role="co-founder & ceo").status, ACCEPTED)

    def test_company_domain_label_is_accepted(self):
        self.assertEqual(self.one(company="Acme").status, ACCEPTED)

    def test_accepts_json_string_and_bare_list(self):
        raw = json.dumps([self.claim()])
        self.assertEqual(verify_decision_makers(raw, self.team, KEY, COMPANY)[0].status, ACCEPTED)

    def test_passage_iterable_and_dict_inputs(self):
        self.assertEqual(self.verify([self.claim()], list(self.team.passages))[0].status, ACCEPTED)
        self.assertEqual(self.verify([self.claim()], self.team.by_id())[0].status, ACCEPTED)

    def test_each_claim_gets_its_own_verdict(self):
        out = self.verify([self.claim(), self.claim(name="Nobody Real", quote="Nobody Real")])
        self.assertEqual([v.status for v in out], [ACCEPTED, REJECTED])


class FabricationTests(VerifyBase):
    def test_nonexistent_passage_id(self):
        self.assertEqual(self.one(passage_id="ps_000000000000").reason, "unknown_passage_id")

    def test_fabricated_quote(self):
        v = self.one(quote="Jane Doe is the visionary founder")
        self.assertEqual((v.status, v.reason), (REJECTED, "quote_not_in_passage"))

    def test_quote_case_change_is_not_exact(self):
        self.assertEqual(self.one(quote="jane doe co-founder & ceo").reason, "quote_not_in_passage")

    def test_too_short_quote(self):
        self.assertEqual(self.one(quote="Jane").reason, "quote_not_in_passage")

    def test_fabricated_name_not_in_quote(self):
        v = self.one(name="Janet Doe")
        self.assertEqual((v.status, v.reason), (REJECTED, "name_not_in_quote"))

    def test_partial_name_token_is_not_a_match(self):
        self.assertEqual(self.one(name="Jane Do").reason, "name_not_in_quote")

    def test_fabricated_title(self):
        v = self.one(role="Chief Executive Officer")
        self.assertEqual((v.status, v.reason), (REJECTED, "role_not_in_quote"))

    def test_non_person_name(self):
        v = self.one(name="Our Team", quote="Meet the Team")
        self.assertEqual(v.status, REJECTED)

    def test_missing_and_malformed_fields(self):
        for bad in ({"name": ""}, {"role": None}, {"passage_id": 7}):
            self.assertEqual(self.one(**bad).status, REJECTED)
        out = verify_decision_makers({"decision_makers": ["Jane Doe", None]}, self.team, KEY, COMPANY)
        self.assertTrue(all(v.reason == "malformed_entry" for v in out))
        self.assertEqual(verify_decision_makers("not json", self.team, KEY, COMPANY)[0].status, REJECTED)


class CompanyAndThirdPartyTests(VerifyBase):
    def test_company_mismatch(self):
        v = self.one(company="Globex Corp")
        self.assertEqual((v.status, v.reason), (REJECTED, "company_mismatch"))

    def test_role_tied_to_other_company_in_first_party_page(self):
        p = by_text(self.team, "Sam Poe")
        v = self.verify([{"name": "Sam Poe", "role": "CTO", "company": "Acme Studio",
                          "passage_id": p.passage_id, "quote": "Sam Poe CTO at Globex Corp"}])[0]
        self.assertEqual((v.status, v.reason), (REJECTED, "role_tied_to_other_company"))

    def test_testimonial_client_attribution_rejected(self):
        res = prepare_evidence([snap(TESTIMONIAL_HTML)])
        p = by_text(res, "Mary Major")
        for company in ("Globex Corp", "Acme Studio"):  # even if the AI claims the target company
            v = self.verify([{"name": "Mary Major", "role": "CEO", "company": company,
                              "passage_id": p.passage_id, "quote": "Mary Major, CEO of Globex Corp"}], res)[0]
            self.assertEqual(v.status, REJECTED, company)

    def test_testimonial_context_rejected_even_without_other_org_text(self):
        res = prepare_evidence([snap("<h1>What clients say</h1><blockquote><p>Brilliant partners, truly.</p>"
                                     "<p>Mary Major, CEO</p></blockquote>")])
        p = by_text(res, "Mary Major")
        v = self.verify([{"name": "Mary Major", "role": "CEO", "company": "Acme Studio",
                          "passage_id": p.passage_id, "quote": "Mary Major, CEO"}], res)[0]
        self.assertEqual(v.status, REJECTED)
        self.assertTrue(v.reason.startswith("third_party_context"))

    def test_footer_mention_goes_to_manual_review_not_accepted(self):
        res = prepare_evidence([snap(FOOTER_HTML)])
        ps = [p for p in res.passages if "Kim Park" in p.text]
        if not ps:
            self.skipTest("prep did not select footer text")
        v = self.verify([{"name": "Kim Park", "role": "Founder", "company": "Acme Studio",
                          "passage_id": ps[0].passage_id, "quote": "Kim Park, Founder"}], res)[0]
        self.assertNotEqual(v.status, ACCEPTED)


class ManualReviewTests(VerifyBase):
    def test_non_leadership_role_goes_to_manual_review(self):
        p = by_text(self.team, "Senior Engineer")
        v = self.verify([{"name": "Pat Lee", "role": "Senior Engineer", "company": "Acme Studio",
                          "passage_id": p.passage_id, "quote": "Pat Lee Senior Engineer"}])[0]
        self.assertEqual((v.status, v.reason), (MANUAL_REVIEW, "role_not_recognised_leadership"))

    def test_context_unknown_goes_to_manual_review(self):
        from dataclasses import replace
        unknown = replace(self.p_jane, risk_flags=("context_unknown",))
        v = self.verify([self.claim()], [unknown])[0]
        self.assertEqual(v.status, MANUAL_REVIEW)

    def test_untrusted_page_kind_goes_to_manual_review(self):
        from dataclasses import replace
        other = replace(self.p_jane, page_kind="other")
        self.assertEqual(self.verify([self.claim()], [other])[0].reason, "page_kind_other")


class QuoteAttributionPolicyTests(unittest.TestCase):
    def test_unclassified_article_context_requires_manual_review(self):
        result = prepare_evidence([snap(
            '<article><p>Jane Doe</p><p>Founder and CEO</p></article>',
            "https://x.example/about/", home=False)])
        passage = by_text(result, "Jane Doe")
        self.assertIn("ctx:article_unknown", passage.risk_flags)
        claim = {"name": "Jane Doe", "role": "Founder and CEO", "company": COMPANY,
                 "passage_id": passage.passage_id, "quote": "Jane Doe Founder and CEO"}
        verdict = verify_decision_makers([claim], result, KEY, COMPANY)[0]
        self.assertEqual((verdict.status, verdict.reason),
                         (MANUAL_REVIEW, "unclear_context:ctx:article_unknown"))

    def test_first_person_founder_quote_with_adjacent_name_stays_manual_review(self):
        html = (
            '<h2>Where form and function work together</h2><section id="tandem">'
            '<blockquote><p>“I started Tandem with a vision to create software that is thoughtful.”</p></blockquote>'
            '<p>Soltan Adel</p><p>Founder, CEO</p></section>'
        )
        result = prepare_evidence([snap(html)])
        passage = by_text(result, "Soltan Adel")
        self.assertIn("adjacent_quote", passage.risk_flags)
        claim = {"name": "Soltan Adel", "role": "Founder, CEO", "company": "Acme Studio",
                 "passage_id": passage.passage_id, "quote": "Soltan Adel Founder, CEO"}
        verdict = verify_decision_makers([claim], result, KEY, COMPANY)[0]
        self.assertEqual((verdict.status, verdict.reason),
                         (MANUAL_REVIEW, "unclear_context:adjacent_quote"))
        self.assertNotIn("I started Tandem", passage.text)

    def test_static_wordpress_conference_page_does_not_trust_speaker_bio(self):
        html = (
            '<body class="wp-singular page page-id-22 wp-custom-logo">'
            '<article class="post-22 page type-page ast-article-single" '
            'itemtype="https://schema.org/CreativeWork">'
            '<div class="speaker-profile"><p>Gregory Cerallo</p><p>Founder and CEO</p></div>'
            '</article></body>'
        )
        result = prepare_evidence([snap(html, "https://x.example/conference/", home=False)])
        passage = by_text(result, "Gregory Cerallo")
        self.assertIn("ctx:editorial", passage.risk_flags)
        claim = {"name": "Gregory Cerallo", "role": "Founder and CEO", "company": COMPANY,
                 "passage_id": passage.passage_id, "quote": "Gregory Cerallo Founder and CEO"}
        verdict = verify_decision_makers([claim], result, KEY, COMPANY)[0]
        self.assertEqual(verdict.status, REJECTED)
        self.assertTrue(verdict.reason.startswith("third_party_context:ctx:editorial"))


if __name__ == "__main__":
    unittest.main()
