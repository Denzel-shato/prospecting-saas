"""Engine #6 V2 passage coverage audit: synthetic saved runs only (fictional companies, no network, no AI)."""
import csv
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_e6v2_workflow import TESTIMONIAL, make_store
from vm1.e6v2_audit import audit as audit_mod
from vm1.e6v2_audit import run_audit, write_outputs
from vm1.e6v2_audit.__main__ import main

TEAM = ('<html><body><h1>Our Team</h1><div class="card"><h3>Maya Okafor</h3><p>Founder &amp; CEO</p></div>'
        '<div class="card"><h3>Chris Lee</h3><p>Lead Designer</p></div>'
        '<p>Weekend rides are organised by Zed Ample, who loves cycling.</p></body></html>')
HOME = ("<html><body><h1>Welcome</h1><p>We build apps for clients.</p>"
        "<p>Weekend rides are organised by Zed Ample, who loves cycling.</p>"
        '<div class="card"><h3>Maya Okafor</h3><p>Founder</p></div></body></html>')
ACCENT = '<html><body><h1>About</h1><div class="card"><h3>Agustin Guerra</h3><p>CEO and Co-Founder</p></div></body></html>'
PRICING = "<html><body><h1>Pricing</h1><p>Plans start soon.</p></body></html>"

# domain -> (html or None, fetch_ok, label name, label role)
CASES = {
    "covered.example": (TEAM, True, "Maya Okafor", "Founder"),
    "norole.example": (TEAM, True, "Chris Lee", "CTO"),
    "offpage.example": (TEAM, True, "Nobody Real", "CEO"),
    "unselected.example": (HOME, True, "Zed Ample", "CEO"),
    "accent.example": (ACCENT, True, "Agustín Guerra", "CEO & Co-Founder"),
    "quote.example": (TESTIMONIAL, True, "Mary Major", "CEO"),
    "pricing.example": (PRICING, True, "Pat Q", "CEO"),
    "failed.example": (None, False, "Fay Led", "CEO"),
    "nosnap.example": (None, True, "Sam Lost", "CEO"),
}


class AuditBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.source = self.tmp / "run"
        (self.source / "snapshots").mkdir(parents=True)
        rows, labels = [], []
        for domain, (html, ok, name, role) in CASES.items():
            rows.append({"domain": domain, "fetch_ok": ok, "http_status": 200 if ok else None,
                         "fetch_error": None if ok else "timeout"})
            labels.append({"company": domain.split(".")[0].title(), "domain": domain, "url": f"https://{domain}/",
                           "expected_name": name, "expected_role": role})
            if html:
                path = {"pricing": "pricing", "unselected": ""}.get(domain.split(".")[0], "team")
                make_store(self.source / "snapshots" / audit_mod.slug(domain), {f"https://{domain}/{path}": html.encode()})
        (self.source / "results.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
        self.labels = self.tmp / "labels.csv"
        with open(self.labels, "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=list(labels[0]))
            w.writeheader()
            w.writerows(labels)
        self.rows = {r["domain"]: r for r in run_audit(self.source, self.labels)}

    def status(self, domain):
        return self.rows[domain]["status"], self.rows[domain]["detail"]


class ClassificationTests(AuditBase):
    def test_covered_name_and_role_in_one_passage(self):
        self.assertEqual(self.status("covered.example")[0], "covered")
        self.assertTrue(self.rows["covered.example"]["name_and_role_together"])

    def test_name_without_role(self):
        self.assertEqual(self.status("norole.example")[0], "name_without_role")

    def test_name_not_on_page_vs_on_page_but_not_selected(self):
        self.assertEqual(self.status("offpage.example"), ("name_not_in_passages", "name_not_on_page"))
        self.assertEqual(self.status("unselected.example"), ("name_not_in_passages", "name_on_page_not_selected"))

    def test_accent_case_and_ampersand_folding(self):
        self.assertEqual(self.status("accent.example")[0], "covered")

    def test_testimonial_is_covered_but_flags_are_reported(self):
        r = self.rows["quote.example"]
        self.assertEqual(r["status"], "covered")
        self.assertIn("ctx:quote", r["name_passage_flags"])
        self.assertIn("ctx:quote", r["risk_flags"])

    def test_no_passages_is_a_prep_outcome_with_zero_counts(self):
        r = self.rows["pricing.example"]
        self.assertEqual((r["status"], r["passages"], r["chars"]), ("no_passages", 0, 0))

    def test_fetch_failures_are_distinct_from_prep_failures(self):
        self.assertEqual(self.status("failed.example")[0], "fetch_failed")
        self.assertEqual(self.rows["failed.example"]["fetch_error"], "timeout")
        self.assertEqual(self.status("nosnap.example")[0], "snapshot_unavailable")
        self.assertNotIn(self.status("failed.example")[0], audit_mod.PREP_SIDE)
        self.assertNotIn(self.status("nosnap.example")[0], audit_mod.PREP_SIDE)

    def test_missing_fetch_record(self):
        label = {"company": "X", "domain": "ghost.example", "expected_name": "A B", "expected_role": "CEO"}
        self.assertEqual(audit_mod.audit_company(label, None, self.source)["status"], "no_fetch_record")

    def test_corrupted_snapshot_body_is_snapshot_unavailable(self):
        store = self.source / "snapshots" / "covered-example" / "responses"
        next(store.glob("*.body")).write_bytes(b"tampered")
        self.assertEqual(run_audit(self.source, self.labels)[0]["status"], "snapshot_unavailable")

    def test_prep_exception_is_reported_as_prep_error(self):
        with mock.patch.object(audit_mod, "prepare_evidence", side_effect=RuntimeError("boom")):
            rows = {r["domain"]: r for r in run_audit(self.source, self.labels)}
        self.assertEqual(rows["covered.example"]["status"], "prep_error")
        self.assertIn("boom", rows["covered.example"]["detail"])
        self.assertEqual(rows["failed.example"]["status"], "fetch_failed")   # unaffected

    def test_passage_and_character_counts(self):
        r = self.rows["covered.example"]
        self.assertGreater(r["passages"], 0)
        self.assertGreaterEqual(r["chars"], r["max_passage_chars"])
        self.assertGreater(r["max_passage_chars"], 0)


class OutputTests(AuditBase):
    def sha(self, p):
        return hashlib.sha256(Path(p).read_bytes()).hexdigest()

    def test_outputs_in_new_dir_inputs_untouched(self):
        before = (self.sha(self.labels), self.sha(self.source / "results.jsonl"))
        out = self.tmp / "new-out"
        md, csv_path = write_outputs(list(self.rows.values()), self.source, out)
        self.assertEqual((md.name, csv_path.name), ("report.md", "audit.csv"))
        self.assertEqual(before, (self.sha(self.labels), self.sha(self.source / "results.jsonl")))
        with open(csv_path, encoding="utf-8") as fh:
            data = list(csv.DictReader(fh))
        self.assertEqual(len(data), len(CASES))
        self.assertEqual(list(data[0]), audit_mod.COLUMNS)
        text = md.read_text(encoding="utf-8")
        for needle in ("fetch side", "prep side", "Fetch-side gaps", "failed.example", "name_not_on_page", "covered"):
            self.assertIn(needle, text)

    def test_refuses_non_empty_output_dir(self):
        out = self.tmp / "used"
        out.mkdir()
        (out / "keep.txt").write_text("x")
        with self.assertRaises(FileExistsError):
            write_outputs(list(self.rows.values()), self.source, out)
        self.assertEqual((out / "keep.txt").read_text(), "x")

    def test_cli_ok_and_errors(self):
        out = self.tmp / "cli-out"
        self.assertEqual(main(["--source", str(self.source), "--labels", str(self.labels), "--out", str(out)]), 0)
        self.assertTrue((out / "report.md").exists())
        self.assertEqual(main(["--source", str(self.source), "--labels", str(self.labels), "--out", str(out)]), 2)
        self.assertEqual(main(["--source", str(self.tmp / "nope"), "--labels", str(self.labels),
                               "--out", str(self.tmp / "o2")]), 2)


if __name__ == "__main__":
    unittest.main()
