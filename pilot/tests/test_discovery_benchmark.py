"""Discovery benchmark: determinism, label/tier separation, honesty banners, import of a local pool."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from vm1 import discovery_benchmark as bench
from vm1.cli import main
from vm1.policy import load_policy

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures" / "discovery_benchmark"
POLICY = load_policy(ROOT / "icp" / "frontend-studio-worldwide.json")


def rows(*specs, method="automated", source="pickanagency"):
    out = []
    for dom, tagline, services in specs:
        out.append({"domain": dom, "name": dom, "source": source, "method": method,
                    "attrs": {"directory_tagline": tagline, "directory_services": services,
                              "directory_service_hint": True}})
    return out


def run_cli(*argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = main(list(argv))
    return code, buf.getvalue()


class StatisticsTests(unittest.TestCase):
    def test_wilson_interval_is_sane(self):
        self.assertIsNone(bench.wilson(0, 0))
        lo, hi = bench.wilson(5, 10)
        self.assertTrue(0.2 < lo < 0.5 < hi < 0.8)
        self.assertEqual(bench.wilson(0, 3)[0], 0.0)
        self.assertEqual(bench.wilson(3, 3)[1], 1.0)

    def test_human_precision_uses_only_labelled_rows_and_excludes_unsure(self):
        labels = {"a.example": {"label": "relevant"}, "b.example": {"label": "not_relevant"},
                  "c.example": {"label": "unsure"}}
        h = bench.human_stats(["a.example", "b.example", "c.example", "d.example"], labels)
        self.assertEqual((h["labeled"], h["precision"], h["precision_denominator"], h["unsure"]), (3, 0.5, 2, 1))
        self.assertEqual(h["label_coverage"], 0.75)
        none = bench.human_stats(["x.example"], {})
        self.assertIsNone(none["precision"])
        self.assertEqual(none["labeled"], 0)


class LabelsTests(unittest.TestCase):
    def write(self, text):
        d = tempfile.mkdtemp()
        p = Path(d) / "labels.csv"
        p.write_text(text, encoding="utf-8")
        return p

    def test_aliases_canonical_domains_conflicts_and_invalid_rows(self):
        p = self.write("domain,label\nhttps://www.A.example/x,y\nb.example,N\nc.example,relevant\nc.example,not_relevant\n"
                       "d.example,maybe\n,relevant\n")
        labels, info = bench.read_labels(p)
        self.assertEqual({d: v["label"] for d, v in labels.items()}, {"a.example": "relevant", "b.example": "not_relevant"})
        self.assertEqual(info["conflicting_domains"], ["c.example"])
        self.assertEqual(len(info["invalid"]), 2)

    def test_missing_columns_fail_closed(self):
        with self.assertRaises(ValueError):
            bench.read_labels(self.write("domain,verdict\na.example,y\n"))
        self.assertEqual(bench.read_labels(None)[0], {})


class TierTests(unittest.TestCase):
    def tier(self, tagline="", services=(), **attrs):
        return bench.record_tier({"directory_tagline": tagline, "directory_services": list(services), **attrs}, POLICY)

    def test_tiers(self):
        self.assertEqual(self.tier("Custom software development company"), "record_target_like")
        self.assertEqual(self.tier("Social media growth agency"), "record_negative")
        self.assertEqual(self.tier(services=["Consulting", "Web Design"]), "record_generic")
        self.assertEqual(self.tier(), "record_no_text")
        self.assertEqual(self.tier("Custom software development", listed_on_exchange=True), "record_mixed")
        self.assertEqual(self.tier("A platform", directory_vendor_hint=True), "record_negative")

    def test_tiers_are_never_called_labels(self):
        self.assertIn("NOT human labels", bench.TIER_NOTE)
        self.assertTrue(all(t.startswith("record_") for t in bench.TIERS))


class BenchmarkTests(unittest.TestCase):
    def arms(self):
        a = rows(("one.example", "Custom software development company", ["Software Development"]),
                 ("two.example", "Social media growth agency", ["SEO"]),
                 ("one.example", "dup", []))
        b = rows(("one.example", "Custom software development company", ["Software Development"]),
                 ("three.example", "Product development studio", ["Software Development"]))
        return {"A": a, "B": b}

    def test_unique_coverage_overlap_and_duplicates(self):
        res = bench.run_benchmark(self.arms(), POLICY)
        self.assertEqual(res["arms"]["A"]["rows"], 3)
        self.assertEqual(res["arms"]["A"]["unique_domains"], 2)
        self.assertEqual(res["arms"]["A"]["duplicate_rows"], 1)
        self.assertEqual(res["cross_arm"], {"union_unique_domains": 3, "unique_to_arm": {"A": 1, "B": 1},
                                            "pairwise_overlap": {"A&B": 1}})

    def test_without_labels_precision_is_not_measured_and_says_so(self):
        res = bench.run_benchmark(self.arms(), POLICY)
        self.assertTrue(any("NO HUMAN LABELS" in n for n in res["notices"]))
        self.assertIsNone(res["arms"]["A"]["human"]["precision"])
        self.assertIsNone(res["arms"]["A"]["yield_per_request"]["human_relevant_per_request"])
        self.assertIn("NOT MEASURED", bench.render_markdown(res))

    def test_labels_drive_precision_and_unmatched_labels_are_reported(self):
        labels = {"one.example": {"label": "relevant"}, "two.example": {"label": "not_relevant"},
                  "ghost.example": {"label": "relevant"}}
        res = bench.run_benchmark(self.arms(), POLICY, labels)
        a = res["arms"]["A"]
        self.assertEqual((a["human"]["relevant"], a["human"]["not_relevant"], a["human"]["precision"]), (1, 1, 0.5))
        self.assertTrue(any("ghost.example" in n for n in res["notices"]))
        self.assertTrue(any("cover" in n for n in res["notices"]))
        self.assertEqual(a["tier_calibration_human"]["record_target_like"]["precision"], 1.0)
        self.assertEqual(a["tier_calibration_human"]["record_negative"]["precision"], 0.0)

    def test_synthetic_input_is_flagged_even_with_labels(self):
        synth = {"S": rows(("a.example", "Custom software development company", []))}
        res = bench.run_benchmark(synth, POLICY, {"a.example": {"label": "relevant"}})
        self.assertTrue(res["synthetic_input"])
        self.assertIn("not a real-world improvement", res["notices"][0])
        real = {"R": rows(("acme-studio.com", "Custom software development company", []))}
        self.assertFalse(bench.run_benchmark(real, POLICY)["synthetic_input"])
        self.assertTrue(bench.run_benchmark(real, POLICY, force_synthetic=True)["synthetic_input"])

    def test_deterministic_and_input_order_independent_for_unique_rows(self):
        # Duplicate domains follow the pipeline's first-row-wins rule, so order independence is asserted for unique rows.
        arms = {k: [r for r in v if r["attrs"]["directory_tagline"] != "dup"] for k, v in self.arms().items()}
        first = json.dumps(bench.run_benchmark(arms, POLICY), sort_keys=True)
        self.assertEqual(first, json.dumps(bench.run_benchmark(arms, POLICY), sort_keys=True))
        reversed_arms = {k: list(reversed(v)) for k, v in arms.items()}
        self.assertEqual(first, json.dumps(bench.run_benchmark(reversed_arms, POLICY), sort_keys=True))

    def test_per_query_attribution_and_exact_requests_from_manifest(self):
        r = rows(("one.example", "Custom software development company", []))
        r[0]["attrs"]["directory_discovery_queries"] = [{"service": "Software Development"}, {"q": "custom software"}]
        r[0]["attrs"]["directory_discovery_query"] = {"service": "Software Development"}
        manifest = {"discovery_status": [{"adapter": "pickanagency", "yield": {"per_query": [{}, {}, {}]}}]}
        res = bench.run_benchmark({"A": r}, POLICY, manifests={"A": manifest})
        a = res["arms"]["A"]
        self.assertEqual(a["by_query"]["q=custom software"], {**a["by_query"]["q=custom software"], "returned_unique": 1,
                                                              "first_seen_here": 0})
        self.assertEqual(a["by_query"]["service=Software Development"]["first_seen_here"], 1)
        self.assertEqual((a["yield_per_request"]["requests"], a["yield_per_request"]["requests_exact"]), (3, True))

    def test_pool_json_is_not_modified_and_loader_accepts_flat_attrs_and_run_candidates(self):
        d = Path(tempfile.mkdtemp())
        p = d / "pool.json"
        p.write_text(json.dumps({"candidates": [
            {"name": "Flat", "website": "https://www.flat.example", "tagline": "Custom software", "services": ["Software Development"]},
            {"name": "Run", "url": "https://run.example", "domain": "run.example", "source": "wikidata",
             "discovery_method": "automated", "attrs": {"description": "software company"}},
            {"name": "NoSite"}]}), encoding="utf-8")
        before = p.read_bytes()
        got = bench.load_pool(p)
        self.assertEqual([r["domain"] for r in got], ["flat.example", "run.example"])
        self.assertEqual(got[0]["attrs"]["directory_services"], ["Software Development"])
        self.assertEqual(p.read_bytes(), before)


class CliTests(unittest.TestCase):
    def test_cli_runs_on_fictional_fixtures_and_writes_deterministic_outputs(self):
        outs = []
        for _ in range(2):
            d = tempfile.mkdtemp()
            code, text = run_cli("discovery-benchmark", "--pool", f"legacy={FIX / 'fictional_legacy.json'}",
                                 "--pool", f"complementary={FIX / 'fictional_complementary.json'}",
                                 "--labels", str(FIX / "fictional_labels.csv"), "--out", d, "--labels-template")
            self.assertEqual(code, 0)
            self.assertIn("SYNTHETIC/FICTIONAL INPUT", text)
            outs.append(((Path(d) / "discovery_benchmark.json").read_text(), (Path(d) / "discovery_benchmark.md").read_text()))
            self.assertTrue((Path(d) / "labels_template.csv").exists())
        self.assertEqual(outs[0], outs[1])
        res = json.loads(outs[0][0])
        self.assertEqual(res["cross_arm"]["union_unique_domains"], 9)

    def test_labels_template_is_blank_for_humans(self):
        d = Path(tempfile.mkdtemp()) / "t.csv"
        n = bench.labels_template(d, {"A": rows(("a.example", "x", []))})
        self.assertEqual(n, 1)
        self.assertEqual(d.read_text().splitlines()[1], "a.example,a.example,pickanagency,,,,")

    def test_bad_inputs_fail_closed_with_exit_2(self):
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            code, _ = run_cli("discovery-benchmark", "--pool", "x=/nonexistent.json", "--out", tempfile.mkdtemp())
        self.assertEqual(code, 2)
        with self.assertRaises(SystemExit):
            run_cli("discovery-benchmark", "--pool", "nopath", "--out", tempfile.mkdtemp())

    def test_benchmark_module_never_touches_the_network(self):
        src = (ROOT / "vm1" / "discovery_benchmark.py").read_text()
        for banned in ("socket", "urllib.request", "http.client", "ApiClient", "PinnedTransport"):
            self.assertNotIn(banned, src)


if __name__ == "__main__":
    unittest.main()
