"""Development-only snapshot capture and OFFLINE replay of first-party page fetches.

Purpose: re-run page selection, evidence extraction, scoring and reporting against the SAME fetched pages
without recrawling. This is a developer tool, not a discovery or relevance result.

Capture
* Wraps the real transport UNDER PoliteFetcher, so robots.txt, SSRF validation, DNS pinning, TLS verification,
  size caps, redirect rules and per-host rate limits all still apply exactly as in a live run.
* Records every HTTP hop (robots.txt, redirects, pages) and failures (network errors, non-200, too large).
* Stores a REDACTED copy: no request headers, cookies or credentials; only whitelisted response headers;
  e-mail addresses, mailto:/tel: links and <script> bodies (except JSON-LD) are removed from stored HTML.
* Local, git-ignored directory only; the manifest carries retention notes and the replay refuses stale captures.

Replay
* Serves captured responses with NO network access. A request that was not captured raises SnapshotMissing
  (or, with strict=False, is recorded and returned as an explicit 'snapshot_missing' failure). Nothing is
  invented and nothing is silently fetched.
* Evidence timestamps are the ORIGINAL capture times; runs are labelled mode 'replay' and are never counted
  as fresh autonomous discovery or as an independent live relevance result.
"""

from __future__ import annotations

import hashlib
import json
import re
import socket
import ssl
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from . import USER_AGENT, __version__
from .discovery import Adapter, Candidate
from .fetch import NETWORK_ERRORS, FetchResult, PoliteFetcher, RawResponse, Transport, _decode, utc_now_iso
from .netsafe import Target
from .policy import IcpPolicy

SCHEMA = 1
KEEP_HEADERS = ("content-type", "location", "content-length", "content-language", "last-modified")
DEFAULT_MAX_AGE_DAYS = 30
RETENTION_NOTE = ("Local development snapshot of third-party first-party web pages, redacted of e-mail addresses, "
                  "mailto:/tel: links and scripts. Do not commit, share or publish. Delete when no longer needed; "
                  "replay refuses captures older than the configured max age.")

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_MAILTO_RE = re.compile(r"""(?i)\b(?:mailto|tel|sms):[^"'\s>]*""")
_SCRIPT_RE = re.compile(r"(?is)<script\b([^>]*)>.*?</script\s*>")
_JSONLD_ATTR_RE = re.compile(r"""(?i)type\s*=\s*["']?application/ld\+json""")


class SnapshotMissing(Exception):
    """A page the current code wants was not captured. Never swallowed by the fetcher."""


class SnapshotStale(Exception):
    pass


def redact_html(text: str) -> str:
    """Remove data a research replay does not need: emails, mailto/tel links, scripts (JSON-LD kept)."""
    def script(m: re.Match) -> str:
        return m.group(0) if _JSONLD_ATTR_RE.search(m.group(1) or "") else ""
    text = _SCRIPT_RE.sub(script, text)
    text = _MAILTO_RE.sub("", text)
    return _EMAIL_RE.sub("[redacted-email]", text)


def _key(method: str, url: str) -> str:
    return hashlib.sha256(f"{method.upper()} {url}".encode()).hexdigest()[:32]


class SnapshotStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.dir = self.root / "responses"

    def put(self, entry: dict, body: bytes) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        k = _key(entry["method"], entry["url"])
        entry = dict(entry, body_sha256=hashlib.sha256(body).hexdigest(), body_bytes=len(body))
        (self.dir / f"{k}.body").write_bytes(body)
        (self.dir / f"{k}.json").write_text(json.dumps(entry, indent=1, ensure_ascii=False), encoding="utf-8")

    def get(self, method: str, url: str) -> tuple[dict, bytes] | None:
        k = _key(method, url)
        meta = self.dir / f"{k}.json"
        if not meta.exists():
            return None
        entry = json.loads(meta.read_text(encoding="utf-8"))
        body = (self.dir / f"{k}.body").read_bytes()
        if hashlib.sha256(body).hexdigest() != entry.get("body_sha256"):
            raise ValueError(f"snapshot body for {url} does not match its recorded hash (store was modified)")
        return entry, body

    def entries(self) -> list[dict]:
        if not self.dir.exists():
            return []
        return [json.loads(p.read_text(encoding="utf-8")) for p in sorted(self.dir.glob("*.json"))]

    def read_manifest(self) -> dict:
        return json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))

    def write_manifest(self, manifest: dict) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "manifest.json").write_text(json.dumps(manifest, indent=1, ensure_ascii=False), encoding="utf-8")


class RecordingTransport:
    """Wraps the real transport; stores a redacted copy of every response. Behaviour toward the caller is unchanged."""

    def __init__(self, inner: Transport, store: SnapshotStore, now=utc_now_iso):
        self.inner, self.store, self.now = inner, store, now

    def request(self, method, target: Target, headers, body, timeout, max_bytes) -> RawResponse:
        at = self.now()
        base = {"schema": SCHEMA, "method": method.upper(), "url": target.url, "captured_at": at}
        try:
            raw = self.inner.request(method, target, headers, body, timeout, max_bytes)
        except NETWORK_ERRORS as exc:
            self.store.put({**base, "status": None, "headers": {}, "truncated": False,
                            "error": {"type": type(exc).__name__}, "redacted": False}, b"")
            raise
        hdrs = {k: v for k, v in raw.headers.items() if k.lower() in KEEP_HEADERS}
        ctype = hdrs.get("content-type", "").lower()
        if "text/html" in ctype or "application/xhtml" in ctype:
            stored = redact_html(_decode(raw)).encode("utf-8")
            hdrs["content-type"] = "text/html; charset=utf-8"
            redacted = True
        elif ctype.startswith("text/plain"):
            stored, redacted = redact_html(_decode(raw)).encode("utf-8"), True  # robots.txt etc.
            hdrs["content-type"] = "text/plain; charset=utf-8"
        else:
            stored, redacted = b"", False  # non-HTML bodies are never used; keep metadata only
        self.store.put({**base, "status": raw.status, "headers": hdrs, "truncated": raw.truncated,
                        "error": None, "redacted": redacted, "original_bytes": len(raw.body)}, stored)
        return raw


_ERROR_CLASSES = {"TimeoutError": TimeoutError, "timeout": socket.timeout, "SSLError": ssl.SSLError,
                  "ConnectionResetError": ConnectionResetError, "ConnectionRefusedError": ConnectionRefusedError,
                  "gaierror": socket.gaierror}


class ReplayTransport:
    """Serves captured responses. Opens no sockets. Uncaptured requests raise SnapshotMissing."""

    def __init__(self, store: SnapshotStore):
        self.store = store
        self.served: list[str] = []
        self.missing: list[str] = []

    def request(self, method, target: Target, headers, body, timeout, max_bytes) -> RawResponse:
        got = self.store.get(method, target.url)
        if got is None:
            self.missing.append(target.url)
            raise SnapshotMissing(f"not captured: {method.upper()} {target.url}")
        entry, stored = got
        self.served.append(target.url)
        if entry.get("error"):
            raise _ERROR_CLASSES.get(entry["error"]["type"], OSError)(f"replayed {entry['error']['type']}")
        return RawResponse(entry["status"], dict(entry["headers"]), stored, bool(entry.get("truncated")))


def replay_resolver_for(unresolvable: set[str]):
    """No DNS in replay. SSRF URL validation still runs; a fixed public address satisfies the IP check, except for
    hosts that failed to resolve at capture time (recorded in the manifest), which fail the same way again."""
    def resolve(host: str) -> list[str]:
        return [] if host.lower() in unresolvable else ["1.1.1.1"]
    return resolve


def replay_resolver(host: str) -> list[str]:
    return replay_resolver_for(set())(host)


class ReplayFetcher(PoliteFetcher):
    """PoliteFetcher over a ReplayTransport: same robots/redirect/size logic, original timestamps."""

    def __init__(self, store: SnapshotStore, *, strict: bool = True):
        self.store = store
        self.strict = strict
        self.replay = ReplayTransport(store)
        try:
            manifest = store.read_manifest()
            unresolvable = set(manifest.get("unresolvable_hosts", []))
            # Failed DNS/robots checks never reach RecordingTransport, hence have no
            # per-response timestamp. Use the *recorded capture start*, not replay wall time.
            self.capture_started_at = manifest["started_at"]
        except FileNotFoundError:
            unresolvable = set()
            self.capture_started_at = ""
        super().__init__(self.replay, replay_resolver_for(unresolvable), min_delay=0.0, sleep=lambda s: None)

    @property
    def missing(self) -> list[str]:
        return list(dict.fromkeys(self.replay.missing))

    def fetch(self, url: str) -> FetchResult:
        try:
            res = super().fetch(url)
        except SnapshotMissing as exc:
            if self.strict:
                raise SnapshotMissing(f"{exc}. The current code selected a page that the capture did not fetch. "
                                      "Re-capture with a larger --capture-pages, or capture this page explicitly.") from exc
            return FetchResult(url=url, error=f"snapshot_missing: {exc}", fetched_at=self.capture_started_at)
        got = self.store.get("GET", res.final_url or url) or self.store.get("GET", url)
        if got:
            res.fetched_at = got[0]["captured_at"]  # provenance: ORIGINAL capture time, not replay time
        else:
            # No GET response is recorded for DNS failures, robots refusals or URL-level failures.
            # These must also replay deterministically even when runs cross a wall-clock second.
            res.fetched_at = self.capture_started_at
        return res


class ReplayAdapter(Adapter):
    """Re-emits the capture's candidate list. Labelled 'replay': never counted as automated discovery."""

    name = "snapshot_replay"

    def __init__(self, store: SnapshotStore):
        self.store = store

    def discover(self) -> list[Candidate]:
        man = self.store.read_manifest()
        out = []
        for c in man["candidates"]:
            attrs = dict(c.get("attrs") or {})
            attrs["original_discovery_method"] = c.get("discovery_method")
            out.append(Candidate(name=c["name"], url=c["url"], discovery_method="replay",
                                 source=f"snapshot:{man['capture_id']}", source_id=c.get("source_id", ""),
                                 source_url=c.get("source_url", ""), source_license=c.get("source_license", ""),
                                 retrieved_at=man["started_at"], attrs=attrs))
        return out


def check_fresh(store: SnapshotStore, max_age_days: float | None = DEFAULT_MAX_AGE_DAYS) -> dict:
    man = store.read_manifest()
    if man.get("schema") != SCHEMA:
        raise SnapshotStale(f"unsupported snapshot schema {man.get('schema')!r}")
    if max_age_days is not None:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(man["started_at"])).total_seconds() / 86400
        if age > max_age_days:
            raise SnapshotStale(f"capture is {age:.0f} days old (> {max_age_days:g}); retention policy says re-capture "
                                "or pass --allow-stale after confirming you may still keep it")
    return man


# ---- capture -------------------------------------------------------------------------------------------------
def capture(candidates: list[Candidate], fetcher: PoliteFetcher, store: SnapshotStore, *, capture_pages: int = 8,
            label: str = "", policy: IcpPolicy | None = None) -> dict:
    """Fetch homepage + the top-ranked eligible secondary pages (a SUPERSET of what the normal 4-page budget
    fetches, so selection changes can be replayed) through the recording fetcher. Produces snapshots, no findings."""
    from .pageselect import canonical_key, plan_selection, rank_candidates
    from .htmlparse import parse_html
    from .pipeline import homepage_url

    started = utc_now_iso()
    companies = []
    unresolvable: set[str] = set()
    real_resolver = fetcher.resolver

    def watching(host):  # record hosts that never reach the transport, so replay fails identically
        try:
            ips = real_resolver(host)
        except Exception:
            unresolvable.add(host.lower())
            raise
        if not ips:
            unresolvable.add(host.lower())
        return ips
    fetcher.resolver = watching
    for cand in candidates:
        home_url = homepage_url(cand)
        res = fetcher.fetch(home_url)
        row = {"name": cand.name, "domain": cand.domain, "homepage": home_url, "homepage_ok": res.ok,
               "homepage_error": res.error, "pages": [], "page_errors": {}}
        if res.ok:
            url = res.final_url or home_url
            page = parse_html(res.text or "", url)
            page_policy = policy.page_selection if policy is not None else None
            ranked = rank_candidates(page.links, url, page_policy)
            planned = plan_selection(ranked, 4, page_policy)
            order = [s.url for s in planned] + [s.url for s in ranked if s.url not in {p.url for p in planned}]
            seen = {canonical_key(url)}
            for u in order:
                if len(row["pages"]) >= capture_pages:
                    break
                if canonical_key(u) in seen:
                    continue
                seen.add(canonical_key(u))
                r = fetcher.fetch(u)
                row["pages"].append(u)
                if not r.ok:
                    row["page_errors"][u] = r.error
        companies.append(row)
    fetcher.resolver = real_resolver
    manifest = {
        "schema": SCHEMA, "capture_id": label or started.replace(":", "").replace("-", ""), "started_at": started,
        "ended_at": utc_now_iso(), "tool_version": __version__, "user_agent": USER_AGENT,
        "capture_pages": capture_pages, "unresolvable_hosts": sorted(unresolvable), "candidates": [asdict(c) for c in candidates], "companies": companies,
        "retention": RETENTION_NOTE, "redaction": ["emails", "mailto/tel/sms links", "script bodies except JSON-LD",
                                                   "request headers and cookies never stored"],
        "kind": "development snapshot; not a finding",
        "policy_id": policy.id if policy is not None else None,
        "policy_version": policy.policy_version if policy is not None else None,
        "policy_digest": policy.digest if policy is not None else None,
    }
    store.write_manifest(manifest)
    return manifest
