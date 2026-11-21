import unittest

import tests.util as u
from vm1.discovery import Candidate
from vm1.evidence import (CORROBORATED, SOURCE_SUPPORTED, UNKNOWN, apply_discovery_record, extract_evidence,
                          verify_evidence)

K = "x.example"


def ev_by_type(evs):
    return {e.claim_type: e for e in evs}


class EvidenceTests(unittest.TestCase):
    def test_supported_claims_have_source_timestamp_and_verbatim_excerpt(self):
        s = u.snap("<p>We build web applications with React and Next.js. Based in Austin, TX 78701.</p>")
        evs = extract_evidence(K, [s])
        by = ev_by_type(evs)
        self.assertEqual(by["service:react"].level, SOURCE_SUPPORTED)
        self.assertEqual(by["location:us"].value, "TX")
        pages = {s.url: s.page}
        for e in evs:
            self.assertEqual((e.source_url, e.fetched_at), (s.url, u.TS))
            self.assertLessEqual(len(e.excerpt), 200)
            self.assertTrue(verify_evidence(e, pages), e.claim_type)

    def test_tampered_excerpt_fails_verification(self):
        s = u.snap("<p>We build SaaS dashboards.</p>")
        e = extract_evidence(K, [s])[0]
        e.excerpt_parts = ["We build blockchain rockets."]
        self.assertFalse(verify_evidence(e, {s.url: s.page}))
        e.excerpt_parts = ["We build SaaS dashboards."]
        self.assertFalse(verify_evidence(e, {}), "missing page cannot verify")

    def test_nothing_invented_from_empty_page(self):
        self.assertEqual(extract_evidence(K, [u.snap("<p>Coming soon.</p>")]), [])

    def test_conflicting_sizes_become_unknown_not_guessed(self):
        s = u.snap("<p>We are a team of 8.</p><p>We have 35 employees.</p>")
        size = [e for e in extract_evidence(K, [s]) if e.claim_type == "size:employees"]
        self.assertEqual(len(size), 1)
        self.assertEqual((size[0].level, size[0].value), (UNKNOWN, None))

    def test_thousands_separator_parsed(self):
        s = u.snap("<p>Our 12,000 employees ship software.</p>")
        size = [e for e in extract_evidence(K, [s]) if e.claim_type == "size:employees"][0]
        self.assertEqual(size.value, 12000)

    def test_no_size_when_absent(self):
        s = u.snap("<p>We are a React studio in Denver, CO 80202.</p>")
        self.assertFalse([e for e in extract_evidence(K, [s]) if e.claim_type == "size:employees"])

    def test_non_us_detected(self):
        s = u.snap("<p>We are based in London, United Kingdom.</p>")
        self.assertIn("location:non_us", ev_by_type(extract_evidence(K, [s])))

    def test_hiring_and_client_work_are_signals_not_intent(self):
        s = u.snap("<p>We're hiring! See our case studies.</p>")
        by = ev_by_type(extract_evidence(K, [s]))
        for key in ("signal:client_work", "signal:hiring_info_only"):
            note = by[key].notes
            self.assertIn("NOT", note)
            self.assertIn("purchase intent", note)

    def test_staffing_homepage_self_description_is_negative(self):
        s = u.snap("<h1>We are an IT staffing agency</h1>")
        self.assertIn("negative:staffing_recruiting", ev_by_type(extract_evidence(K, [s])))

    def test_staffing_on_secondary_page_is_only_a_mention(self):
        home = u.snap("<p>Software studio.</p>")
        sec = u.snap("<p>We partner with a recruiting firm.</p>", "https://x.example/about", home=False)
        by = ev_by_type(extract_evidence(K, [home, sec]))
        self.assertNotIn("negative:staffing_recruiting", by)

    def test_corroboration_requires_independent_agreeing_record(self):
        s = u.snap("<p>Our office: 1 Main St, Austin, TX 78701.</p>")
        base = extract_evidence(K, [s])
        manual = Candidate("A", "https://x.example", "manual", "manual_csv", attrs={"country": "US"})
        out = apply_discovery_record(K, manual, [*base])
        self.assertEqual(ev_by_type(out)["location:us"].level, SOURCE_SUPPORTED, "manual input is not independent")
        rec = Candidate("A", "https://x.example", "automated", "openstreetmap", source_id="node/1",
                        source_url="https://www.openstreetmap.org/node/1", retrieved_at=u.TS,
                        attrs={"country": "US", "addr:state": "TX"})
        out = apply_discovery_record(K, rec, extract_evidence(K, [s]))
        levels = {e.source_type: e.level for e in out if e.claim_type == "location:us"}
        self.assertEqual(levels["first_party_page"], CORROBORATED)
        self.assertEqual(levels["discovery_record"], SOURCE_SUPPORTED)

    def test_disagreeing_state_is_not_corroborated(self):
        s = u.snap("<p>Our office: 1 Main St, Austin, TX 78701.</p>")
        rec = Candidate("A", "https://x.example", "automated", "openstreetmap", source_id="node/1",
                        retrieved_at=u.TS, attrs={"country": "US", "addr:state": "CA"})
        out = apply_discovery_record(K, rec, extract_evidence(K, [s]))
        fp = [e for e in out if e.source_type == "first_party_page" and e.claim_type == "location:us"][0]
        self.assertEqual(fp.level, SOURCE_SUPPORTED)

    def test_user_verified_and_inferred_never_produced_automatically(self):
        s = u.snap("<p>React studio. Austin, TX 78701. Team of 12.</p>")
        for e in extract_evidence(K, [s]):
            self.assertNotIn(e.level, ("user_verified", "inferred"))


if __name__ == "__main__":
    unittest.main()
