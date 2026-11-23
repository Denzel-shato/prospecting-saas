"""Engine #2 (research backfill): failed research attempts are replaced from the ranked pool within a hard
budget; qualification, provenance and determinism are unchanged. Offline, fictional hosts (.example)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.util import ROOT
from vm1 import cli
from vm1.discovery import Adapter, Candidate
from vm1.fetch import PoliteFetcher
from vm1.fixture import FakeTransport
from vm1.pipeline import (ASSESSED, EXCLUDED_BY_EVIDENCE, INACCESSIBLE, NOT_RESEARCHABLE_ROBOTS, RunConfig,
                          default_research_budget, prioritize_pool, research_company, research_outcome,
                          run_pipeline)
from vm1.policy import load_policy
from vm1.report import write_report
from vm1.score import EXCLUDED, NOT_RESEARCHABLE

POLICY = load_policy(ROOT / "icp" / "frontend-studio.json")
PAGES = ROOT / "fixtures" / "synthetic"

# Host behaviours. quiet_home is a thin first-party page that scores "weak" (still ASSESSED);
# megacorp_home is an enterprise page the policy excludes on evidence.
OK = {"pages": {"/": {"file": "pages/quiet_home.html"}}}
FORBIDDEN = {"pages": {"/": {"status": 403}}}
ROBOTS = {"robots": "User-agent: *\nDisallow: /", "pages": {"/": {"file": "pages/quiet_home.html"}}}
ENTERPRISE = {"pages": {"/": {"file": "pages/megacorp_home.html"}}}

# Failures outrank healthy records (priority 4 vs 3) so every one of them lands in the initial wave.
FAIL_ATTRS = {"description": "web development agency", "employees": 12}
OK_ATTRS = {"description": "web development agency"}


class ListAdapter(Adapter):
    name = "list"

    def __init__(self, candidates):
        self.candidates = candidates
        self.calls = 0

    def discover(self):
        self.calls += 1
        return list(self.candidates)


def world(spec):
    """spec: {host: behaviour}. Returns (candidates, fetcher, transport)."""
    hosts = dict(spec)
    transport = FakeTransport({"hosts": hosts}, PAGES)
    fetcher = PoliteFetcher(transport, lambda h: ["1.1.1.1"] if h in hosts else [], min_delay=0.0,
                            sleep=lambda s: None, now=lambda: "2026-11-23T00:00:00+00:00")
    return fetcher, transport


def cand(host, attrs, source_id=""):
    return Candidate(name=host.split(".")[0].title(), url=f"https://{host}/", discovery_method="synthetic_fixture",
                     source="list", source_id=source_id or host, source_url=f"https://list.example/{host}",
                     attrs=dict(attrs))


def run(spec, cands, **cfg):
    fetcher, transport = world(spec)
    adapter = ListAdapter(cands)
    out = tempfile.TemporaryDirectory()
    unittest.addModuleCleanup(out.cleanup)
    result = run_pipeline(RunConfig(icp=POLICY, out_dir=Path(out.name), mode="synthetic_fixture", **cfg),
                          [adapter], fetcher)
    result["_tmp"], result["_transport"], result["_adapter"] = out, transport, adapter
    return result


def domains(result):
    return [c["domain"] for c in result["companies"]]


class BackfillReplacesFailedAttempts(unittest.TestCase):
    SPEC = {"f403.example": FORBIDDEN, "frobots.example": ROBOTS, "fbig.example": ENTERPRISE,
            **{f"ok{i}.example": OK for i in range(1, 6)}}

    @staticmethod
    def pool():
        cands = [cand(h, FAIL_ATTRS) for h in ("f403.example", "frobots.example", "fbig.example")]
        return cands + [cand(f"ok{i}.example", OK_ATTRS) for i in range(1, 6)]

    def result(self, **cfg):
        return run(self.SPEC, self.pool(), max_candidates=3, max_research=6, **cfg)

    def test_inaccessible_robots_and_excluded_attempts_are_replaced_in_priority_order(self):
        r = self.result()
        sel = {c["domain"]: c["research_selection"] for c in r["companies"]}
        self.assertEqual(sorted(domains(r)[:3]), ["f403.example", "fbig.example", "frobots.example"])
        # backfills are the best-ranked healthy candidates, in the pool's own priority order
        ranked, _ = prioritize_pool(self.pool(), "vm1-pilot-1", POLICY)
        healthy = [x.candidate.domain for x in ranked if x.candidate.domain.startswith("ok")]
        self.assertEqual(domains(r)[3:], healthy[:3])
        self.assertEqual(sel["f403.example"]["outcome"], INACCESSIBLE)
        self.assertEqual(sel["frobots.example"]["outcome"], NOT_RESEARCHABLE_ROBOTS)
        self.assertEqual(sel["fbig.example"]["outcome"], EXCLUDED_BY_EVIDENCE)
        backfills = [c for c in r["companies"] if c["research_selection"]["wave"] == "backfill"]
        self.assertEqual(len(backfills), 3)
        self.assertTrue(all(c["research_selection"]["outcome"] == ASSESSED for c in backfills))
        # each backfill names the failed attempt it replaces, oldest failure first
        self.assertEqual([c["research_selection"]["backfill_for"] for c in backfills], domains(r)[:3])
        plan = r["manifest"]["research_plan"]
        self.assertEqual((plan["assessed"], plan["attempted"], plan["backfill_attempted"], plan["stop_reason"]),
                         (3, 6, 3, "target_met"))
        self.assertEqual(plan["outcomes"], {"assessed": 3, "inaccessible": 1, "not_researchable": 1, "excluded": 1})
        self.assertEqual(plan["target_shortfall"], 0)

    def test_without_backfill_the_same_run_would_assess_nothing(self):
        """The defect: a fixed pre-selection of 3 spends every slot on the three failures."""
        r = run(self.SPEC, [cand(h, FAIL_ATTRS) for h in ("f403.example", "frobots.example", "fbig.example")] +
                [cand(f"ok{i}.example", OK_ATTRS) for i in range(1, 6)], max_candidates=3, max_research=3)
        self.assertEqual(r["manifest"]["research_plan"]["assessed"], 0)
        self.assertEqual(r["manifest"]["research_plan"]["stop_reason"], "budget_exhausted")

    def test_weak_companies_are_assessed_and_never_trigger_backfill(self):
        spec = {f"w{i}.example": OK for i in range(5)}
        r = run(spec, [cand(h, OK_ATTRS) for h in spec], max_candidates=2)
        self.assertEqual({c["tier"] for c in r["companies"]}, {"weak"})
        plan = r["manifest"]["research_plan"]
        self.assertEqual((plan["attempted"], plan["backfill_attempted"], plan["stop_reason"]), (2, 0, "target_met"))

    def test_skipped_records_keep_rank_priority_provenance_and_reason(self):
        r = self.result()
        self.assertEqual(len(r["skipped"]), 2)
        saved = json.loads((Path(r["run_dir"]) / "skipped.json").read_text())
        self.assertEqual(saved, r["skipped"])
        self.assertEqual([s["pool_rank"] for s in saved], [7, 8])
        s = saved[0]
        self.assertEqual((s["source"], s["method"], s["priority"]), ("list", "synthetic_fixture", 3))
        self.assertTrue(s["source_url"].startswith("https://list.example/"))
        self.assertIn("target", s["skipped_reason"])
        self.assertEqual(r["manifest"]["counts"]["researched"] + r["manifest"]["counts"]["skipped_not_researched"], 8)

    def test_candidates_json_lists_exactly_the_researched_companies(self):
        r = self.result()
        listed = [c["domain"] for c in json.loads((Path(r["run_dir"]) / "candidates.json").read_text())]
        self.assertEqual(listed, domains(r))
        self.assertEqual(r["manifest"]["counts"]["selected"], len(domains(r)))
        self.assertEqual(r["manifest"]["counts"]["selected_synthetic"], len(domains(r)))


class BudgetIsAHardCap(unittest.TestCase):
    def test_all_403_pool_stops_at_max_research_and_never_retries_or_bypasses(self):
        spec = {f"d{i}.example": FORBIDDEN for i in range(10)}
        r = run(spec, [cand(h, OK_ATTRS) for h in spec], max_candidates=3, max_research=5)
        plan = r["manifest"]["research_plan"]
        self.assertEqual((plan["attempted"], plan["assessed"], plan["stop_reason"], plan["target_shortfall"]),
                         (5, 0, "budget_exhausted", 3))
        self.assertEqual(plan["outcomes"]["inaccessible"], 5)
        self.assertEqual(len(r["skipped"]), 5)
        homepage_hits = [url for _, url in r["_transport"].requests if url.rstrip("/").count("/") == 2]
        self.assertEqual(len(homepage_hits), 5, "exactly one homepage request per attempt, no retry on 403")
        self.assertEqual(len({url for url in homepage_hits}), 5)
        self.assertEqual({c["homepage"]["status"] for c in r["companies"]}, {403})

    def test_pool_smaller_than_target_researches_everything_once(self):
        spec = {"a.example": FORBIDDEN, "b.example": OK}
        r = run(spec, [cand(h, OK_ATTRS) for h in spec], max_candidates=10)
        plan = r["manifest"]["research_plan"]
        self.assertEqual((plan["attempted"], plan["stop_reason"], plan["unresearched_in_pool"]), (2, "pool_exhausted", 0))
        self.assertEqual(r["skipped"], [])

    def test_default_budget_is_target_plus_half_and_is_validated_before_any_work(self):
        self.assertEqual([default_research_budget(n) for n in (0, 1, 3, 10, 40)], [0, 2, 5, 15, 60])
        spec = {"a.example": OK}
        fetcher, transport = world(spec)
        adapter = ListAdapter([cand("a.example", OK_ATTRS)])
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(ValueError):
                run_pipeline(RunConfig(icp=POLICY, out_dir=Path(t), mode="synthetic_fixture", max_candidates=5,
                                       max_research=4), [adapter], fetcher)
            self.assertEqual(list(Path(t).iterdir()), [])
        self.assertEqual((adapter.calls, transport.requests), (0, []))

    def test_cli_exposes_max_research_and_passes_it_through(self):
        seen = {}

        class Stop(Exception):
            pass

        def capture(cfg, *a, **k):
            seen["cfg"] = cfg
            raise Stop

        for argv, expected in ((["run", "--max-candidates", "10", "--max-research", "12"], 12),
                               (["run", "--max-candidates", "10"], None)):
            with mock.patch.object(cli, "run_pipeline", capture), self.assertRaises(Stop):
                cli.main(argv)
            self.assertEqual((seen["cfg"].max_candidates, seen["cfg"].max_research), (10, expected))


class QualificationAndProvenanceUnchanged(unittest.TestCase):
    SPEC = {"f403.example": FORBIDDEN, "fbig.example": ENTERPRISE, "ok1.example": OK, "ok2.example": OK}

    def pool(self):
        return [cand("f403.example", FAIL_ATTRS), cand("fbig.example", FAIL_ATTRS),
                cand("ok1.example", OK_ATTRS), cand("ok2.example", OK_ATTRS)]

    def test_scores_tiers_and_evidence_equal_a_standalone_research_of_the_same_company(self):
        r = run(self.SPEC, self.pool(), max_candidates=2, max_research=4)
        fetcher, _ = world(self.SPEC)
        for rec in r["companies"]:
            alone = research_company(next(c for c in self.pool() if c.domain == rec["domain"]), fetcher, POLICY, 4)
            with self.subTest(domain=rec["domain"]):
                for key in ("tier", "total", "score", "evidence", "decision_makers", "company_type", "homepage"):
                    if key == "homepage":
                        self.assertEqual(rec[key]["ok"], alone[key]["ok"])
                    else:
                        self.assertEqual(rec[key], alone[key])
        self.assertIsNone(next(c for c in r["companies"] if c["domain"] == "f403.example")["total"])

    def test_discovery_provenance_and_dedup_rejections_survive_backfill(self):
        pool = self.pool() + [Candidate("Dup", "https://www.ok1.example/x?utm=1", "synthetic_fixture", "list",
                                        source_id="dup-1", attrs=dict(OK_ATTRS))]
        r = run(self.SPEC, pool, max_candidates=2, max_research=4)
        rejected = json.loads((Path(r["run_dir"]) / "rejected.json").read_text())
        self.assertEqual([(x["reason"], x["domain"]) for x in rejected], [("duplicate_domain", "ok1.example")])
        for rec in r["companies"]:
            self.assertEqual(rec["discovery"]["source"], "list")
            self.assertEqual(rec["discovery"]["source_url"], f"https://list.example/{rec['domain']}")
        self.assertEqual(r["manifest"]["counts"]["rejected"], 1)

    def test_run_is_deterministic_including_selection_metadata(self):
        a = run(self.SPEC, self.pool(), max_candidates=2, max_research=4)
        b = run(self.SPEC, self.pool(), max_candidates=2, max_research=4)
        self.assertEqual(domains(a), domains(b))
        self.assertEqual([c["research_selection"] for c in a["companies"]],
                         [c["research_selection"] for c in b["companies"]])
        self.assertEqual(a["skipped"], b["skipped"])
        self.assertEqual(a["manifest"]["research_plan"], b["manifest"]["research_plan"])


class OutcomeClassification(unittest.TestCase):
    def test_only_assessed_counts_toward_the_target(self):
        def rec(tier, ok):
            return {"tier": tier, "homepage": {"ok": ok}}
        for tier in ("strong", "possible", "weak"):
            self.assertEqual(research_outcome(rec(tier, True)), ASSESSED)
        self.assertEqual(research_outcome(rec(NOT_RESEARCHABLE, False)), NOT_RESEARCHABLE_ROBOTS)
        self.assertEqual(research_outcome(rec(EXCLUDED, False)), INACCESSIBLE)  # unreachable => excluded by scorer
        self.assertEqual(research_outcome(rec(EXCLUDED, True)), EXCLUDED_BY_EVIDENCE)


class ReportShowsTheResearchPlan(unittest.TestCase):
    def test_report_line_and_old_manifests_without_a_plan(self):
        spec = {"f403.example": FORBIDDEN, "ok1.example": OK, "ok2.example": OK}
        r = run(spec, [cand("f403.example", FAIL_ATTRS), cand("ok1.example", OK_ATTRS),
                       cand("ok2.example", OK_ATTRS)], max_candidates=1, max_research=2)
        text = write_report(r["run_dir"]).read_text()
        self.assertIn("research plan: target 1 assessed within a budget of 2 attempts", text)
        self.assertIn("backfill 1", text)
        self.assertIn("inaccessible 1", text)
        manifest = Path(r["run_dir"]) / "manifest.json"
        data = json.loads(manifest.read_text())
        data.pop("research_plan")
        manifest.write_text(json.dumps(data))
        self.assertNotIn("research plan:", write_report(r["run_dir"]).read_text())


if __name__ == "__main__":
    unittest.main()
