"""Engine #2 (ordering): directory text is compared with the ICP's own vocabulary, so the seeded hash only
separates candidates that no record signal distinguishes. Offline, fictional data; never a lead-quality claim."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from tests.util import ROOT
from vm1.discovery import AUTOMATED, Candidate
from vm1.pickanagency import PickAnAgencyAdapter
from vm1.pipeline import prioritize_pool, select_with_reasons
from vm1.policy import load_policy
from vm1.prequalify import order_pool, prequalify, term_breadth

FRONTEND = load_policy(ROOT / "icp" / "frontend-studio.json")
ECOMMERCE = load_policy(ROOT / "icp" / "ecommerce-marketing-agency.json")
SEEDS = [f"seed-{i}" for i in range(12)]

# What PickAnAgency attaches to every record found by its "Software Development" category query:
# the SAME service-hint boolean, so the integer priority cannot tell these records apart.
BASE = {"directory_service_hint": True, "directory_frontend_hint": False}


def cand(domain, **attrs):
    return SimpleNamespace(domain=domain, attrs={**BASE, **attrs})


def domains(rows):
    return [c.domain for c, _, _ in rows]


class DirectoryTextUsesIcpVocabulary(unittest.TestCase):
    def pool(self):
        good = [cand(f"dev{i}.example", directory_services=["Web Development", "Software Development"],
                     directory_tagline="Design and development for product teams") for i in range(6)]
        bad = [cand(f"mkt{i}.example", directory_services=["SEO", "Social Media Marketing"],
                    directory_tagline="Social media growth on a cloud platform") for i in range(6)]
        return good, bad

    def test_equal_priority_records_are_not_left_to_the_hash(self):
        good, bad = self.pool()
        self.assertEqual({prequalify(c.attrs, FRONTEND)[0] for c in good + bad}, {3},
                         "premise: the integer priority ties across the whole pool")
        for seed in SEEDS:
            with self.subTest(seed=seed):
                top = domains(order_pool(good + bad, seed, FRONTEND))[:6]
                self.assertEqual(set(top), {c.domain for c in good})

    def test_text_never_changes_the_priority_score(self):
        attrs = {"directory_tagline": "web development agency", "directory_services": ["Web Development"]}
        self.assertEqual(prequalify(attrs, FRONTEND), (0, []))

    def test_missing_text_is_neutral_not_a_penalty(self):
        pos = cand("pos.example", directory_services=["Web Development"])
        unknown = cand("unknown.example")
        neg = cand("neg.example", directory_services=["Social Media Marketing"])
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(domains(order_pool([neg, unknown, pos], seed, FRONTEND)),
                                 ["pos.example", "unknown.example", "neg.example"])
        self.assertEqual(term_breadth({}, FRONTEND), (0, [], []))

    def test_breadth_is_graded_by_distinct_terms(self):
        broad = cand("broad.example", directory_services=["Web Design", "Web Development", "App Development"])
        narrow = cand("narrow.example", directory_services=["Web Development"])
        repeated = cand("repeated.example", directory_services=["Web Development", "web development"])
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(domains(order_pool([repeated, narrow, broad], seed, FRONTEND))[0], "broad.example")
        self.assertEqual(term_breadth(repeated.attrs, FRONTEND)[0], 1, "a repeated term counts once")

    def test_vocabulary_is_the_icps_not_a_hardcoded_frontend_list(self):
        web = cand("web.example", directory_services=["Web Development"])
        shop = cand("shop.example", directory_tagline="Shopify online store builder")
        for seed in SEEDS:
            with self.subTest(seed=seed):
                self.assertEqual(domains(order_pool([shop, web], seed, FRONTEND))[0], "web.example")
                self.assertEqual(domains(order_pool([web, shop], seed, ECOMMERCE))[0], "shop.example")

    def test_hash_still_orders_candidates_nothing_distinguishes(self):
        pool = [cand(f"same{i}.example") for i in range(20)]
        by_seed = {s: domains(order_pool(pool, s, FRONTEND)) for s in SEEDS}
        self.assertGreater(len({tuple(v) for v in by_seed.values()}), 1)
        for s in SEEDS:
            self.assertEqual(by_seed[s], domains(order_pool(list(reversed(pool)), s, FRONTEND)))


class SelectionExplainsTieBreak(unittest.TestCase):
    def test_prioritize_pool_covers_whole_pool_and_explains_text_match(self):
        pool = [cand("a.example", directory_services=["Web Development"]), cand("b.example"),
                cand("c.example", directory_services=["Social Media Marketing"])]
        rows, info = prioritize_pool(pool, "s", FRONTEND)
        self.assertEqual(len(rows), 3)
        self.assertEqual(info["a.example"]["tie_break"]["matched_positive"], ["web development"])
        self.assertEqual(info["c.example"]["tie_break"]["matched_negative"], ["social media"])
        self.assertEqual(info["a.example"]["priority"], 3)
        self.assertNotIn("tie_break", info["b.example"])

    def test_select_with_reasons_is_a_prefix_of_the_full_order(self):
        pool = [cand(f"x{i}.example", directory_services=["Web Development"] * (i % 3)) for i in range(9)]
        rows, _ = prioritize_pool(pool, "s", FRONTEND)
        chosen, info = select_with_reasons(pool, 4, "s", FRONTEND)
        self.assertEqual([c.domain for c in chosen], [r.candidate.domain for r in rows[:4]])
        self.assertLessEqual(set(info), {c.domain for c in chosen})


class PickAnAgencyKeepsServiceLabels(unittest.TestCase):
    def test_services_are_kept_bounded_and_string_only(self):
        row = dict(name="Many Services", website="https://many.example", slug="many", location={"country": "US"},
                   profile_url="https://www.pickanagency.com/agencies/many",
                   services=[f"Service {i}" for i in range(15)] + [7, None, "  ", "x" * 100],
                   tagline="Hi")

        class Client:
            def request_json(self, method, url):
                return {"results": [row]}

        (c,) = PickAnAgencyAdapter(Client(), search_terms=("custom software",)).discover()
        self.assertEqual(c.discovery_method, AUTOMATED)
        self.assertEqual(c.attrs["directory_services"], [f"Service {i}" for i in range(10)])
        row["services"] = [7, "x" * 100]
        (c,) = PickAnAgencyAdapter(Client(), search_terms=("custom software",)).discover()
        self.assertEqual(c.attrs["directory_services"], ["x" * 60])

    def test_candidate_dataclass_is_unchanged(self):
        c = Candidate("n", "https://n.example", AUTOMATED, "pickanagency")
        self.assertEqual(c.attrs, {})


if __name__ == "__main__":
    unittest.main()
