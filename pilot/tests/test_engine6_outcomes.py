"""Offline research-to-report checks with explicitly fictional pages."""
import copy
import tempfile
import unittest
from pathlib import Path
from vm1.discovery import Candidate
from vm1.fetch import FetchResult
from vm1.pipeline import research_company, run_pipeline, RunConfig
from vm1.policy import load_policy
from vm1.fixture import build_synthetic
from vm1.report import compute_metrics, render_report
from tests.util import ROOT, WORLD

POLICY = load_policy(ROOT / 'icp/frontend-studio-worldwide.json')

class Outcomes(unittest.TestCase):
    def research(self, pages):
        class Fetcher:
            def fetch(self, url):
                body = pages.get(url)
                return FetchResult(url=url, final_url=url, status=200 if body is not None else 403,
                                   text=body, error=None if body is not None else 'http_403',
                                   fetched_at='2026-11-23T00:00:00Z')
        c = Candidate(name='Acme Studio', url='https://acme.example/', discovery_method='synthetic_fixture',
                      source='fixture', source_id='acme', source_url='https://fixture.example/')
        return research_company(c, Fetcher(), POLICY, 4)

    def test_discovery_and_extraction_outcomes(self):
        home = 'https://acme.example/'
        cases = [({}, 'homepage_unreachable'),
                 ({home:'<p>Welcome</p>'}, 'no_people_page_fetched'),
                 ({home:'<a href="/team">Team</a>'}, 'people_pages_inaccessible'),
                 ({home:'<a href="/team">Team</a>', home+'team':'<p>Our team</p>'}, 'no_attributable_person_extracted'),
                 ({home:'<a href="/team">Team</a>', home+'team':'<span>Jane Doe</span><span>CEO</span>'}, 'named')]
        for pages, outcome in cases:
            with self.subTest(outcome=outcome):
                c = self.research(pages)
                self.assertEqual(c['decision_maker_outcome'], outcome)
                self.assertEqual(bool(c['decision_makers']), outcome == 'named')

    def test_reporting_counts_eligible_and_old_runs_remain_unrecorded(self):
        with tempfile.TemporaryDirectory() as out:
            adapters, fetcher = build_synthetic(WORLD)
            run = run_pipeline(RunConfig(icp=POLICY, out_dir=Path(out), mode='synthetic_fixture'), adapters, fetcher)
            metrics = compute_metrics(run)
            self.assertEqual(sum(metrics['dm_outcomes'].values()), metrics['eligible'])
            self.assertIn('Decision-maker outcomes (eligible companies)', render_report(run, metrics))
            old = copy.deepcopy(run)
            for c in old['companies']:
                c.pop('decision_maker_outcome', None)
            m = compute_metrics(old)
            self.assertEqual(m['dm_outcomes'], {'unrecorded':m['eligible']})
            self.assertIn('unknown (unrecorded)', render_report(old, m))
