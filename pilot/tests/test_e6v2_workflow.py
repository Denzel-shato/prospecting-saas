"""Engine #6 V2 offline workflow: saved snapshot -> prep -> MockProvider -> verification. Synthetic, no network."""
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tests.util import ROOT
from vm1.ai import AIHTTPError, MockProvider
from vm1.e6v2 import prepare_evidence
from vm1.e6v2_workflow import load_snapshots, run_offline
from vm1.e6v2_workflow.workflow import OfflineOnlyError
from vm1.snapshot import SnapshotStore

PAGES = ROOT / "fixtures" / "synthetic" / "pages"
KEY, NAME = "brightlane.example", "Brightlane Studio"
TESTIMONIAL = ("<html><body><h1>What clients say</h1><blockquote><p>Great work from the whole crew, truly.</p>"
               "<p>Mary Major, CEO of Globex Corp</p></blockquote></body></html>")


def make_store(root, pages: dict) -> str:
    store = SnapshotStore(root)
    for url, body in pages.items():
        store.put({"method": "GET", "url": url, "status": 200, "headers": {"content-type": "text/html; charset=utf-8"},
                   "truncated": False, "captured_at": "2026-11-21T00:00:00+00:00"}, body)
    return str(root)


def claim(p, name, role, quote=None, company=NAME):
    return {"name": name, "role": role, "company": company, "passage_id": p.passage_id,
            "quote": quote or f"{name} {role}"}


class WorkflowBase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.store = make_store(self.tmp / "store", {
            "https://brightlane.example/team": (PAGES / "brightlane_team.html").read_bytes(),
            "https://brightlane.example/": (PAGES / "brightlane_home.html").read_bytes()})
        self.snaps = load_snapshots(self.store)
        self.passages = prepare_evidence(self.snaps).passages

    def p(self, needle):
        return next(p for p in self.passages if needle in p.text)


class EndToEndTests(WorkflowBase):
    def test_mixed_ai_output_is_sorted_into_three_buckets(self):
        ai = {"decision_makers": [
            claim(self.p("Maya Okafor"), "Maya Okafor", "Founder & CEO"),                       # real
            claim(self.p("Chris Lee"), "Chris Lee", "Lead Designer"),                          # not leadership
            claim(self.p("Maya Okafor"), "Maya Okafor", "Chief Wizard", "Maya Okafor Chief Wizard"),  # fabricated
            {**claim(self.p("Maya Okafor"), "Zed Nobody", "CEO"), "passage_id": "ps_000000000000"},     # bad id
        ]}
        provider = MockProvider([ai])
        r = run_offline(self.snaps, provider, KEY, NAME)
        self.assertEqual([x["name"] for x in r.accepted], ["Maya Okafor"])
        self.assertEqual([x["name"] for x in r.review], ["Chris Lee"])
        self.assertEqual(sorted(x["reason"] for x in r.rejected), ["quote_not_in_passage", "unknown_passage_id"])
        self.assertTrue(r.provider_called and len(provider.calls) == 1 and r.error == "")

    def test_request_carries_passage_ids_and_text_only(self):
        provider = MockProvider([{"decision_makers": []}])
        run_offline(self.snaps, provider, KEY, NAME)
        prompt = provider.calls[0].prompt
        for p in self.passages:
            self.assertIn(p.passage_id, prompt)
            self.assertIn(p.text, prompt)
        self.assertNotIn("<html", prompt.lower())

    def test_testimonial_snapshot_is_rejected_even_if_ai_claims_target_company(self):
        store = make_store(self.tmp / "t", {"https://brightlane.example/": TESTIMONIAL.encode()})
        snaps = load_snapshots(store)
        p = next(p for p in prepare_evidence(snaps).passages if "Mary Major" in p.text)
        ai = {"decision_makers": [claim(p, "Mary Major", "CEO", "Mary Major, CEO of Globex Corp"),
                                  claim(p, "Mary Major", "CEO", "Mary Major, CEO of Globex Corp", company="Globex Corp")]}
        r = run_offline(snaps, MockProvider([ai]), KEY, NAME)
        self.assertEqual((len(r.accepted), len(r.review), len(r.rejected)), (0, 0, 2))

    def test_result_is_json_and_deterministic(self):
        ai = {"decision_makers": [claim(self.p("Maya Okafor"), "Maya Okafor", "Founder & CEO")]}
        a = json.dumps(run_offline(self.snaps, MockProvider([ai]), KEY, NAME).to_dict(), sort_keys=True)
        b = json.dumps(run_offline(load_snapshots(self.store), MockProvider([ai]), KEY, NAME).to_dict(), sort_keys=True)
        self.assertEqual(a, b)


class GuardAndFailureTests(WorkflowBase):
    def test_non_mock_provider_is_refused_before_any_call(self):
        class Live:
            name = "groq"
            called = False

            def generate_structured(self, request):
                Live.called = True
        with self.assertRaises(OfflineOnlyError):
            run_offline(self.snaps, Live(), KEY, NAME)
        self.assertFalse(Live.called)

    def test_no_passages_means_no_provider_call(self):
        store = make_store(self.tmp / "e", {"https://brightlane.example/pricing": b"<html><body><p>Plans</p></body></html>"})
        provider = MockProvider()
        r = run_offline(load_snapshots(store), provider, KEY, NAME)
        self.assertEqual((r.passages, r.provider_called, provider.calls), (0, False, []))

    def test_provider_error_yields_error_and_no_results(self):
        r = run_offline(self.snaps, MockProvider([AIHTTPError(500, "boom", provider="mock")]), KEY, NAME)
        self.assertTrue(r.error)
        self.assertEqual((r.accepted, r.review, r.rejected), ([], [], []))

    def test_malformed_model_output_is_a_provider_error_not_a_crash(self):
        r = run_offline(self.snaps, MockProvider(["not json"]), KEY, NAME)
        self.assertTrue(r.error.startswith("AIResponseError"))

    def test_load_snapshots_skips_non_html_failed_and_truncated(self):
        store = SnapshotStore(self.tmp / "m")
        ok = {"method": "GET", "status": 200, "headers": {"content-type": "text/html"}, "truncated": False,
              "captured_at": "t"}
        store.put({**ok, "url": "https://a.example/team"}, b"<html><body><h1>Team</h1></body></html>")
        store.put({**ok, "url": "https://a.example/robots.txt", "headers": {"content-type": "text/plain"}}, b"x")
        store.put({**ok, "url": "https://a.example/big", "truncated": True}, b"<html></html>")
        store.put({**ok, "url": "https://a.example/gone", "status": 404}, b"<html></html>")
        self.assertEqual([s.url for s in load_snapshots(self.tmp / "m")], ["https://a.example/team"])


class CliSmokeTests(WorkflowBase):
    def test_cli_runs_in_fresh_interpreter_without_network(self):
        scripted = self.tmp / "mock.json"
        scripted.write_text(json.dumps({"decision_makers": [
            claim(self.p("Maya Okafor"), "Maya Okafor", "Founder & CEO"),
            claim(self.p("Maya Okafor"), "Maya Okafor", "Chief Wizard", "Maya Okafor Chief Wizard")]}))
        code = (
            "import socket, sys\n"
            "def boom(*a, **k): raise AssertionError('network attempted')\n"
            "socket.socket.connect = boom; socket.getaddrinfo = boom; socket.create_connection = boom\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "from vm1.e6v2_workflow.__main__ import main\n"
            f"sys.exit(main(['--snapshot-dir', {self.store!r}, '--company-key', {KEY!r}, "
            f"'--company-name', {NAME!r}, '--mock-response', {str(scripted)!r}]))\n")
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=self.tmp)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        out = json.loads(proc.stdout)
        self.assertEqual(out["counts"], {"accepted": 1, "review": 0, "rejected": 1})
        self.assertEqual(out["accepted"][0]["name"], "Maya Okafor")

    def test_cli_bad_inputs_exit_2(self):
        from vm1.e6v2_workflow.__main__ import main
        self.assertEqual(main(["--snapshot-dir", str(self.tmp), "--company-key", KEY,
                               "--mock-response", str(self.tmp / "missing.json")]), 2)


if __name__ == "__main__":
    unittest.main()
