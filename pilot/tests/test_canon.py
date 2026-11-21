import unittest

import tests.util  # noqa: F401  (sys.path)
from vm1.canon import canonical_domain, is_first_party_candidate, normalize_name, registrable_domain
from vm1.discovery import Candidate
from vm1.pipeline import dedup


class CanonTests(unittest.TestCase):
    def test_variants_collapse_to_one_key(self):
        variants = ["https://www.Acme-Studio.com/", "http://acme-studio.com/about?utm=1",
                    "ACME-STUDIO.COM", "https://acme-studio.com:443/x#frag", "blog.acme-studio.com",
                    "https://acme-studio.com."]
        self.assertEqual({canonical_domain(v) for v in variants}, {"acme-studio.com"})

    def test_multi_part_suffix(self):
        self.assertEqual(registrable_domain("www.studio.co.uk"), "studio.co.uk")

    def test_shared_hosting_tenants_are_distinct(self):
        self.assertEqual(canonical_domain("https://alpha.vercel.app"), "alpha.vercel.app")
        self.assertNotEqual(canonical_domain("alpha.vercel.app"), canonical_domain("beta.vercel.app"))
        self.assertIsNone(registrable_domain("vercel.app"))

    def test_invalid_inputs(self):
        for bad in ("", "localhost", "127.0.0.1", "http://[::1]/", "   "):
            self.assertIsNone(canonical_domain(bad), bad)

    def test_non_first_party_domains_rejected(self):
        for d in ("clutch.co", "linkedin.com", "github.com", "crunchbase.com", "wikipedia.org"):
            self.assertFalse(is_first_party_candidate(d), d)
        self.assertTrue(is_first_party_candidate("acme-studio.com"))

    def test_name_normalization(self):
        self.assertEqual(normalize_name("Brightlane Studio, LLC"), normalize_name("Brightlane Studio"))

    def test_dedup_removes_duplicates_and_directories_and_flags_name_collisions(self):
        mk = lambda n, u: Candidate(name=n, url=u, discovery_method="manual", source="manual_csv")  # noqa: E731
        cands = [mk("Acme", "https://acme.com/"), mk("Acme again", "http://www.acme.com/team"),
                 mk("Acme Inc", "https://acme.io/"), mk("Listing", "https://clutch.co/profile/acme"),
                 mk("Broken", "not a url ::")]
        kept, rejected, same = dedup(cands)
        self.assertEqual([c.domain for c in kept], ["acme.com", "acme.io"])
        reasons = sorted(r["reason"] for r in rejected)
        self.assertEqual(reasons, ["duplicate_domain", "invalid_or_unresolvable_domain",
                                   "non_first_party_domain"])
        self.assertEqual(len({c.domain for c in kept}), len(kept), "no residual duplicate domains")
        self.assertEqual(same[0]["domains"], ["acme.com", "acme.io"], "same-name different-domain flagged, not removed")


if __name__ == "__main__":
    unittest.main()
