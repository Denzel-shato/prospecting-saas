"""Issue #5: policy-aware discovery ordering (no network, no lead-quality claims)."""
from __future__ import annotations

import copy
import unittest
from types import SimpleNamespace

from tests.reference.legacy_prequalify_516c9f4 import (
    prequalify as legacy_prequalify,
    order_pool as legacy_order_pool,
    coverage as legacy_coverage,
)
from vm1.policy import baseline_policy, load_policy
from vm1.prequalify import prequalify, order_pool, coverage


def candidate(domain, description="", employees=None, listed=False):
    return SimpleNamespace(
        domain=domain,
        attrs={"description": description, "employees": employees, "listed_on_exchange": listed},
    )


def changed_policy():
    raw = copy.deepcopy(baseline_policy().to_dict())
    raw["id"] = "ecommerce-prospects-test"
    raw["prequalify"] = {
        "positive_terms": ["online store", "ecommerce", "shopify"],
        "negative_terms": ["software development agency", "outsourc*"],
    }
    raw["size"]["band"] = [10, 100]
    raw["size"]["hard_max"] = 500
    return load_policy(raw)


class BaselineDifferential(unittest.TestCase):
    def test_record_priority_matches_frozen_legacy(self):
        samples = [
            "", "web development agency", "small software consultancy", "product studio",
            "outsourcing services", "outsourced developers", "development shop",
            "custom software", "cloud platform", "SaaS marketplace",
            "social network", "artificial intelligence", "cybersecurity",
            "cyber security", "e-commerce", "ecommerce", "consulting firm",
            "enterprise software development company", "database",
            "design and development", "video game development studio",
            "a leading development agency", "recruiting business",
        ]
        for desc in samples:
            for headcount in (None, 4, 5, 50, 51, 250, 251):
                for listed in (False, True):
                    attrs = {"description": desc, "employees": headcount, "listed_on_exchange": listed}
                    with self.subTest(desc=desc, employees=headcount, listed=listed):
                        self.assertEqual(prequalify(attrs), legacy_prequalify(attrs))

    def test_baseline_ordering_and_coverage_match(self):
        pool = [
            candidate("one.example", "web development agency", 11),
            candidate("two.example", "cloud SaaS platform", 180, True),
            candidate("three.example", "software consultancy"),
            candidate("four.example"),
        ]
        self.assertEqual(order_pool(pool, "fixed-seed"), legacy_order_pool(pool, "fixed-seed"))
        prev, now = legacy_coverage(pool), coverage(pool)
        for key in prev:
            self.assertEqual(now[key], prev[key])


class PolicySwitch(unittest.TestCase):
    def test_same_description_different_priorities(self):
        ecommerce = changed_policy()
        attrs = {"description": "A Shopify ecommerce online store", "employees": 20}
        self.assertLess(prequalify(attrs)[0], 0)   # baseline treats ecommerce as vendor-like
        self.assertGreater(prequalify(attrs, ecommerce)[0], 0)
        agency = {"description": "software development agency outsourcing", "employees": 20}
        self.assertGreater(prequalify(agency)[0], prequalify(agency, ecommerce)[0])

    def test_software_first_directory_tie_break_is_only_prioritization(self):
        pol = load_policy("icp/frontend-studio-worldwide.json")
        common = {"directory_service_hint": True, "directory_frontend_hint": False}
        software = {**common, "directory_software_focus_hint": True}
        marketing = {**common, "directory_marketing_focus_hint": True}
        generic = dict(common)
        self.assertEqual(prequalify(software, pol)[0], 5)
        self.assertEqual(prequalify(generic, pol)[0], 3)
        self.assertEqual(prequalify(marketing, pol)[0], 2)
        self.assertIn("directory", " ".join(prequalify(software, pol)[1]))
        source_pool = [
            SimpleNamespace(domain="general.example", attrs=generic),
            SimpleNamespace(domain="software.example", attrs=software),
            SimpleNamespace(domain="marketing.example", attrs=marketing),
        ]
        self.assertEqual([r[0].domain for r in order_pool(source_pool, "seed", pol)],
                         ["software.example", "general.example", "marketing.example"])
        self.assertEqual(prequalify(generic, pol)[0], 3)  # unchanged generic records
        non_agency_policy = changed_policy()
        self.assertEqual(prequalify(software, non_agency_policy)[0], 5)  # target stays agency_studio

    def test_policy_size_rules_and_deterministic_order(self):
        ecommerce = changed_policy()
        attrs = {"description": "", "employees": 400}
        self.assertEqual(prequalify(attrs, ecommerce), (0, []))
        self.assertEqual(prequalify(attrs)[0], -3)
        pool = [
            candidate("shop.example", "ecommerce Shopify store", 20),
            candidate("studio.example", "software development agency", 20),
        ]
        self.assertEqual(order_pool(pool, "seed", ecommerce)[0][0].domain, "shop.example")
        self.assertEqual(order_pool(pool, "seed", ecommerce), order_pool(pool, "seed", ecommerce))
        cov = coverage(pool, ecommerce)
        self.assertEqual((cov["target_like_description"], cov["negative_like_description"]), (1, 1))
        self.assertNotIn("agency_like_description", cov)


if __name__ == "__main__":
    unittest.main()
