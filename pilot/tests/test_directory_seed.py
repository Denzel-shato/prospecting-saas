"""Directory seed ingestion tests. Fictional data only; no network, no directory is fetched."""

from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import tests.util as u
from vm1 import directory_seed as ds
from vm1.canon import canonical_domain
from vm1.cli import main as cli_main
from vm1.discovery import AUTOMATED, MANUAL, DiscoveryBlocked, build_adapters
from vm1.evidence import apply_discovery_record
from vm1.fixture import build_synthetic
from vm1.guard import PaidApiBlocked
from vm1.pipeline import RunConfig, run_pipeline
from vm1.policy import baseline_policy
from vm1.prequalify import prequalify
from vm1.report import verdict

FIX = u.ROOT / "fixtures" / "directory_seed"
FIX_CATALOG = FIX / "fixture_catalog.json"
FIX_CSV = FIX / "fictional_smoke_seed.csv"
NOW = "2026-11-22T00:00:00+00:00"


def write(tmp: str, name: str, text: str) -> Path:
    p = Path(tmp) / name
    p.write_text(text, encoding="utf-8")
    return p


class CatalogTests(unittest.TestCase):
    def test_real_catalog_has_19_sources_and_no_automated_directory(self):
        raw = json.loads(ds.DEFAULT_CATALOG.read_text(encoding="utf-8"))
        self.assertEqual(len(raw["existing_automated_sources"]), 3)
        catalog = ds.load_catalog()
        self.assertEqual(len(catalog), 16)
        self.assertEqual(len(raw["existing_automated_sources"]) + len(catalog), 19)
        self.assertEqual(ds.AUTOMATED_DIRECTORY_ADAPTERS, {})
        for src in catalog.values():
            self.assertEqual((src.mode, src.automated_adapter, src.automated_access_verified),
                             ("manual_seed_only", False, False), src.id)

    def test_vercel_and_netlify_blockers_are_recorded(self):
        catalog = ds.load_catalog()
        for sid in ("vercel_solution_partners", "netlify_agency_directory"):
            review = catalog[sid].access_review
            self.assertEqual(review["outcome"], "manual_only")
            self.assertFalse(review["documented_api_found"])
            self.assertFalse(review["robots_txt_verified"])
            self.assertTrue(review["findings"] and review["evidence_urls"] and review["unblock_requires"])

    def test_unverified_automated_claim_fails_closed(self):
        raw = json.loads(FIX_CATALOG.read_text(encoding="utf-8"))
        raw["proposed_directory_sources"][0].update(automated_adapter=True)
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ds.CatalogError):
                ds.load_catalog(write(t, "c.json", json.dumps(raw)))
            raw["proposed_directory_sources"][0].update(automated_access_verified=True, mode="api",
                                                        access_review={"outcome": "api"})
            with self.assertRaises(ds.CatalogError):  # verified on paper but no adapter is registered
                ds.load_catalog(write(t, "c2.json", json.dumps(raw)))

    def test_catalog_rejects_duplicate_ids_and_bad_urls(self):
        raw = json.loads(FIX_CATALOG.read_text(encoding="utf-8"))
        dup = dict(raw, proposed_directory_sources=raw["proposed_directory_sources"] * 2)
        bad = json.loads(FIX_CATALOG.read_text(encoding="utf-8"))
        bad["proposed_directory_sources"][0]["url"] = "http://directory.example/"
        with tempfile.TemporaryDirectory() as t:
            for payload in (dup, bad):
                with self.assertRaises(ds.CatalogError):
                    ds.load_catalog(write(t, "c.json", json.dumps(payload)))

    def test_catalog_directory_name_is_not_an_automated_source(self):
        for name in ("vercel_solution_partners", "netlify_agency_directory"):
            with self.assertRaises(DiscoveryBlocked) as cm:
                build_adapters([name])
            self.assertIn("manual_seed_only", str(cm.exception))
            self.assertIn("--directory-seed-csv", str(cm.exception))
        with self.assertRaises(PaidApiBlocked):
            build_adapters(["exa"])


class IngestTests(unittest.TestCase):
    def setUp(self):
        self.catalog = ds.load_catalog(FIX_CATALOG)

    def rows(self, text: str):
        with tempfile.TemporaryDirectory() as t:
            return ds.read_seed_rows(write(t, "s.csv", text))

    def test_fixture_ingest_attribution_dedupe_and_rejections(self):
        res = ds.ingest_rows(ds.read_seed_rows(FIX_CSV), self.catalog, retrieved_at=NOW)
        self.assertEqual(res.stats, {"rows": 6, "invalid_rows": 3, "valid_rows": 3,
                                     "duplicate_domain_rows": 1, "unique_domains": 2})
        self.assertEqual(sorted(r["reason"] for r in res.rejected),
                         ["directory_own_domain", "missing_name_or_url", "non_first_party_domain"])
        bright = next(c for c in res.candidates if c.domain == "brightlane-studio.example")
        # first listing wins name/url, exactly as supplied; the second listing stays in the occurrence log
        self.assertEqual((bright.name, bright.url), ("Brightlane Studio", "https://brightlane-studio.example/"))
        occ = bright.attrs["seed_occurrences"]
        self.assertEqual([o["directory_id"] for o in occ], ["example_directory_a", "example_directory_b"])
        self.assertEqual(occ[0]["directory_name"], "Example Directory A")
        self.assertEqual(occ[0]["directory_url"], "https://directory.example/partners")
        self.assertEqual(occ[1]["listed_url"], "https://www.BRIGHTLANE-studio.example/about?utm_source=x")
        self.assertEqual(occ[1]["listed_name"], "Brightlane Studio (second listing)")
        self.assertEqual(len(res.occurrences), 3)
        self.assertEqual(res.by_directory["example_directory_b"]["duplicate_domain_rows"], 1)
        self.assertEqual(res.by_directory["example_directory_a"]["new_domains"], 2)

    def test_default_listing_url_is_the_directory_url(self):
        res = ds.ingest_rows(self.rows("name,url\nNorthwind UI,https://northwind-ui.example/\n"), self.catalog,
                             default_directory="example_directory_a", retrieved_at=NOW)
        cand = res.candidates[0]
        self.assertEqual(cand.source_url, "https://directory.example/partners")
        self.assertEqual(cand.attrs["seed_directory"]["name"], "Example Directory A")

    def test_bare_domains_and_www_dedupe_to_one_company(self):
        res = ds.ingest_rows(self.rows("name,url\nA,Acme-Studio.example\nA again,https://www.acme-studio.example/x\n"),
                             self.catalog, default_directory="example_directory_a", retrieved_at=NOW)
        self.assertEqual(len(res.candidates), 1)
        self.assertEqual(res.candidates[0].domain, canonical_domain("acme-studio.example"))
        self.assertEqual(res.stats["duplicate_domain_rows"], 1)

    def test_directory_resolution_failures(self):
        res = ds.ingest_rows(self.rows("name,url,directory_id\nA,https://a.example/,nope\nB,https://b.example/,\n"),
                             self.catalog, retrieved_at=NOW)
        self.assertEqual(sorted(r["reason"] for r in res.rejected), ["no_directory_id", "unknown_directory_id"])
        self.assertEqual(res.candidates, [])
        with self.assertRaises(DiscoveryBlocked):
            ds.ingest_rows([], self.catalog, default_directory="missing")

    def test_listing_url_must_be_on_the_attributed_directory(self):
        res = ds.ingest_rows(
            self.rows("name,url,listing_url\nA,https://a.example/,https://elsewhere.example/p\n"
                      "B,https://b.example/,https://directory.example/partners/b\n"),
            self.catalog, default_directory="example_directory_a", retrieved_at=NOW)
        self.assertEqual([r["reason"] for r in res.rejected], ["listing_url_not_on_directory"])
        self.assertEqual([c.domain for c in res.candidates], ["b.example"])

    def test_missing_columns_and_file_block(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(DiscoveryBlocked):
                ds.read_seed_rows(write(t, "bad.csv", "company,site\nA,https://a.example/\n"))
            with self.assertRaises(DiscoveryBlocked):
                ds.read_seed_rows(Path(t) / "missing.csv")

    def test_seeds_are_manual_and_carry_no_qualification_signal(self):
        res = ds.ingest_rows(ds.read_seed_rows(FIX_CSV), self.catalog, retrieved_at=NOW)
        for c in res.candidates:
            self.assertEqual(c.discovery_method, MANUAL)
            self.assertNotEqual(c.discovery_method, AUTOMATED)
            self.assertEqual(prequalify(c.attrs, baseline_policy()), (0, []))  # directory listing never ranks
            self.assertEqual(apply_discovery_record(c.domain, c, []), [])  # and never becomes evidence


class AdapterAndPipelineSmokeTests(unittest.TestCase):
    def adapter(self):
        return ds.DirectorySeedAdapter(FIX_CSV, catalog_path=FIX_CATALOG)

    def test_adapter_requires_zero_cost_and_reports_blockers(self):
        self.assertEqual(self.adapter().cost_class, "free_keyless")
        with self.assertRaises(DiscoveryBlocked):
            ds.DirectorySeedAdapter(Path("/nonexistent/seed.csv"), directory_id="x", catalog_path=FIX_CATALOG).discover()
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(DiscoveryBlocked) as cm:  # no attribution at all: block, never guess
                ds.DirectorySeedAdapter(write(t, "s.csv", "name,url\nA,https://a.example/\n"),
                                        catalog_path=FIX_CATALOG).discover()
            self.assertIn("directory_id", str(cm.exception))

    def test_fixture_smoke_flows_into_first_party_qualification_as_manual(self):
        _, fetcher = build_synthetic(u.WORLD)
        adapter = self.adapter()
        with tempfile.TemporaryDirectory() as t:
            run = run_pipeline(RunConfig(icp=baseline_policy(), out_dir=Path(t), mode="synthetic_fixture"),
                               [adapter], fetcher)
            manifest = run["manifest"]
            counts = manifest["counts"]
            self.assertEqual((counts["raw_automated"], counts["selected_automated"]), (0, 0))
            self.assertEqual((counts["selected_manual"], counts["selected_manual_directory_seed"]), (2, 2))
            self.assertEqual(counts["raw_manual_directory_seed"], 2)
            self.assertEqual(counts["selected_synthetic"], 0)
            self.assertTrue(manifest["directory_seed"]["excluded_from_autonomous_metrics"])
            self.assertEqual(manifest["discovery_status"][0]["yield"]["duplicate_domain_rows"], 1)
            by = {c["domain"]: c for c in run["companies"]}
            self.assertEqual(set(by), {"brightlane-studio.example", "northwind-ui.example"})
            bright = by["brightlane-studio.example"]
            self.assertEqual(bright["discovery"]["method"], "manual")
            self.assertEqual(bright["discovery"]["directory"],
                             {"id": "example_directory_a", "name": "Example Directory A",
                              "url": "https://directory.example/partners"})
            self.assertEqual([o["directory_id"] for o in bright["discovery"]["directory_occurrences"]],
                             ["example_directory_a", "example_directory_b"])
            # existing first-party qualification ran on the company's own pages, not on the directory listing
            self.assertTrue(bright["homepage"]["ok"])
            self.assertTrue(bright["evidence"])
            self.assertTrue(all(e["source_type"] != "discovery_record" for e in bright["evidence"]))
            self.assertTrue(all("directory" not in e["source_url"] for e in bright["evidence"]))
            self.assertIn("tier", bright)
            self.assertNotIn("directory.example", " ".join(r["url"] for r in fetcher.log))
            log = json.loads((Path(run["run_dir"]) / "directory_seed_occurrences.json").read_text())
            self.assertEqual(len(log), 3)
            self.assertEqual(manifest["paid_api_spend_usd"], 0.0)

    def test_manual_directory_run_is_reported_as_qualification_only(self):
        manifest = {"mode": "live", "counts": {"selected_manual": 4, "selected_automated": 0},
                    "discovery_status": [{"adapter": "directory_seed"}]}
        self.assertIn("MANUAL QUALIFICATION RUN", verdict({"manifest": manifest}, {})[0])
        mixed = {"mode": "live", "counts": {"selected_manual": 4, "selected_automated": 0, "raw_automated": 0},
                 "discovery_status": [{"adapter": "directory_seed"}, {"adapter": "drupal_org"}]}
        self.assertIn("NO-GO", verdict({"manifest": mixed}, {})[0])

    def test_cross_adapter_duplicate_keeps_first_and_logs_source(self):
        from vm1.discovery import Candidate
        from vm1.pipeline import dedup
        auto = Candidate(name="Auto", url="https://brightlane-studio.example/", discovery_method=AUTOMATED,
                         source="drupal_org", source_id="1")
        seeded = self.adapter().discover()
        kept, rejected, _ = dedup([auto] + seeded)
        self.assertEqual(kept[0].discovery_method, AUTOMATED)  # an independent find is never relabelled manual
        dup = next(r for r in rejected if r["domain"] == "brightlane-studio.example")
        self.assertEqual((dup["source"], dup["source_id"]), ("directory_seed", "example_directory_a"))


class CliTests(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli_main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_seed_directory_writes_reviewable_artifacts_offline(self):
        with tempfile.TemporaryDirectory() as t:
            code, out, _ = self.run_cli("seed-directory", "--csv", str(FIX_CSV), "--source-catalog", str(FIX_CATALOG),
                                        "--out", t)
            self.assertEqual(code, 0, out)
            files = {p.name for p in Path(t).iterdir()}
            self.assertEqual(files, {"directory_seeds.json", "directory_seed_occurrences.json",
                                     "directory_seed_rejected.json", "directory_seed_summary.json"})
            seeds = json.loads((Path(t) / "directory_seeds.json").read_text())
            self.assertEqual({s["domain"] for s in seeds}, {"brightlane-studio.example", "northwind-ui.example"})
            self.assertEqual(next(s for s in seeds if s["domain"] == "brightlane-studio.example")["directories"],
                             ["example_directory_a", "example_directory_b"])

    def test_seed_directory_blocks_unknown_directory(self):
        with tempfile.TemporaryDirectory() as t:
            csv_path = write(t, "s.csv", "name,url\nA,https://a.example/\n")
            code, _, err = self.run_cli("seed-directory", "--csv", str(csv_path), "--directory-source", "nope",
                                        "--out", str(Path(t) / "o"))
            self.assertEqual(code, 3)
            self.assertIn("unknown directory id", err)

    def test_run_refuses_a_manual_only_directory_as_a_source(self):
        code, _, err = self.run_cli("run", "--sources", "vercel_solution_partners", "--out", tempfile.gettempdir())
        self.assertEqual(code, 3)
        self.assertIn("manual_seed_only", err)


if __name__ == "__main__":
    unittest.main()
