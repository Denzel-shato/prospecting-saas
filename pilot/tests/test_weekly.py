import csv
import json
import tempfile
import unittest
from pathlib import Path

from vm1.weekly import build_weekly, read_reviews


class WeeklyReviewTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.root = Path(scratch.name)
        self.out = self.root / "week"

    def make_run(self, name, *domains, mode="live"):
        path = self.root / name
        path.mkdir()
        manifest = {"run_id": name, "mode": mode, "icp_id": "studio", "policy_digest": "abc"}
        companies = [{
            "domain": domain, "name": domain, "url": f"https://{domain}", "tier": "possible", "total": 45,
            "decision_makers": [{"name": "Example Person", "title": "Founder", "source_url": f"https://{domain}/team"}],
            "evidence": [], "verified_evidence_ids": [],
        } for domain in domains]
        for file, data in (("manifest", manifest), ("companies", companies), ("drafts", []),
                           ("rejected", []), ("candidates", [])):
            (path / f"{file}.json").write_text(json.dumps(data), encoding="utf-8")
        return path

    def edit_review(self, path, **updates):
        with path.open(newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            rows = list(reader)
        rows[0].update(updates)
        with path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, rows[0])
            writer.writeheader()
            writer.writerows(rows)

    def test_deduplicates_current_batches_and_previously_reviewed_domains(self):
        old = self.root / "history.csv"
        old.write_text("domain,decision\nold.example,skip\nretry.example,needs_research\n", encoding="utf-8")
        a = self.make_run("a", "old.example", "www.new.example", "retry.example")
        b = self.make_run("b", "new.example")
        result = build_weekly([("directory", a), ("search", b)], [old], self.out)
        self.assertEqual(result["unique_new_companies"], 2)
        self.assertEqual(result["sources"]["directory"]["previously_reviewed"], 1)
        self.assertEqual(result["sources"]["search"]["duplicate"], 1)
        self.assertEqual(result["shortfall_to_150"], 150)

    def test_ready_requires_human_verified_fields_and_preserves_edits(self):
        batches = [("directory", self.make_run("a", "new.example"))]
        queue = self.out / "review.csv"
        self.assertEqual(build_weekly(batches, [], self.out)["ready_to_contact"], 0)
        self.edit_review(queue, decision="contact", reason="Client web work")
        self.assertEqual(build_weekly(batches, [], self.out)["contact_missing_verification_or_angle"], 1)
        self.edit_review(queue, verified_person="Example Person", verified_role="Founder",
                         verified_person_url="https://offsite.example/team", outreach_angle="React client portal")
        self.assertEqual(build_weekly(batches, [], self.out)["ready_to_contact"], 0)
        self.edit_review(queue, verified_person_url="https://www.new.example/team")
        self.assertEqual(build_weekly(batches, [], self.out)["ready_to_contact"], 1)
        self.assertEqual(read_reviews(queue)["new.example"]["reason"], "Client web work")
        self.assertEqual(build_weekly(batches, [], self.out)["high_fit_ready_to_contact"], 0)
        self.edit_review(queue, fit="plausible", client_project_url="https://new.example/work/portal")
        self.assertEqual(build_weekly(batches, [], self.out)["high_fit_ready_to_contact"], 0)
        self.edit_review(queue, fit="strong", client_project_url="https://offsite.example/work/portal")
        self.assertEqual(build_weekly(batches, [], self.out)["high_fit_ready_to_contact"], 0)
        self.edit_review(queue, client_project_url="https://new.example/work/portal")
        result = build_weekly(batches, [], self.out)
        self.assertEqual(result["high_fit_ready_to_contact"], 1)
        self.assertEqual(result["shortfall_to_150"], 149)

    def test_refuses_synthetic_input_without_creating_review_files(self):
        with self.assertRaisesRegex(ValueError, "only live"):
            build_weekly([("fixture", self.make_run("a", "new.example", mode="synthetic_fixture"))], [], self.out)
        self.assertFalse(self.out.exists())
