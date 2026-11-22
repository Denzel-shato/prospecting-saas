"""Issue #5 pipeline-level ICP integration tests (fictional data; not lead quality)."""

from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import tests.util as u
from vm1.cli import main as cli_main
from vm1.fixture import build_synthetic
from vm1.pipeline import RunConfig, run_pipeline
from vm1.policy import PolicyError, baseline_policy, load_policy


def alternative_policy():
    raw = copy.deepcopy(baseline_policy().to_dict())
    raw["id"] = "storefront-only-test"
    raw["policy_version"] = "1.0.1"
    raw["target_type"]["id"] = "storefront_business"
    raw["target_type"]["label"] = "Storefront business"
    raw["target_type"]["short_label"] = "Storefront"
    raw["target_type"]["identity"] = [{
        "claim": "company_type:storefront_signal",
        "strength": "strong",
        "points": 20,
        "rule": "storefront identity",
        "min_distinct_values": 2,
    }]
    raw["prequalify"] = {"positive_terms": ["online store", "ecommerce"],
                         "negative_terms": ["software development agency"]}
    raw["drafts"]["enabled"] = False
    return load_policy(raw)


class PipelinePolicyWiring(unittest.TestCase):
    def test_custom_icp_changes_verdict_without_changing_pages_or_company(self):
        with tempfile.TemporaryDirectory() as t:
            base_adapters, base_fetcher = build_synthetic(u.WORLD)
            baseline = run_pipeline(
                RunConfig(icp=baseline_policy(), out_dir=Path(t) / "baseline",
                          mode="synthetic_fixture"),
                base_adapters, base_fetcher,
            )
            other_adapters, other_fetcher = build_synthetic(u.WORLD)
            alt = alternative_policy()
            other = run_pipeline(
                RunConfig(icp=alt, out_dir=Path(t) / "other",
                          mode="synthetic_fixture"),
                other_adapters, other_fetcher,
            )
            x = {c["domain"]: c for c in baseline["companies"]}
            y = {c["domain"]: c for c in other["companies"]}
            dom = "brightlane-studio.example"
            self.assertIn(dom, x)
            self.assertIn(dom, y)
            self.assertEqual(x[dom]["company_type"], "agency_studio")
            self.assertNotEqual(y[dom]["company_type"], "agency_studio")
            self.assertEqual(x[dom]["discovery"]["source_id"], y[dom]["discovery"]["source_id"])
            self.assertEqual(other["manifest"]["icp_id"], alt.id)
            self.assertEqual(other["manifest"]["policy_version"], alt.policy_version)
            self.assertEqual(other["manifest"]["policy_digest"], alt.digest)
            self.assertEqual(other["manifest"]["paid_api_spend_usd"], 0.0)
            self.assertEqual(other["drafts"], [], "non-baseline draft template must stay disabled")

    def test_invalid_policy_fails_before_discovery(self):
        with tempfile.TemporaryDirectory() as t:
            invalid = {"schema_version": 1, "id": "bad", "unknown_field": True}
            with self.assertRaises(PolicyError):
                run_pipeline(RunConfig(icp=invalid, out_dir=Path(t), mode="synthetic_fixture"),
                             *build_synthetic(u.WORLD))
            self.assertEqual(list(Path(t).iterdir()), [], "invalid policy must cause no work or output")

    def test_validate_icp_cli(self):
        with tempfile.TemporaryDirectory() as t:
            valid = Path(t) / "valid.json"
            invalid = Path(t) / "invalid.json"
            valid.write_text(json.dumps(alternative_policy().to_dict()), encoding="utf-8")
            invalid.write_text('{"schema_version": 999, "id": "bad"}', encoding="utf-8")
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(cli_main(["validate-icp", str(valid)]), 0)
            self.assertIn("storefront-only-test", out.getvalue())
            err = io.StringIO()
            with redirect_stderr(err):
                self.assertEqual(cli_main(["validate-icp", str(invalid)]), 2)
            self.assertIn("INVALID ICP", err.getvalue())


if __name__ == "__main__":
    unittest.main()
