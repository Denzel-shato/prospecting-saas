import unittest

import tests.util as u
from vm1.drafts import STATUS, build_draft, lint_draft
from vm1.evidence import Evidence, extract_evidence
from vm1.people import find_decision_makers
from vm1.score import NOT_RESEARCHABLE, score_company

K = "x.example"


def score(body, **kw):
    s = u.snap(body)
    evs = extract_evidence(K, [s])
    dms = find_decision_makers([s])
    kw.setdefault("homepage_ok", True)
    return evs, dms, score_company(evs, dms, **kw)


def rules(res):
    return [e["rule"] for e in res.hard_exclusions]


class ExclusionTests(unittest.TestCase):
    def test_staffing_excluded_with_no_score(self):
        _, _, r = score("<h1>We are an IT staffing agency</h1><p>Austin, TX 78701. React.</p>")
        self.assertEqual((r.total, r.tier), (None, "excluded"))
        self.assertIn("staffing_recruiting", rules(r))

    def test_non_us_only_excluded_but_dual_flagged(self):
        _, _, r = score("<p>We are based in London, United Kingdom. React studio.</p>")
        self.assertIn("non_us_only", rules(r))
        _, _, r = score("<p>We are based in London, United Kingdom.</p><p>US office: 1 Main St, Austin, TX 78701.</p>")
        self.assertFalse(r.hard_exclusions)
        self.assertTrue(any("conflict" in f for f in r.flags))

    def test_oversized_excluded_and_above_band_penalised(self):
        _, _, r = score("<p>Our 400 employees build software in Austin, TX 78701.</p>")
        self.assertIn("size_over_250", rules(r))
        _, _, r = score("<p>Software studio, Austin, TX 78701. We are a team of 80.</p>")
        self.assertFalse(r.hard_exclusions)
        self.assertTrue(any(c["points"] == -10 for c in r.components))

    def test_unreachable_and_directory_domain_excluded(self):
        self.assertIn("unreachable", rules(score_company([], [], homepage_ok=False)))
        self.assertIn("non_first_party_domain",
                      rules(score_company([], [], homepage_ok=True, first_party_domain=False)))

    def test_robots_blocked_is_not_an_exclusion_violation(self):
        r = score_company([], [], homepage_ok=False, robots_blocked=True)
        self.assertEqual(r.tier, NOT_RESEARCHABLE)
        self.assertFalse(r.hard_exclusions)

    def test_unknown_evidence_earns_nothing_and_unknowns_listed(self):
        evs, _, r = score("<p>We are a team of 8. We have 35 employees. Coming soon.</p>")
        self.assertFalse([c for c in r.components if c["rule"].startswith("size")])
        self.assertTrue(any(x.startswith("size") for x in r.unknowns))
        self.assertTrue(any(x.startswith("location") for x in r.unknowns))

    def test_hiring_adds_no_points(self):
        _, _, a = score("<p>React studio, Austin, TX 78701.</p>")
        _, _, b = score("<p>React studio, Austin, TX 78701.</p><p>We're hiring!</p>")
        self.assertEqual(a.total, b.total)

    def test_deterministic_and_explainable(self):
        body = "<p>Software studio. React, Next.js. Austin, TX 78701. Team of 12.</p>"
        _, _, a = score(body)
        _, _, b = score(body)
        self.assertEqual(a.to_dict(), b.to_dict())
        self.assertEqual(a.total, sum(c["points"] for c in a.components))
        self.assertIn("+", a.explain())


class PeopleTests(unittest.TestCase):
    def test_named_leader_found_with_source(self):
        s = u.team_snap("<div><h3>Maya Okafor</h3><p>Founder &amp; CEO</p></div>")
        d = find_decision_makers([s])
        self.assertEqual((d[0].name, d[0].role_class, d[0].source_url), ("Maya Okafor", "founder_ceo", s.url))
        self.assertEqual(d[0].basis, "team_page")

    def test_inline_and_reverse_forms(self):
        self.assertEqual(find_decision_makers([u.team_snap("<p>Daniel Reyes, CTO</p>")])[0].name, "Daniel Reyes")
        self.assertEqual(find_decision_makers([u.team_snap("<p>CEO: Ana Silva</p>")])[0].name, "Ana Silva")

    def test_decoys_and_non_leaders_ignored(self):
        body = ("<h1>Meet Our Team</h1><h2>Our Leadership</h2><p>Founder</p><h2>Founder Story</h2>"
                "<div><h3>Chris Lee</h3><p>Lead Designer</p></div><p>Contact Us, CEO</p>")
        self.assertEqual(find_decision_makers([u.snap(body)]), [])

    def test_unknown_when_nobody_named_and_no_email_fields(self):
        self.assertEqual(find_decision_makers([u.snap("<p>Our founder started this in 2015.</p>")]), [])
        for d in find_decision_makers([u.team_snap("<p>Daniel Reyes, CTO</p>")]):
            self.assertFalse(hasattr(d, "email"))

    def test_ordering_prefers_founder_ceo(self):
        body = "<p>Daniel Reyes, CTO</p><p>Maya Okafor, Founder</p>"
        self.assertEqual(find_decision_makers([u.team_snap(body)])[0].name, "Maya Okafor")

    def test_mailto_links_are_never_collected(self):
        s = u.snap('<a href="mailto:boss@x.example">Maya Okafor, CEO</a><a href="/team">Team</a>')
        self.assertFalse([l for l, _ in s.page.links if "mailto" in l or "@" in l])


class DraftTests(unittest.TestCase):
    BODY = "<p>Software studio building React and Next.js web applications in Austin, TX 78701.</p>"

    def make(self, body=None, verified=True, people=True):
        s = u.snap(body or self.BODY)
        team = u.team_snap("<p>Maya Okafor, Founder</p>")
        evs = extract_evidence(K, [s])
        ids = {e.id for e in evs} if verified else set()
        return evs, build_draft(domain=K, company_name="Acme", evidence=evs, verified_ids=ids,
                                decision_makers=find_decision_makers([s, team] if people else [s]))

    def test_draft_is_unsent_with_no_email_and_passes_lint(self):
        _, d = self.make()
        self.assertEqual(d.status, STATUS)
        self.assertIsNone(d.recipient["email"])
        self.assertEqual(d.recipient["email_status"], "not_collected")
        self.assertTrue(d.lint["passed"], d.lint)
        self.assertIn("Hi Maya", d.body)
        self.assertNotIn("@", d.body)

    def test_every_claim_traces_to_assertable_evidence(self):
        evs, d = self.make()
        by = {e.id: e for e in evs}
        self.assertTrue(d.claims_used)
        for c in d.claims_used:
            self.assertIn(by[c["evidence_id"]].level, ("source_supported", "corroborated", "user_verified"))

    def test_unverified_or_unsupported_evidence_is_omitted(self):
        evs, d = self.make(verified=False)
        self.assertIsNone(d, "no verified evidence => no personalised draft at all")
        evs, d = self.make()
        evs[0].level = "inferred"
        d2 = build_draft(domain=K, company_name="Acme", evidence=[evs[0]], verified_ids={evs[0].id},
                         decision_makers=[])
        self.assertIsNone(d2)

    def test_no_evidence_means_no_draft_and_no_invented_claims(self):
        self.assertIsNone(self.make("<p>Coming soon.</p>")[1])

    def test_no_named_contact_falls_back_to_team_greeting(self):
        _, d = self.make("<p>Software studio building React apps. Austin, TX 78701.</p>", people=False)
        self.assertIsNone(d.recipient["name"])
        self.assertIn("Acme team", d.body)

    def test_lint_catches_unsupported_assertions_and_emails(self):
        evs, d = self.make()
        by = {e.id: e for e in evs}
        d.body += " Congrats on your recent funding! Reach me at me@x.com"
        res = lint_draft(d, by, {e.id for e in evs})
        self.assertFalse(res["passed"])
        self.assertGreaterEqual(res["unsupported_factual_assertions"], 2)
        d.recipient["email"] = "guess@x.example"
        self.assertTrue(any("recipient email" in i for i in lint_draft(d, by, set(by))["issues"]))

    def test_lint_flags_fabricated_evidence_reference(self):
        evs, d = self.make()
        d.claims_used.append({"sentence": "x", "evidence_id": "ev_fake", "level": "source_supported", "source_url": ""})
        self.assertFalse(lint_draft(d, {e.id: e for e in evs}, {e.id for e in evs})["passed"])


if __name__ == "__main__":
    unittest.main()
