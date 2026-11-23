"""One offline Engine #6 V2 run. See package docstring."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from ..ai import AIProviderError, MockProvider, StructuredRequest
from ..e6v2 import PrepConfig, prepare_evidence
from ..e6v2_verify import ACCEPTED, MANUAL_REVIEW, REJECTED, verify_decision_makers
from ..evidence import PageSnapshot
from ..htmlparse import parse_html
from ..snapshot import SnapshotStore

SCHEMA = {
    "type": "object",
    "required": ["decision_makers"],
    "properties": {"decision_makers": {"type": "array", "items": {
        "type": "object",
        "required": ["name", "role", "company", "passage_id", "quote"],
        "properties": {k: {"type": "string"} for k in ("name", "role", "company", "passage_id", "quote")},
    }}},
}
SYSTEM = ("Extract people who lead the target company from the numbered passages. Use only the passage text. "
          "For each person give the exact passage_id and a verbatim quote containing the name and title. "
          "Return an empty list if none.")


class OfflineOnlyError(RuntimeError):
    """The workflow refuses any provider other than the MockProvider."""


@dataclass
class WorkflowResult:
    company_key: str
    passages: int
    provider_called: bool
    error: str = ""
    accepted: list = field(default_factory=list)
    review: list = field(default_factory=list)
    rejected: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"company_key": self.company_key, "passages": self.passages, "provider_called": self.provider_called,
                "error": self.error, "accepted": self.accepted, "review": self.review, "rejected": self.rejected,
                "counts": {"accepted": len(self.accepted), "review": len(self.review),
                           "rejected": len(self.rejected)}}


def load_snapshots(snapshot_dir: str | Path) -> list[PageSnapshot]:
    """Saved (redacted) snapshot store -> PageSnapshots for its stored HTML 200 pages. No network."""
    store = SnapshotStore(snapshot_dir)
    out = []
    for e in store.entries():
        ctype = (e.get("headers") or {}).get("content-type", "").lower()
        if e.get("method") != "GET" or e.get("status") != 200 or e.get("truncated") or "html" not in ctype:
            continue
        got = store.get("GET", e["url"])
        if got is None:
            continue
        page = parse_html(got[1].decode("utf-8", errors="replace"), e["url"])
        out.append(PageSnapshot(url=e["url"], fetched_at=e.get("captured_at", ""), page=page,
                                is_homepage=urlsplit(e["url"]).path in ("", "/")))
    return sorted(out, key=lambda s: s.url)


def build_request(passages, company_name: str, company_key: str) -> StructuredRequest:
    lines = [f"Target company: {company_name or company_key} ({company_key})", "", "Passages:"]
    for p in passages:
        lines.append(f"[{p.passage_id}] (page: {p.page_kind}; flags: {','.join(p.risk_flags) or 'none'})")
        lines.append(p.text)
        lines.append("")
    return StructuredRequest(prompt="\n".join(lines), schema=SCHEMA, system=SYSTEM, max_tokens=1024)


def _row(v) -> dict:
    return v.to_dict()


def run_offline(snapshots, provider: MockProvider, company_key: str, company_name: str | None = None,
                prep_config: PrepConfig | None = None) -> WorkflowResult:
    if not isinstance(provider, MockProvider):
        raise OfflineOnlyError(f"only MockProvider is allowed offline, got {type(provider).__name__}")
    prep = prepare_evidence(snapshots, prep_config)
    result = WorkflowResult(company_key, len(prep.passages), False)
    if not prep.passages:
        return result
    result.provider_called = True
    try:
        response = provider.generate_structured(build_request(prep.passages, company_name or "", company_key))
    except AIProviderError as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        return result
    for v in verify_decision_makers(response.data, prep, company_key, company_name):
        {ACCEPTED: result.accepted, MANUAL_REVIEW: result.review, REJECTED: result.rejected}[v.status].append(_row(v))
    return result
