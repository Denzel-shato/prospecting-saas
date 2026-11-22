"""Offline ICP requalification: re-score STORED verified evidence without fetching or discovering anything.

This is NOT a new relevance measurement. The source's evidence/extraction may be incomplete
for the new ICP; missing facts stay unknown. Historical discovery counts are provenance only.
No drafts are regenerated (templates have not been validated for another ICP).
"""

from __future__ import annotations

import copy
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .canon import is_first_party_candidate
from .evidence import Evidence
from .people import DecisionMaker
from .policy import IcpPolicy, load_policy
from .report import load_run, write_report
from .score import score_company


def requalify_run(source_dir: str | Path, policy: IcpPolicy | dict | str, out_root: str | Path) -> Path:
    """Return the new *run directory*. No network, discovery or raw-page processing occurs."""
    pol = load_policy(policy)  # validate before writing anything
    run = load_run(source_dir)
    original = run["manifest"]
    if original.get("mode") not in ("live", "replay", "synthetic_fixture", "requalify"):
        raise ValueError(f"unsupported source run mode {original.get('mode')!r}")
    if not isinstance(run["companies"], list):
        raise ValueError("source companies.json must contain a list")

    companies: list[dict] = []
    for original_company in run["companies"]:
        c = copy.deepcopy(original_company)
        evidence = [Evidence(**e) for e in c["evidence"]]
        people = [DecisionMaker(**d) for d in c["decision_makers"]]
        home = c.get("homepage") or {}
        error = home.get("error") or ""
        before = {"policy_id": original.get("icp_id"), "tier": c["tier"], "total": c["total"],
                  "company_type": c.get("company_type")}
        result = score_company(
            evidence, people, homepage_ok=bool(home.get("ok")),
            robots_blocked=not home.get("ok") and error.startswith(("robots: disallowed", "robots: crawl_delay")),
            first_party_domain=is_first_party_candidate(c["domain"]), policy=pol,
        )
        c.update(score=result.to_dict(), tier=result.tier, total=result.total, company_type=result.company_type)
        c["requalification"] = {"original": before, "evidence_reextracted": False, "pages_refetched": False}
        companies.append(c)

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    manifest = copy.deepcopy(original)
    manifest.update(
        run_id="", mode="requalify", started_at=now, ended_at=now,
        icp_id=pol.id, policy_version=pol.policy_version, policy_digest=pol.digest,
        policy_source_format=pol.source_format,
        http_requests_logged=0, paid_api_spend_usd=0.0, spend_ledger_entries=0,
        credentials_detected_in_env_but_ignored=[],
        elapsed_s=0.0, stage_elapsed_s={"requalification_s": 0.0},
        # Original record-term coverage belongs to the source ICP, not the newly selected policy.
        # Preserve it in lineage but do not present it as if it described the new target market.
        discovery_coverage={},
        requalification={
            "source_run_id": original.get("run_id"),
            "source_mode": original.get("mode"),
            "source_icp_id": original.get("icp_id"),
            "source_policy_digest": original.get("policy_digest"),
            "source_http_requests_logged": original.get("http_requests_logged"),
            "source_discovery_coverage": original.get("discovery_coverage"),
            "counts_as_fresh_discovery": False,
            "counts_as_independent_live_result": False,
            "stored_evidence_only": True,
            "no_network_or_reextraction": True,
        },
    )
    root = Path(out_root)
    root.mkdir(parents=True, exist_ok=True)
    prefix = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-requalify-"
    out = Path(tempfile.mkdtemp(prefix=prefix, dir=root))
    manifest["run_id"] = out.name

    def write(name: str, data) -> None:
        (out / name).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    write("manifest.json", manifest)
    write("companies.json", companies)
    write("candidates.json", run["candidates"])
    write("rejected.json", run["rejected"])
    write("drafts.json", [])
    (out / "drafts").mkdir(exist_ok=True)
    (out / "fetch_log.jsonl").write_text("", encoding="utf-8")
    write_report(out)
    return out
