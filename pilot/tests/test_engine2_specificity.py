"""Engine #2 (specificity): broad agency labels, ambiguous negative words and a high wording-derived priority must
not outrank company-specific software/product-development positioning. Offline; fictional `.example` records.
Ordering only: prequalify() and every qualification score are untouched."""
from __future__ import annotations

import copy
import hashlib
import json
import unittest
from types import SimpleNamespace

from tests.util import ROOT
from vm1.policy import PolicyError, load_policy
from vm1.prequalify import order_pool, prequalify, rank_pool, record_evidence, structural_priority

WORLD_PATH = ROOT / "icp" / "frontend-studio-worldwide.json"
WORLD = load_policy(WORLD_PATH)
RAW = json.loads(WORLD_PATH.read_text())
LEGACY_RAW = copy.deepcopy(RAW)
for _k in ("generic_terms", "ambiguous_negative_terms", "service_context_terms", "service_line_terms"):
    LEGACY_RAW["prequalify"].pop(_k)
LEGACY_WORLD = load_policy(LEGACY_RAW)
SEEDS = [f"s{i}" for i in range(10)]
HINT = {"directory_service_hint": True}


def cand(domain, **attrs):
    return SimpleNamespace(domain=domain, attrs={**HINT, **attrs})


def top(pool, n, seed, policy=WORLD):
    return [c.domain for c, _, _ in order_pool(pool, seed, policy)][:n]


class GenericTermsCannotInflateBreadth(unittest.TestCase):
    def test_many_generic_labels_count_once(self):
        many = record_evidence({"directory_services": ["Consulting", "Web Design", "Web Development", "Digital Agency"]}, WORLD)
        one = record_evidence({"directory_services": ["Web Development"]}, WORLD)
        self.assertEqual(many.points, one.points)
        self.assertGreater(len(many.generic), 1)

    def test_specific_positioning_beats_any_number_of_generic_labels(self):
        broad = [cand(f"broad{i}.example", directory_services=["Consulting", "Web Design", "Web Development", "Digital Agency"])
                 for i in range(8)]
        specific = cand("spec.example", directory_tagline="Custom software and app development for startups",
                        directory_services=["Software Development"])
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(top(broad + [specific], 1, seed), ["spec.example"])

    def test_same_words_weigh_more_in_company_positioning_than_in_directory_labels(self):
        positioned = record_evidence({"directory_tagline": "Custom software development company"}, WORLD)
        labelled = record_evidence({"directory_services": ["Custom software development company"]}, WORLD)
        self.assertGreater(positioned.points, labelled.points)

    def test_overlapping_phrases_are_one_term(self):
        ev = record_evidence({"directory_tagline": "A software development company"}, WORLD)
        self.assertEqual(ev.specific, ("software development company",))


class AmbiguousTermsAreReadInContext(unittest.TestCase):
    def test_saas_named_as_what_a_studio_builds_is_not_penalised(self):
        for text in ("SaaS product development studio", "Custom software development company for SaaS and fintech startups",
                     "Cloud consulting and engineering studio", "Design and engineering for ecommerce brands"):
            with self.subTest(text=text):
                ev = record_evidence({"directory_tagline": text}, WORLD)
                self.assertEqual(ev.ambiguous_penalised, (), text)
                self.assertGreaterEqual(ev.points, 0, text)

    def test_the_same_words_naming_what_a_company_sells_are_penalised(self):
        for text in ("The SaaS platform for project teams", "Cloud-based enterprise marketplace", "Leading fintech and ecommerce provider"):
            with self.subTest(text=text):
                self.assertLess(record_evidence({"directory_tagline": text}, WORLD).points, 0, text)

    def test_studio_ranks_above_vendor_even_with_identical_category_hint(self):
        studio = cand("studio.example", directory_tagline="SaaS product development studio", directory_services=["Software Development"])
        vendor = cand("vendor.example", directory_tagline="The SaaS platform for project teams", directory_services=["Software Development"])
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(top([vendor, studio], 2, seed), ["studio.example", "vendor.example"])

    def test_unambiguous_negatives_stay_negative_even_beside_service_words(self):
        self.assertLess(record_evidence({"directory_tagline": "Social media platform development"}, WORLD).points, 0)


class PriorityCannotOutweighStrongerEvidence(unittest.TestCase):
    def test_service_hint_with_only_generic_labels_loses_to_specific_description_without_hint(self):
        hinted = SimpleNamespace(domain="hinted.example", attrs={**HINT, "directory_frontend_hint": True,
                                                                   "directory_services": ["Web Development", "Consulting"]})
        described = SimpleNamespace(domain="described.example", attrs={"description": "Product studio and custom software company"})
        self.assertGreater(prequalify(hinted.attrs, WORLD)[0], prequalify(described.attrs, WORLD)[0],
                           "premise: the legacy priority prefers the hinted record")
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(top([hinted, described], 1, seed), ["described.example"])

    def test_wording_points_are_not_counted_twice(self):
        """The legacy +3 for the service hint / description wording is replaced, not added to, the evidence."""
        row = rank_pool([cand("x.example", directory_services=["Web Development"])], "s", WORLD)[0]
        self.assertEqual(row.priority, 3)
        self.assertEqual(row.rank_score, 1)
        row = rank_pool([SimpleNamespace(domain="y.example", attrs={"description": "Product studio and custom software company"})], "s", WORLD)[0]
        self.assertEqual((row.priority, row.rank_score), (3, 8))

    def test_structural_signals_still_apply(self):
        listed = cand("listed.example", directory_tagline="Custom software company", listed_on_exchange=True)
        plain = cand("plain.example", directory_tagline="Custom software company")
        self.assertEqual(top([listed, plain], 2, "s"), ["plain.example", "listed.example"])
        self.assertEqual(structural_priority({"listed_on_exchange": True}, WORLD), -4)

    def test_missing_text_is_neutral(self):
        unknown, generic = cand("u.example"), cand("g.example", directory_services=["Web Design"])
        neg = cand("n.example", directory_tagline="Social media growth platform")
        for seed in SEEDS:
            with self.subTest(seed=seed):
                order = top([neg, unknown, generic], 3, seed)
                self.assertLess(order.index("g.example"), order.index("n.example"))
                self.assertLess(order.index("u.example"), order.index("n.example"))


class MixedServiceStudios(unittest.TestCase):
    """A marketing service LABEL beside software-development evidence is a mixed agency, not a marketing business."""

    MIXED = ["Custom Software Development", "Social Media Marketing"]

    def score(self, **attrs):
        return structural_priority({**HINT, **attrs}, WORLD) + record_evidence({**HINT, **attrs}, WORLD).points

    def test_marketing_label_does_not_cancel_software_evidence(self):
        mixed = record_evidence({"directory_services": self.MIXED}, WORLD)
        software_only = record_evidence({"directory_services": ["Custom Software Development"]}, WORLD)
        self.assertEqual(mixed.points, software_only.points)
        self.assertEqual(mixed.service_line_neutralised, ("social media",))
        self.assertEqual(mixed.negative, ())

    def test_mixed_service_listing_outranks_generic_only_and_marketing_only(self):
        mixed = cand("mixed.example", directory_services=self.MIXED)
        generic = cand("generic.example", directory_services=["Consulting", "Web Design", "Web Development", "Digital Agency"])
        marketing = cand("marketing.example", directory_services=["Social Media Marketing", "SEO"])
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(top([marketing, generic, mixed], 3, seed), ["mixed.example", "generic.example", "marketing.example"])

    def test_extra_services_do_not_help_a_mixed_studio_either(self):
        a = self.score(directory_services=["Custom Software Development", "Web Development"])
        b = self.score(directory_services=["Custom Software Development", "Web Development", "Social Media Marketing"])
        self.assertEqual(a, b, "neutral, not a bonus")

    def test_marketing_only_labels_keep_the_penalty(self):
        ev = record_evidence({"directory_services": ["Social Media Marketing", "SEO"]}, WORLD)
        self.assertEqual(ev.points, -2)
        self.assertEqual(ev.negative, ("social media",))

    def test_marketing_label_beside_only_generic_web_labels_is_still_penalised(self):
        ev = record_evidence({"directory_services": ["Web Development", "Web Design", "Social Media Marketing"]}, WORLD)
        self.assertEqual(ev.negative, ("social media",))
        self.assertEqual(ev.service_line_neutralised, ())

    def test_misleading_tagline_stays_authoritative(self):
        """First-party positioning outranks labels: a marketing tagline is penalised even when labels list software."""
        misleading = record_evidence({"directory_tagline": "Social media growth agency",
                                      "directory_services": self.MIXED}, WORLD)
        self.assertEqual(misleading.negative, ("social media",))
        self.assertEqual(misleading.service_line_neutralised, ())
        honest = record_evidence({"directory_tagline": "Custom software and app development studio",
                                  "directory_services": self.MIXED}, WORLD)
        self.assertGreater(honest.points, misleading.points)
        studio = cand("studio.example", directory_tagline="Custom software studio", directory_services=self.MIXED)
        decoy = cand("decoy.example", directory_tagline="Social media growth agency", directory_services=self.MIXED)
        for seed in SEEDS:
            self.assertEqual(top([decoy, studio], 2, seed), ["studio.example", "decoy.example"])

    def test_tagline_naming_both_is_neutral_only_with_explicit_software_specialization(self):
        both = record_evidence({"directory_tagline": "Custom software development and social media marketing"}, WORLD)
        self.assertEqual(both.negative, ())
        self.assertEqual(both.service_line_neutralised, ("social media",))
        marketing = record_evidence({"directory_tagline": "Social media marketing and web design"}, WORLD)
        self.assertEqual(marketing.negative, ("social media",))

    def test_saas_vendor_listing_with_marketing_label_is_not_rescued(self):
        vendor = record_evidence({"directory_tagline": "The SaaS platform for project teams",
                                  "directory_services": ["Social Media Marketing"]}, WORLD)
        self.assertLess(vendor.points, 0)
        mixed_vendor = record_evidence({"directory_tagline": "The SaaS platform for project teams",
                                        "directory_services": self.MIXED}, WORLD)
        self.assertEqual(mixed_vendor.ambiguous_penalised, ("saas",))
        self.assertIn("platform", mixed_vendor.negative)

    def test_missing_metadata_is_neutral(self):
        self.assertEqual(record_evidence({}, WORLD).points, 0)
        self.assertEqual(record_evidence({"directory_services": [], "directory_tagline": ""}, WORLD).points, 0)
        self.assertEqual(record_evidence({"directory_services": None}, WORLD).points, 0)
        unknown, marketing = cand("u.example"), cand("m.example", directory_services=["Social Media Marketing"])
        self.assertEqual(top([marketing, unknown], 2, "s"), ["u.example", "m.example"])

    def test_listed_or_oversized_mixed_agencies_still_lose_structural_points(self):
        base = self.score(directory_services=self.MIXED)
        self.assertEqual(self.score(directory_services=self.MIXED, listed_on_exchange=True), base - 4)
        self.assertEqual(self.score(directory_services=self.MIXED, directory_marketing_focus_hint=True), base - 1)

    def test_other_icps_do_not_use_service_line_terms(self):
        for name in ("frontend-studio", "ecommerce-marketing-agency", "ai-automation-service-businesses"):
            self.assertEqual(load_policy(ROOT / "icp" / f"{name}.json").prequalify.service_line_terms, (), name)

    def test_service_line_terms_must_be_negative_terms(self):
        raw = copy.deepcopy(RAW)
        raw["prequalify"]["service_line_terms"] = ["not a listed term"]
        with self.assertRaises(PolicyError):
            load_policy(raw)


class CompatibilityAndProvenance(unittest.TestCase):
    def pool(self):
        return [cand("a.example", directory_tagline="Product studio", directory_services=["Software Development"]),
                cand("b.example", directory_tagline="SaaS platform", directory_services=["Web Design"]),
                cand("c.example", description="American cloud company"),
                cand("d.example", directory_services=["SEO", "Web Development", "Consulting"]),
                cand("e.example")]

    def test_prequalify_is_identical_with_and_without_the_new_vocabulary(self):
        for c in self.pool():
            self.assertEqual(prequalify(c.attrs, WORLD), prequalify(c.attrs, LEGACY_WORLD))

    def test_policy_without_vocabulary_keeps_legacy_order_exactly(self):
        pool = self.pool()
        for seed in SEEDS:
            expected = sorted(pool, key=lambda c: (-prequalify(c.attrs, LEGACY_WORLD)[0],
                                                   -next(r.breadth for r in rank_pool(pool, seed, LEGACY_WORLD) if r.candidate is c),
                                                   hashlib.sha256(f"{seed}|{c.domain}".encode()).hexdigest()))
            rows = rank_pool(pool, seed, LEGACY_WORLD)
            self.assertEqual([r.candidate.domain for r in rows], [c.domain for c in expected])
            self.assertTrue(all(r.rank_score is None and r.evidence is None for r in rows))

    def test_other_icps_are_unchanged(self):
        for name in ("frontend-studio", "ecommerce-marketing-agency", "ai-automation-service-businesses"):
            pol = load_policy(ROOT / "icp" / f"{name}.json")
            self.assertFalse(pol.prequalify.uses_specificity, name)
            rows = rank_pool(self.pool(), "s", pol)
            self.assertTrue(all(r.rank_score is None for r in rows), name)

    def test_ranking_is_a_permutation_and_does_not_touch_records(self):
        pool = self.pool()
        before = copy.deepcopy([c.attrs for c in pool])
        rows = rank_pool(pool, "s", WORLD)
        self.assertEqual(sorted(r.candidate.domain for r in rows), sorted(c.domain for c in pool))
        self.assertEqual([c.attrs for c in pool], before)

    def test_order_is_deterministic_and_input_order_independent(self):
        pool = self.pool()
        for seed in SEEDS:
            self.assertEqual(top(pool, 5, seed), top(list(reversed(pool)), 5, seed))

    def test_manifest_explanation_names_the_matched_terms(self):
        row = next(r for r in rank_pool(self.pool(), "s", WORLD) if r.candidate.domain == "a.example")
        tie = row.tie_break()
        self.assertEqual(tie["rank_score"], row.rank_score)
        self.assertIn("product studio", tie["matched_specific"])

    def test_hash_still_separates_otherwise_equal_candidates(self):
        pool = [cand(f"same{i}.example") for i in range(20)]
        self.assertGreater(len({tuple(top(pool, 20, s)) for s in SEEDS}), 1)


class PolicyValidation(unittest.TestCase):
    def load(self, **changes):
        raw = copy.deepcopy(RAW)
        raw["prequalify"].update(changes)
        return load_policy(raw)

    def test_generic_terms_must_be_positive_terms(self):
        with self.assertRaises(PolicyError):
            self.load(generic_terms=["not a listed term"])

    def test_ambiguous_terms_must_be_negative_terms_and_need_context(self):
        with self.assertRaises(PolicyError):
            self.load(ambiguous_negative_terms=["not a listed term"])
        with self.assertRaises(PolicyError):
            self.load(service_context_terms=[])

    def test_fields_are_optional(self):
        self.assertFalse(LEGACY_WORLD.prequalify.uses_specificity)
        self.assertTrue(WORLD.prequalify.uses_specificity)


if __name__ == "__main__":
    unittest.main()
