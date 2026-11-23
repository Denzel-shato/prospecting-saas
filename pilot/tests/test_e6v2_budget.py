"""Engine #6 V2 persistent $0 usage manager: synthetic limits only, no provider calls, no network."""
import ast
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from tests.util import ROOT
from vm1.e6v2_budget import (DEFERRED, GRANTED, REJECTED, ConfigError, ModelLimits, ReservationStateError,
                             UsageManager)
from vm1.guard import PaidApiBlocked

P, M = "fakeprov", "free-model-a"


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


def lim(**kw):
    kw.setdefault("cost_class", "free_tier")
    return ModelLimits(P, M, **kw)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = str(Path(self.tmp.name) / "usage.sqlite")
        self.clock = Clock()

    def mgr(self, *models, **kw):
        kw.setdefault("clock", self.clock)
        return UsageManager(self.db, models or [lim(requests_per_day=3)], **kw)


class ConfigAndAllowlistTests(Base):
    def test_unknown_provider_and_model_rejected(self):
        m = self.mgr()
        for prov, model in ((P, "other"), ("other", M)):
            r = m.reserve(prov, model, 1)
            self.assertEqual((r.status, r.reason), (REJECTED, "model_not_allowlisted"))
        self.assertEqual(m.usage(P, M)["day_requests"], 0)

    def test_paid_or_unset_cost_class_blocked(self):
        for cc in ("", "paid", "free_keyless", "unknown"):
            with self.assertRaises(PaidApiBlocked):
                ModelLimits(P, M, cost_class=cc, requests_per_day=1)

    def test_no_default_cost_class_means_paid_is_never_implicit(self):
        with self.assertRaises(PaidApiBlocked):
            ModelLimits(P, M, requests_per_day=10)

    def test_requires_a_limit_and_sane_values(self):
        with self.assertRaises(ConfigError):
            lim()
        with self.assertRaises(ConfigError):
            lim(requests_per_day=-1)
        with self.assertRaises(ConfigError):
            lim(requests_per_day=True)
        with self.assertRaises(ConfigError):
            UsageManager(self.db, [lim(requests_per_day=1), lim(requests_per_day=2)])
        with self.assertRaises(ConfigError):
            UsageManager(":memory:", [lim(requests_per_day=1)])

    def test_invalid_estimates_rejected(self):
        m = self.mgr()
        self.assertEqual(m.reserve(P, M, -1).reason, "invalid_estimate")
        self.assertEqual(m.reserve(P, M, 1, "x").reason, "invalid_estimate")


class LimitTests(Base):
    def test_daily_request_exhaustion_defers_until_next_utc_day(self):
        m = self.mgr(lim(requests_per_day=2))
        self.assertTrue(m.reserve(P, M).granted and m.reserve(P, M).granted)
        r = m.reserve(P, M)
        self.assertEqual((r.status, r.dimension), (DEFERRED, "requests_per_day"))
        self.assertAlmostEqual(r.retry_after_s, 86400 - self.clock.t % 86400, places=2)
        self.clock.t += r.retry_after_s
        self.assertTrue(m.reserve(P, M).granted)

    def test_day_offset_is_configurable(self):
        m = self.mgr(lim(requests_per_day=1), day_utc_offset_minutes=120)
        self.assertTrue(m.reserve(P, M).granted)
        r = m.reserve(P, M)
        self.assertAlmostEqual(r.retry_after_s, 86400 - (self.clock.t + 7200) % 86400, places=2)

    def test_per_minute_rolling_window_and_retry_after(self):
        m = self.mgr(lim(requests_per_minute=2))
        m.reserve(P, M)
        self.clock.t += 20
        m.reserve(P, M)
        r = m.reserve(P, M)
        self.assertEqual((r.status, r.dimension), (DEFERRED, "requests_per_minute"))
        self.assertAlmostEqual(r.retry_after_s, 40.0, places=2)
        self.clock.t += 40.01
        self.assertTrue(m.reserve(P, M).granted)

    def test_token_quotas_minute_and_day(self):
        m = self.mgr(lim(tokens_per_minute=1000, tokens_per_day=1500))
        self.assertTrue(m.reserve(P, M, 800).granted)
        r = m.reserve(P, M, 300)
        self.assertEqual((r.status, r.dimension), (DEFERRED, "tokens_per_minute"))
        self.clock.t += 61
        self.assertTrue(m.reserve(P, M, 600).granted)       # 1400 of 1500 today
        self.clock.t += 61
        r = m.reserve(P, M, 200)
        self.assertEqual((r.status, r.dimension), (DEFERRED, "tokens_per_day"))

    def test_neurons_tracked_separately_from_tokens(self):
        m = self.mgr(lim(tokens_per_day=10_000, neurons_per_day=100))
        self.assertTrue(m.reserve(P, M, est_tokens=5000, est_neurons=60).granted)
        r = m.reserve(P, M, est_tokens=10, est_neurons=50)   # tokens fine, neurons exhausted
        self.assertEqual((r.status, r.dimension), (DEFERRED, "neurons_per_day"))
        self.assertTrue(m.reserve(P, M, est_tokens=10, est_neurons=40).granted)
        u = m.usage(P, M)
        self.assertEqual((u["day_tokens"], u["day_neurons"]), (5010, 100))

    def test_estimate_larger_than_any_limit_is_rejected_not_deferred(self):
        m = self.mgr(lim(tokens_per_minute=100))
        r = m.reserve(P, M, 101)
        self.assertEqual((r.status, r.reason, r.dimension), (REJECTED, "estimate_exceeds_limit", "tokens_per_minute"))

    def test_unconfigured_dimension_is_recorded_not_enforced(self):
        m = self.mgr(lim(requests_per_day=5))
        self.assertTrue(m.reserve(P, M, 10**9, 10**9).granted)
        self.assertEqual(m.usage(P, M)["day_tokens"], 10**9)

    def test_models_do_not_share_counters(self):
        m = self.mgr(lim(requests_per_day=1), ModelLimits(P, "b", cost_class="free_tier", requests_per_day=1))
        self.assertTrue(m.reserve(P, M).granted and m.reserve(P, "b").granted)
        self.assertEqual(m.reserve(P, M).status, DEFERRED)


class ReconcileTests(Base):
    def test_reconcile_frees_unused_estimate_and_records_actual(self):
        m = self.mgr(lim(tokens_per_day=1000))
        r = m.reserve(P, M, 900)
        self.assertEqual(m.reserve(P, M, 200).status, DEFERRED)
        m.reconcile(r.reservation_id, 300)
        self.assertEqual(m.usage(P, M)["day_tokens"], 300)
        self.assertTrue(m.reserve(P, M, 600).granted)

    def test_actual_above_estimate_is_recorded_truthfully(self):
        m = self.mgr(lim(tokens_per_day=1000))
        r = m.reserve(P, M, 100)
        m.reconcile(r.reservation_id, 950)
        self.assertEqual(m.reserve(P, M, 100).status, DEFERRED)

    def test_release_returns_everything(self):
        m = self.mgr(lim(requests_per_day=1))
        r = m.reserve(P, M, 5)
        m.release(r.reservation_id)
        self.assertEqual(m.usage(P, M)["day_requests"], 0)
        self.assertTrue(m.reserve(P, M).granted)

    def test_double_settle_and_unknown_ids_raise(self):
        m = self.mgr()
        r = m.reserve(P, M, 5)
        m.reconcile(r.reservation_id, 4)
        for fn in (lambda: m.reconcile(r.reservation_id, 4), lambda: m.release(r.reservation_id),
                   lambda: m.release("nope")):
            with self.assertRaises(ReservationStateError):
                fn()
        with self.assertRaises(ValueError):
            m.reconcile(m.reserve(P, M).reservation_id, -1)


class RestartAndInterruptionTests(Base):
    def test_usage_survives_restart(self):
        m1 = self.mgr(lim(requests_per_day=2, tokens_per_day=100))
        a = m1.reserve(P, M, 40)
        m1.reconcile(a.reservation_id, 30)
        m1.reserve(P, M, 20)
        del m1
        m2 = self.mgr(lim(requests_per_day=2, tokens_per_day=100))
        u = m2.usage(P, M)
        self.assertEqual((u["day_requests"], u["day_tokens"]), (2, 50))
        self.assertEqual(m2.reserve(P, M, 1).dimension, "requests_per_day")

    def test_interrupted_reservation_is_abandoned_but_still_counts(self):
        m1 = self.mgr(lim(requests_per_day=1), reservation_ttl_s=300)
        rid = m1.reserve(P, M, 10).reservation_id
        del m1                                             # "crash": never reconciled
        self.clock.t += 301
        m2 = self.mgr(lim(requests_per_day=1), reservation_ttl_s=300)
        self.assertEqual(m2.recover_interrupted(), 1)
        self.assertEqual(m2.usage(P, M)["by_status"], {"abandoned": 1})
        self.assertEqual(m2.reserve(P, M).status, DEFERRED)   # fail closed: may have been sent
        m2.reconcile(rid, 7)                                   # late response still reconciles
        self.assertEqual(m2.usage(P, M)["by_status"], {"committed": 1})

    def test_abandoned_can_be_released_when_never_sent(self):
        m = self.mgr(lim(requests_per_day=1), reservation_ttl_s=10)
        rid = m.reserve(P, M).reservation_id
        self.clock.t += 11
        self.assertEqual(m.recover_interrupted(), 1)
        m.release(rid)
        self.assertTrue(m.reserve(P, M).granted)

    def test_fresh_reservation_is_not_recovered(self):
        m = self.mgr()
        m.reserve(P, M)
        self.assertEqual(m.recover_interrupted(), 0)

    def test_reserve_itself_abandons_stale_reservations(self):
        m = self.mgr(lim(requests_per_day=5), reservation_ttl_s=10)
        m.reserve(P, M)
        self.clock.t += 11
        m.reserve(P, M)
        self.assertEqual(m.usage(P, M)["by_status"], {"abandoned": 1, "reserved": 1})


class ConcurrencyTests(Base):
    def test_threads_never_exceed_daily_limit(self):
        m = UsageManager(self.db, [lim(requests_per_day=7, tokens_per_day=70)], clock=self.clock)
        results, gate = [], threading.Barrier(32)

        def work():
            gate.wait()
            results.append(m.reserve(P, M, 10).status)
        threads = [threading.Thread(target=work) for _ in range(32)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(results.count(GRANTED), 7)
        self.assertEqual(results.count(DEFERRED), 25)
        u = m.usage(P, M)
        self.assertEqual((u["day_requests"], u["day_tokens"]), (7, 70))

    def test_separate_processes_share_one_limit(self):
        UsageManager(self.db, [lim(requests_per_day=5)], clock=self.clock)
        code = (
            "import sys\n"
            f"sys.path.insert(0, {str(ROOT)!r})\n"
            "from vm1.e6v2_budget import ModelLimits, UsageManager\n"
            f"m = UsageManager({self.db!r}, [ModelLimits({P!r}, {M!r}, cost_class='free_tier', requests_per_day=5)],"
            " clock=lambda: 1000000.0)\n"
            f"print(sum(m.reserve({P!r}, {M!r}).granted for _ in range(4)))\n")
        procs = [subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True) for _ in range(4)]
        granted = sum(int(p.communicate()[0]) for p in procs)
        self.assertEqual(granted, 5)


class IsolationTests(unittest.TestCase):
    def test_package_is_stdlib_plus_guard_only(self):
        pkg = ROOT / "vm1" / "e6v2_budget"
        for path in pkg.glob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    for a in node.names:
                        self.assertIn(a.name.split(".")[0], sys.stdlib_module_names)
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    self.assertIn((node.module or "").split(".")[0], sys.stdlib_module_names)
                elif isinstance(node, ast.ImportFrom) and node.level == 2:
                    self.assertEqual(node.module, "guard")
            src = path.read_text(encoding="utf-8")
            for token in ("urllib", "http.client", "socket", "import requests", "os.environ"):
                self.assertNotIn(token, src, f"{path.name} contains {token}")


if __name__ == "__main__":
    unittest.main()
