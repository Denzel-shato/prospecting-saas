"""Engine #2 compatibility: every shipped ICP and every discovery adapter's real output flows through the new
ordering and backfill without changing priorities, qualification or the "directory listing never ranks" rule."""
from __future__ import annotations

import hashlib
import itertools
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.test_pickanagency import MockClient, record
from tests.util import ROOT, WORLD
from vm1.discovery import (ApiClient, DrupalOrgAdapter, ManualCsvAdapter, OverpassAdapter, SyntheticFixtureAdapter,
                           WikidataAdapter)
from vm1.directory_seed import DirectorySeedAdapter
from vm1.pickanagency import PickAnAgencyAdapter
from vm1.pipeline import (ASSESSED, EXCLUDED_BY_EVIDENCE, INACCESSIBLE, dedup, prioritize_pool,
                          research_with_backfill, skipped_records)
from vm1.policy import load_policy
from vm1.prequalify import prequalify, term_breadth

ICPS = sorted((ROOT / "icp").glob("*.json"))
SEED_DIR = ROOT / "fixtures" / "directory_seed"


def drupal_candidates():
    rows = [{"type": "organization", "nid": str(i), "title": f"Studio {i}", "field_link": {"url": f"https://d{i}.example"},
             "field_organization_headquarters": "Denver, CO",
             "body": {"value": f"<p>{text}</p>"}}
            for i, text in ((1, "We build React applications."), (2, "Download our CMS."), (3, "A development agency."))]

    class Client:
        def request_json(self, method, url):
            return {"list": rows}

    return DrupalOrgAdapter(Client()).discover()


def pickanagency_candidates():
    rows = [record("Dev Shop", "https://devshop.example", services=["Web Development", "Software Development"],
                   tagline="Custom software"),
            record("Growth Co", "https://growth.example", services=["SEO", "Social Media Marketing"],
                   tagline="Brand growth"),
            record("Plain Co", "https://plain.example", services=["Software Development"])]
    return PickAnAgencyAdapter(MockClient({"results": rows}), search_terms=("custom software",)).discover()


def wikidata_candidates():
    data = {"results": {"bindings": [
        {"item": {"value": "http://www.wikidata.org/entity/Q1"}, "itemLabel": {"value": "Foo"},
         "website": {"value": "https://foo.example"}, "desc": {"value": "web development agency"},
         "employees": {"value": "12"}, "listed": {"value": "false"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q2"}, "itemLabel": {"value": "Bar"},
         "website": {"value": "https://bar.example"}, "desc": {"value": "cloud platform"},
         "listed": {"value": "true"}},
        {"item": {"value": "http://www.wikidata.org/entity/Q3"}, "itemLabel": {"value": "Baz"},
         "website": {"value": "https://baz.example"}}]}}
    return WikidataAdapter(ApiClient(transport=object())).parse(data, "t")


def overpass_candidates():
    els = [{"type": "node", "id": i, "tags": {"name": f"Office {i}", "website": f"https://o{i}.example"}}
           for i in range(4)]
    return OverpassAdapter(ApiClient(transport=object()), True).parse({"elements": els}, "t")


def manual_candidates(tmp):
    path = Path(tmp) / "manual.csv"
    path.write_text("name,url\n" + "".join(f"M{i},https://m{i}.example\n" for i in range(4)), encoding="utf-8")
    return ManualCsvAdapter(path).discover()


def seed_candidates():
    return DirectorySeedAdapter(SEED_DIR / "fictional_smoke_seed.csv",
                                catalog_path=SEED_DIR / "fixture_catalog.json").discover()


def synthetic_candidates():
    return SyntheticFixtureAdapter(WORLD).discover()


class EveryAdapterThroughEveryIcp(unittest.TestCase):
    def pools(self):
        with tempfile.TemporaryDirectory() as tmp:
            return {"drupal_org": drupal_candidates(), "pickanagency": pickanagency_candidates(),
                    "wikidata": wikidata_candidates(), "openstreetmap": overpass_candidates(),
                    "manual_csv": manual_candidates(tmp), "directory_seed": seed_candidates(),
                    "synthetic": synthetic_candidates()}

    def test_shipped_icps_are_found(self):
        self.assertGreaterEqual(len(ICPS), 4)

    def test_ordering_never_reorders_across_priorities_and_is_deterministic(self):
        pools = self.pools()
        for icp in ICPS:
            policy = load_policy(icp)
            for name, found in pools.items():
                pool, _, _ = dedup(found)
                with self.subTest(icp=icp.stem, adapter=name):
                    self.assertTrue(pool)
                    rows, info = prioritize_pool(pool, "seed", policy)
                    again, _ = prioritize_pool(list(reversed(pool)), "seed", policy)
                    self.assertEqual([r.candidate.domain for r in rows], [r.candidate.domain for r in again])
                    self.assertEqual(sorted(r.candidate.domain for r in rows), sorted(c.domain for c in pool))
                    priorities = [r.priority for r in rows]
                    self.assertEqual(priorities, sorted(priorities, reverse=True))
                    for r in rows:  # the integer priority is exactly prequalify(): text never alters it
                        self.assertEqual((r.priority, r.reasons), prequalify(r.candidate.attrs, policy))

    def test_records_without_text_keep_the_original_seeded_hash_order(self):
        """Manual CSV, OSM, directory seeds and Wikidata rows with no description carry no text signal, so the
        order is exactly the pre-Engine-#2 (priority, seeded hash) order. Directory listings still never rank."""
        pools = self.pools()
        for icp in ICPS:
            policy = load_policy(icp)
            for name in ("manual_csv", "openstreetmap", "directory_seed"):
                pool, _, _ = dedup(pools[name])
                with self.subTest(icp=icp.stem, adapter=name):
                    for c in pool:
                        self.assertEqual(term_breadth(c.attrs, policy), (0, [], []))
                    old = sorted(pool, key=lambda c: (-prequalify(c.attrs, policy)[0],
                                                      hashlib.sha256(f"seed|{c.domain}".encode()).hexdigest()))
                    rows, _ = prioritize_pool(pool, "seed", policy)
                    self.assertEqual([r.candidate.domain for r in rows], [c.domain for c in old])
        seeds, _, _ = dedup(pools["directory_seed"])
        for c in seeds:
            self.assertEqual(prequalify(c.attrs, load_policy(ICPS[0])), (0, []))

    def test_pickanagency_text_is_ranked_with_the_icps_own_terms(self):
        pool = pickanagency_candidates()
        frontend = load_policy(ROOT / "icp" / "frontend-studio.json")
        rows, info = prioritize_pool(pool, "seed", frontend)
        by = {r.candidate.domain: r for r in rows}
        self.assertGreater(by["devshop.example"].breadth, by["plain.example"].breadth)
        self.assertLess(by["growth.example"].breadth, by["plain.example"].breadth)
        self.assertEqual([r.candidate.domain for r in rows][0], "devshop.example")
        self.assertIn("tie_break", info["growth.example"])


def stub_record(domain, outcome):
    return {"domain": domain, "tier": {ASSESSED: "weak", INACCESSIBLE: "excluded", EXCLUDED_BY_EVIDENCE: "excluded"}[outcome],
            "homepage": {"ok": outcome != INACCESSIBLE}}


class BackfillInvariants(unittest.TestCase):
    """Every success/failure pattern over a 6-company pool, target 2, budget 4 (64 patterns, no network)."""

    def test_invariants_hold_for_all_patterns(self):
        pool = [SimpleNamespace(domain=f"c{i}.example", name=f"C{i}", url="", discovery_method="manual",
                                source="s", source_id="", source_url="", attrs={}) for i in range(6)]
        policy = load_policy(ROOT / "icp" / "frontend-studio.json")
        ranked, _ = prioritize_pool(pool, "s", policy)
        order = [r.candidate.domain for r in ranked]
        for pattern in itertools.product((ASSESSED, INACCESSIBLE), repeat=6):
            outcome_of = dict(zip(order, pattern))
            with self.subTest(pattern=pattern):
                companies, researched, plan = research_with_backfill(
                    ranked, 2, 4, lambda c: stub_record(c.domain, outcome_of[c.domain]))
                attempted = [c["domain"] for c in companies]
                self.assertEqual(attempted, order[:len(attempted)], "always best-first, never skipping ahead")
                self.assertLessEqual(len(attempted), 4)
                self.assertLessEqual(plan["assessed"], 2)
                self.assertEqual(plan["assessed"], sum(outcome_of[d] == ASSESSED for d in attempted))
                if plan["assessed"] == 2:
                    self.assertEqual(plan["stop_reason"], "target_met")
                    self.assertEqual(outcome_of[attempted[-1]], ASSESSED, "stops as soon as the target is met")
                elif len(attempted) == 4:
                    self.assertEqual(plan["stop_reason"], "budget_exhausted")
                else:
                    self.assertEqual(plan["stop_reason"], "pool_exhausted")
                    self.assertEqual(len(attempted), 6)
                self.assertEqual(plan["target_shortfall"], 2 - plan["assessed"])
                skipped = skipped_records(ranked, researched, plan)
                self.assertEqual(len(skipped) + len(attempted), 6)
                self.assertEqual(plan["unresearched_in_pool"], len(skipped))
                replaced = [c["research_selection"]["backfill_for"] for c in companies
                            if "backfill_for" in c["research_selection"]]
                self.assertEqual(len(replaced), len(set(replaced)), "a failure is replaced at most once")
                for c in companies:
                    sel = c["research_selection"]
                    if "backfill_for" in sel:
                        self.assertEqual(sel["wave"], "backfill")
                        self.assertLess(attempted.index(sel["backfill_for"]), attempted.index(c["domain"]))
                        self.assertNotEqual(outcome_of[sel["backfill_for"]], ASSESSED)


if __name__ == "__main__":
    unittest.main()
