"""Issue #5 multi-ICP facts, requalification, and safety tests.

Fictional evidence only. These tests prove policy behaviour, not real-world lead quality.
"""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import tests.util as u
from tests.reference import legacy_score_516c9f4 as legacy
from vm1.evidence import Evidence, SOURCE_SUPPORTED, INFERRED
from vm1.fixture import build_synthetic
from vm1.pipeline import RunConfig, run_pipeline
from vm1.policy import PolicyError, load_policy, baseline_policy
from vm1.requalify import requalify_run
from vm1.report import load_run
from vm1.score import classify_company, score_company

ROOT = Path(__file__).resolve().parent.parent
AUTOMATION = ROOT / "icp" / "ai-automation-service-businesses.json"
ECOMMERCE = ROOT / "icp" / "ecommerce-marketing-agency.json"


def ev(kind, value, level=SOURCE_SUPPORTED):
    return Evidence(id=f"ev_{kind}_{value}", company_key="fictional.example", claim_type=kind, value=value,
                    level=level, source_type="first_party_page", source_url="https://fictional.example/",
                    fetched_at="2026-11-22T00:00:00+00:00", excerpt=f"Fictional statement: {kind} {value}",
                    excerpt_parts=[f"Fictional statement: {kind} {value}"])


def score(evidence, policy):
    return score_company(evidence, [], homepage_ok=True, policy=policy)


class ExamplePolicies(unittest.TestCase):
    def test_policies_are_valid_versioned_and_drafts_disabled(self):
        for path in (AUTOMATION, ECOMMERCE):
            pol = load_policy(path)
            self.assertEqual(pol.schema_version, 1)
            self.assertFalse(pol.drafts_enabled)
            self.assertNotEqual(pol.id, baseline_policy().id)
            self.assertTrue(pol.digest)
            self.assertGreaterEqual(pol.max_possible_score(), pol.tiers.possible)

    def test_storefront_matches_marketing_icp_but_not_developer_icp(self):
        evidence = [
            ev("company_type:storefront_signal", "add_to_cart"),
            ev("company_type:storefront_signal", "free_shipping"),
            ev("capability:email_capture", "email_capture"),
            ev("location:us", "US"), ev("size:employees", 32),
        ]
        marketing = score(evidence, load_policy(ECOMMERCE))
        developer = score(evidence, baseline_policy())
        self.assertEqual(marketing.company_type, "ecommerce_storefront")
        self.assertIn(marketing.tier, ("possible", "strong"))
        self.assertEqual(developer.tier, "weak")
        self.assertNotEqual(marketing.total, developer.total)
        self.assertEqual(evidence[0].value, "add_to_cart", "policy must not change source evidence")

    def test_local_service_matches_automation_icp_not_storefront(self):
        evidence = [
            ev("company_type:local_service_signal", "free_estimate"),
            ev("company_type:local_service_signal", "licensed_insured"),
            ev("service:home_services", "home_services"),
            ev("capability:customer_intake", "customer_intake"),
            ev("location:us", "US"), ev("size:employees", 25),
        ]
        automation = score(evidence, load_policy(AUTOMATION))
        ecommerce = score(evidence, load_policy(ECOMMERCE))
        self.assertEqual((automation.company_type, automation.tier), ("service_business", "strong"))
        self.assertEqual(ecommerce.tier, "weak")

    def test_missing_second_independent_identity_signal_does_not_qualify(self):
        evidence = [ev("company_type:storefront_signal", "add_to_cart"),
                    ev("capability:email_capture", "email_capture"),
                    ev("location:us", "US"), ev("size:employees", 32)]
        result = score(evidence, load_policy(ECOMMERCE))
        self.assertEqual((result.company_type, result.tier), ("unclear", "weak"))

    def test_competitor_marketing_agency_excluded_from_storefront_icp(self):
        evidence = [
            ev("company_type:storefront_signal", "shop_cta"),
            ev("company_type:storefront_signal", "returns_policy"),
            ev("capability:email_capture", "email_capture"),
            ev("entity_type:marketing_agency", "marketing_agency"),
        ]
        result = score(evidence, load_policy(ECOMMERCE))
        self.assertEqual(result.tier, "excluded")
        self.assertEqual(result.company_type, "marketing_agency_competitor")

    def test_inferred_identity_signals_are_not_accepted(self):
        evidence = [
            ev("company_type:storefront_signal", "add_to_cart", INFERRED),
            ev("company_type:storefront_signal", "free_shipping", INFERRED),
            ev("capability:email_capture", "email_capture"),
        ]
        result = score(evidence, load_policy(ECOMMERCE))
        self.assertEqual(result.tier, "weak")

    def test_invalid_claim_type_is_rejected(self):
        raw = copy.deepcopy(load_policy(ECOMMERCE).to_dict())
        raw["target_type"]["identity"][0]["claim"] = "company_type:invented_fact"
        with self.assertRaises(PolicyError):
            load_policy(raw)


class Requalification(unittest.TestCase):
    def test_rescore_stored_evidence_without_refetching_or_drafts(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            adapters, fetcher = build_synthetic(u.WORLD)
            original = run_pipeline(
                RunConfig(icp=baseline_policy(), out_dir=root / "source", mode="synthetic_fixture"),
                adapters, fetcher,
            )
            source = Path(original["run_dir"])
            dest = requalify_run(source, ECOMMERCE, root / "derived")
            derived = load_run(dest)
            self.assertEqual(derived["manifest"]["mode"], "requalify")
            self.assertFalse(derived["manifest"]["requalification"]["counts_as_independent_live_result"])
            self.assertFalse(derived["manifest"]["requalification"]["counts_as_fresh_discovery"])
            self.assertEqual(derived["manifest"]["http_requests_logged"], 0)
            self.assertEqual(derived["manifest"]["paid_api_spend_usd"], 0)
            self.assertEqual(derived["drafts"], [])
            self.assertEqual(len(derived["companies"]), len(original["companies"]))
            original_by = {c["domain"]: c for c in original["companies"]}
            for c in derived["companies"]:
                self.assertEqual(c["evidence"], original_by[c["domain"]]["evidence"])
            report = (dest / "report.md").read_text(encoding="utf-8")
            self.assertIn("OFFLINE REQUALIFICATION", report)
            self.assertIn("not new", report.lower())

    def test_invalid_policy_writes_no_derived_artifact(self):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            with self.assertRaises(PolicyError):
                requalify_run(root / "missing-source", {"schema_version": 999}, root / "derived")
            self.assertFalse((root / "derived").exists())


class ScoreCompatibility(unittest.TestCase):
    def test_baseline_score_matches_legacy_on_representative_evidence_combinations(self):
        claims = [
            ("entity_type:studio_or_agency", "studio_or_agency"),
            ("entity_type:client_services", "client_services"),
            ("service:react", "react"),
            ("service:web_app", "web_app"),
            ("service:custom_software", "custom_software"),
            ("location:us", "US"),
            ("size:employees", 20),
            ("negative:staff_augmentation", "staff_augmentation"),
            ("company_type:saas_vendor_signal", "free_trial"),
            ("company_type:saas_vendor_signal", "pricing"),
            ("company_type:saas_vendor_signal", "demo"),
        ]
        # Deterministic masks cover presence/absence, qualification caps and exclusions.
        for mask in range(0, 1 << len(claims), 19):
            evidence = [ev(kind, value) for i, (kind, value) in enumerate(claims) if mask & (1 << i)]
            old = legacy.score_company(evidence, [], homepage_ok=True)
            new = score_company(evidence, [], homepage_ok=True)
            with self.subTest(mask=mask):
                self.assertEqual((new.total, new.tier, new.company_type),
                                 (old.total, old.tier, old.company_type))
                self.assertEqual(new.hard_exclusions, old.hard_exclusions)


if __name__ == "__main__":
    unittest.main()
