"""Persistent $0 AI usage manager.

* The allowlist AND every limit come from configuration (``ModelLimits``); no vendor quota is built in.
  A model that is not configured is rejected. A model whose ``cost_class`` is not explicitly
  ``"free_tier"`` is refused at configuration time (``PaidApiBlocked``): there is no default, no paid
  switch and no code path that enables paid usage.
* Tracked per (provider, model): requests, tokens and Cloudflare-style neurons, each as its own counter
  with its own optional limit (requests/min, requests/day, tokens/min, tokens/day, neurons/day). A limit
  left as ``None`` is simply not enforced (usage is still recorded); at least one limit is required.
* ``reserve`` checks limits and inserts the reservation inside one ``BEGIN IMMEDIATE`` transaction, so
  concurrent threads/processes sharing the database file can never jointly overshoot a limit.
* A reservation counts at its estimate until ``reconcile`` replaces it with actual usage. ``release``
  returns it (request provably never sent). A reservation left ``reserved`` past the TTL (crash, kill)
  becomes ``abandoned`` and KEEPS counting at its estimate: fail closed, since the request may have been sent.
* When a limit is exhausted ``reserve`` returns ``deferred`` with ``retry_after_s``; an estimate larger
  than a limit can never fit and is ``rejected``.
* Minute limits use a rolling 60 s window; day limits use the UTC day shifted by ``day_utc_offset_minutes``
  (configure to match the provider's reset). Time comes from an injectable ``clock``.
"""

from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Callable, Iterable

from ..guard import PaidApiBlocked

COST_CLASS_FREE_TIER = "free_tier"
GRANTED, DEFERRED, REJECTED = "granted", "deferred", "rejected"
_COUNTED = ("reserved", "abandoned", "committed")
_LIMIT_FIELDS = ("requests_per_minute", "requests_per_day", "tokens_per_minute", "tokens_per_day",
                 "neurons_per_day")
WINDOW_S = 60.0
DAY_S = 86400.0


class ConfigError(ValueError):
    """Invalid usage configuration."""


class ReservationStateError(RuntimeError):
    """Operation not valid for the reservation's current state (or unknown id)."""


@dataclass(frozen=True)
class ModelLimits:
    provider: str
    model: str
    cost_class: str = ""  # must be set explicitly to "free_tier"
    requests_per_minute: int | None = None
    requests_per_day: int | None = None
    tokens_per_minute: int | None = None
    tokens_per_day: int | None = None
    neurons_per_day: int | None = None

    def __post_init__(self):
        if not self.provider or not self.model:
            raise ConfigError("provider and model are required")
        if self.cost_class != COST_CLASS_FREE_TIER:
            raise PaidApiBlocked(
                f"{self.provider}/{self.model}: cost_class {self.cost_class!r} is not {COST_CLASS_FREE_TIER!r}; "
                "paid or unknown-cost models are never allowed.")
        limits = [getattr(self, f) for f in _LIMIT_FIELDS]
        for f, v in zip(_LIMIT_FIELDS, limits):
            if v is not None and (isinstance(v, bool) or not isinstance(v, int) or v < 0):
                raise ConfigError(f"{self.provider}/{self.model}: {f} must be a non-negative int or None")
        if all(v is None for v in limits):
            raise ConfigError(f"{self.provider}/{self.model}: configure at least one limit")

    @property
    def key(self) -> tuple:
        return (self.provider, self.model)


@dataclass(frozen=True)
class ReserveResult:
    status: str                      # granted | deferred | rejected
    reason: str = ""
    reservation_id: str = ""
    dimension: str = ""              # which limit blocked (deferred / rejected)
    retry_after_s: float | None = None

    @property
    def granted(self) -> bool:
        return self.status == GRANTED


_SCHEMA = """
CREATE TABLE IF NOT EXISTS reservations (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL, model TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('reserved','committed','released','abandoned')),
    est_tokens INTEGER NOT NULL, est_neurons INTEGER NOT NULL,
    tokens INTEGER NOT NULL, neurons INTEGER NOT NULL,      -- counted values: estimate, then actual
    created_at REAL NOT NULL, updated_at REAL NOT NULL, day_key INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS idx_res_pm_time ON reservations (provider, model, created_at);
CREATE INDEX IF NOT EXISTS idx_res_pm_day ON reservations (provider, model, day_key);
"""


class UsageManager:
    def __init__(self, db_path: str, models: Iterable[ModelLimits], *, clock: Callable[[], float] = time.time,
                 day_utc_offset_minutes: int = 0, reservation_ttl_s: float = 300.0, busy_timeout_s: float = 30.0):
        if db_path == ":memory:" or not db_path:
            raise ConfigError("a file path is required (in-memory databases are not durable or shareable)")
        self._models: dict = {}
        for m in models:
            if not isinstance(m, ModelLimits):
                raise ConfigError("models must be ModelLimits")
            if m.key in self._models:
                raise ConfigError(f"duplicate model {m.key}")
            self._models[m.key] = m
        self._path, self._clock = db_path, clock
        self._offset_s = int(day_utc_offset_minutes) * 60
        self._ttl, self._busy = float(reservation_ttl_s), float(busy_timeout_s)
        con = self._connect()
        try:
            con.execute("PRAGMA journal_mode=WAL")
            con.executescript(_SCHEMA)
        finally:
            con.close()

    # ---- plumbing ------------------------------------------------------------------------------------
    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self._path, timeout=self._busy, isolation_level=None)
        con.execute(f"PRAGMA busy_timeout={int(self._busy * 1000)}")
        return con

    def _day_key(self, now: float) -> int:
        return int((now + self._offset_s) // DAY_S)

    def _next_day_start(self, now: float) -> float:
        return (self._day_key(now) + 1) * DAY_S - self._offset_s

    def _abandon_stale(self, con: sqlite3.Connection, now: float, max_age: float) -> int:
        return con.execute("UPDATE reservations SET status='abandoned', updated_at=? "
                           "WHERE status='reserved' AND created_at<=?", (now, now - max_age)).rowcount

    # ---- reserve -------------------------------------------------------------------------------------
    def reserve(self, provider: str, model: str, est_tokens: int = 0, est_neurons: int = 0) -> ReserveResult:
        cfg = self._models.get((provider, model))
        if cfg is None:
            return ReserveResult(REJECTED, "model_not_allowlisted")
        for v in (est_tokens, est_neurons):
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                return ReserveResult(REJECTED, "invalid_estimate")
        asks = {"requests_per_minute": 1, "requests_per_day": 1, "tokens_per_minute": est_tokens,
                "tokens_per_day": est_tokens, "neurons_per_day": est_neurons}
        limits = {f: getattr(cfg, f) for f in _LIMIT_FIELDS if getattr(cfg, f) is not None}
        for f, lim in limits.items():
            if asks[f] > lim:
                return ReserveResult(REJECTED, "estimate_exceeds_limit", dimension=f)

        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                now = self._clock()
                self._abandon_stale(con, now, self._ttl)
                day = self._day_key(now)
                d_req, d_tok, d_neu = con.execute(
                    "SELECT COUNT(*), COALESCE(SUM(tokens),0), COALESCE(SUM(neurons),0) FROM reservations "
                    "WHERE provider=? AND model=? AND day_key=? AND status IN (?,?,?)",
                    (provider, model, day, *_COUNTED)).fetchone()
                window = con.execute(
                    "SELECT created_at, tokens FROM reservations WHERE provider=? AND model=? AND created_at>? "
                    "AND status IN (?,?,?) ORDER BY created_at", (provider, model, now - WINDOW_S, *_COUNTED)
                ).fetchall()
                used = {"requests_per_day": d_req, "tokens_per_day": d_tok, "neurons_per_day": d_neu,
                        "requests_per_minute": len(window), "tokens_per_minute": sum(t for _, t in window)}
                worst: tuple | None = None   # (wait, dimension)
                for f, lim in limits.items():
                    if used[f] + asks[f] <= lim:
                        continue
                    if f.endswith("_per_day"):
                        wait = self._next_day_start(now) - now
                    else:
                        wait = self._window_wait(f, window, used[f], asks[f], lim, now)
                    if worst is None or wait > worst[0]:
                        worst = (wait, f)
                if worst is not None:
                    con.execute("COMMIT")
                    return ReserveResult(DEFERRED, "limit_exhausted", dimension=worst[1],
                                         retry_after_s=round(max(worst[0], 0.0), 3))
                rid = uuid.uuid4().hex
                con.execute("INSERT INTO reservations VALUES (?,?,?,'reserved',?,?,?,?,?,?,?)",
                            (rid, provider, model, est_tokens, est_neurons, est_tokens, est_neurons, now, now, day))
                con.execute("COMMIT")
                return ReserveResult(GRANTED, "reserved", reservation_id=rid)
            except BaseException:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()

    @staticmethod
    def _window_wait(field: str, window: list, used: int, ask: int, limit: int, now: float) -> float:
        """Seconds until enough of the oldest in-window usage ages out for ``ask`` to fit."""
        total = used
        for created, tokens in window:
            total -= 1 if field == "requests_per_minute" else tokens
            if total + ask <= limit:
                return created + WINDOW_S - now
        return WINDOW_S

    # ---- settle --------------------------------------------------------------------------------------
    def _settle(self, rid: str, status: str, tokens: int | None, neurons: int | None) -> None:
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            try:
                row = con.execute("SELECT status FROM reservations WHERE id=?", (rid,)).fetchone()
                if row is None:
                    raise ReservationStateError(f"unknown reservation {rid!r}")
                if row[0] not in ("reserved", "abandoned"):
                    raise ReservationStateError(f"reservation {rid!r} is already {row[0]}")
                if status == "committed":
                    con.execute("UPDATE reservations SET status=?, tokens=?, neurons=?, updated_at=? WHERE id=?",
                                (status, tokens, neurons, self._clock(), rid))
                else:
                    con.execute("UPDATE reservations SET status=?, updated_at=? WHERE id=?",
                                (status, self._clock(), rid))
                con.execute("COMMIT")
            except BaseException:
                con.execute("ROLLBACK")
                raise
        finally:
            con.close()

    def reconcile(self, reservation_id: str, actual_tokens: int, actual_neurons: int = 0) -> None:
        """Replace the estimate with actual usage. Also valid for an abandoned reservation whose response
        arrived late. Actuals above the estimate are recorded as-is (accounting stays truthful)."""
        for v in (actual_tokens, actual_neurons):
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise ValueError("actual usage must be a non-negative int")
        self._settle(reservation_id, "committed", actual_tokens, actual_neurons)

    def release(self, reservation_id: str) -> None:
        """Return a reservation whose request was provably never sent."""
        self._settle(reservation_id, "released", None, None)

    def recover_interrupted(self, max_age_s: float | None = None) -> int:
        """Mark reservations still ``reserved`` after ``max_age_s`` (default: the TTL) as ``abandoned``.
        They keep counting at their estimate. Returns how many changed."""
        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            n = self._abandon_stale(con, self._clock(), self._ttl if max_age_s is None else max_age_s)
            con.execute("COMMIT")
            return n
        finally:
            con.close()

    # ---- reporting -----------------------------------------------------------------------------------
    def usage(self, provider: str, model: str) -> dict:
        """Counted usage for the current day plus lifetime counts by status."""
        con = self._connect()
        try:
            day = self._day_key(self._clock())
            r, t, n = con.execute(
                "SELECT COUNT(*), COALESCE(SUM(tokens),0), COALESCE(SUM(neurons),0) FROM reservations "
                "WHERE provider=? AND model=? AND day_key=? AND status IN (?,?,?)",
                (provider, model, day, *_COUNTED)).fetchone()
            by_status = dict(con.execute("SELECT status, COUNT(*) FROM reservations WHERE provider=? AND model=? "
                                         "GROUP BY status", (provider, model)).fetchall())
        finally:
            con.close()
        return {"provider": provider, "model": model, "day_requests": r, "day_tokens": t, "day_neurons": n,
                "by_status": by_status}
