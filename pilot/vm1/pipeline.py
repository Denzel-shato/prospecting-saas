"""Pipeline: discovery -> canonicalize/dedup -> own-site research -> evidence -> score ->
decision-makers -> unsent drafts -> artifacts. Nothing here can send anything."""

from __future__ import annotations

import hashlib
import json
import platform
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import USER_AGENT, __version__
from .canon import canonical_domain, is_first_party_candidate, normalize_name, registrable_domain
from .discovery import AUTOMATED, Adapter, Candidate, DiscoveryBlocked
from .drafts import build_draft
from .evidence import (PageSnapshot, apply_discovery_record, extract_evidence, verify_evidence,
                       verify_excerpt_parts)
from .fetch import PoliteFetcher
from .guard import SpendLedger, credentials_present
from .prequalify import coverage, order_pool
from .htmlparse import PageData, parse_html
from .people import find_decision_makers
from .score import EXCLUDED, NOT_RESEARCHABLE, score_company

SECONDARY_KEYWORDS = [  # (keyword, priority) lower = fetched first
    ("team", 0), ("leadership", 0), ("people", 0), ("about", 1), ("company", 1), ("who-we-are", 1),
    ("our-story", 1), ("services", 2), ("what-we-do", 2), ("work", 3), ("case-stud", 3),
    ("portfolio", 3), ("contact", 4),
]
_ASSET_RE = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|mp4|mov|docx?|xlsx?|pptx?)$", re.I)


@dataclass
class RunConfig:
    icp: dict
    out_dir: Path
    mode: str = "live"  # live | synthetic_fixture
    max_candidates: int = 40
    seed: str = "vm1-pilot-1"
    max_secondary: int = 4
    draft_count: int = 10
    extra: dict = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def pick_secondary(home: PageData, home_url: str, limit: int) -> list[str]:
    base = registrable_domain(urlsplit(home_url).hostname or "")
    home_path = urlsplit(home_url).path.rstrip("/")
    seen: set[str] = set()
    ranked: list[tuple[int, int, str]] = []
    for href, text in home.links:
        sp = urlsplit(href)
        if registrable_domain(sp.hostname or "") != base:
            continue
        path = sp.path.rstrip("/")
        if not path or path == home_path or _ASSET_RE.search(path):
            continue
        hay = (path + " " + text).lower()
        prio = next((p for kw, p in SECONDARY_KEYWORDS if kw in hay), None)
        if prio is None:
            continue
        norm = f"{sp.scheme}://{sp.netloc}{sp.path}"
        if norm in seen:
            continue
        seen.add(norm)
        ranked.append((prio, len(ranked), norm))
    ranked.sort()
    return [u for _, _, u in ranked[:limit]]


def homepage_url(cand: Candidate) -> str:
    url = cand.url if "://" in cand.url else "https://" + cand.url
    sp = urlsplit(url)
    return f"{sp.scheme}://{sp.netloc}/"


def dedup(candidates: list[Candidate]) -> tuple[list[Candidate], list[dict], list[dict]]:
    kept: dict[str, Candidate] = {}
    rejected: list[dict] = []
    for c in candidates:
        if not c.domain:
            rejected.append({"name": c.name, "url": c.url, "reason": "invalid_or_unresolvable_domain",
                             "method": c.discovery_method})
        elif not is_first_party_candidate(c.domain):
            rejected.append({"name": c.name, "url": c.url, "domain": c.domain,
                             "reason": "non_first_party_domain", "method": c.discovery_method})
        elif c.domain in kept:
            rejected.append({"name": c.name, "url": c.url, "domain": c.domain, "reason": "duplicate_domain",
                             "duplicate_of": kept[c.domain].name, "method": c.discovery_method})
        else:
            kept[c.domain] = c
    by_name: dict[str, list[str]] = {}
    for d, c in kept.items():
        by_name.setdefault(normalize_name(c.name), []).append(d)
    possible_same = [{"normalized_name": n, "domains": ds} for n, ds in by_name.items() if n and len(ds) > 1]
    return list(kept.values()), rejected, possible_same


def select_with_reasons(pool: list[Candidate], max_candidates: int, seed: str) -> tuple[list[Candidate], dict]:
    """Deterministic selection. Candidates are ordered by (record-based prequalification priority,
    seeded hash). With no usable record fields every priority is 0 and the order is the original
    seeded-hash order. Nothing is dropped for being low priority unless the cap is reached."""
    rows = order_pool(pool, seed)
    chosen = rows if len(pool) <= max_candidates else rows[:max_candidates]
    info = {c.domain: {"priority": pri, "reasons": why} for c, pri, why in chosen if pri or why}
    return [c for c, _, _ in chosen], info


def select(pool: list[Candidate], max_candidates: int, seed: str) -> list[Candidate]:
    return select_with_reasons(pool, max_candidates, seed)[0]


def research_company(cand: Candidate, fetcher: PoliteFetcher, icp: dict, max_secondary: int) -> dict:
    key = cand.domain or cand.url
    rec: dict = {
        "domain": key, "name": cand.name, "url": cand.url,
        "discovery": {"method": cand.discovery_method, "source": cand.source, "source_id": cand.source_id,
                      "source_url": cand.source_url, "license": cand.source_license,
                      "retrieved_at": cand.retrieved_at},
        "homepage": {}, "secondary": [], "secondary_links_found": 0,
    }
    snaps: list[PageSnapshot] = []
    pages_by_url: dict[str, PageData] = {}

    home_url = homepage_url(cand)
    res = fetcher.fetch(home_url)
    rec["homepage"] = {"url": home_url, "final_url": res.final_url, "ok": res.ok, "error": res.error,
                       "status": res.status, "fetched_at": res.fetched_at, "robots_allowed": res.robots_allowed}
    if res.ok:
        url = res.final_url or home_url
        page = parse_html(res.text or "", url)
        snaps.append(PageSnapshot(url=url, fetched_at=res.fetched_at, page=page, is_homepage=True))
        pages_by_url[url] = page
        picks = pick_secondary(page, url, max_secondary)
        rec["secondary_links_found"] = len(picks)
        for sec in picks:
            sres = fetcher.fetch(sec)
            rec["secondary"].append({"url": sec, "ok": sres.ok, "error": sres.error, "status": sres.status})
            if sres.ok:
                surl = sres.final_url or sec
                spage = parse_html(sres.text or "", surl)
                snaps.append(PageSnapshot(url=surl, fetched_at=sres.fetched_at, page=spage))
                pages_by_url[surl] = spage

    evidence = extract_evidence(key, snaps, company_name=cand.name)
    evidence = apply_discovery_record(key, cand, evidence)
    verified, dropped = [], 0
    for ev in evidence:
        if verify_evidence(ev, pages_by_url):
            verified.append(ev)
        else:
            dropped += 1
    verified_ids = {e.id for e in verified}

    dms = [d for d in find_decision_makers(snaps, company_key=key, company_name=cand.name)
           if verify_excerpt_parts(d.excerpt_parts, pages_by_url.get(d.source_url))]

    # Only a real robots/crawl-delay refusal is "not researchable". A robots.txt that could not be
    # fetched (timeout, 5xx, network) is an ordinary reachability failure, not a policy refusal.
    robots_blocked = (not res.ok) and (res.error or "").startswith(
        ("robots: disallowed", "robots: crawl_delay"))
    band = tuple(icp.get("size_band", (5, 50)))
    score = score_company(
        verified, dms, homepage_ok=res.ok, robots_blocked=robots_blocked,
        first_party_domain=is_first_party_candidate(cand.domain), size_band=band,  # type: ignore[arg-type]
        size_hard_max=icp.get("size_hard_max", 250))

    rec.update({"evidence": [e.to_dict() for e in verified], "dropped_unverifiable_evidence": dropped,
                "verified_evidence_ids": sorted(verified_ids),
                "decision_makers": [d.to_dict() for d in dms], "score": score.to_dict(),
                "tier": score.tier, "total": score.total, "company_type": score.company_type})
    return rec


def rank(companies: list[dict]) -> list[dict]:
    elig = [c for c in companies if c["total"] is not None]
    return sorted(elig, key=lambda c: (-c["total"], c["domain"]))


def run_pipeline(cfg: RunConfig, adapters: list[Adapter], fetcher: PoliteFetcher,
                 ledger: SpendLedger | None = None) -> dict:
    ledger = ledger or SpendLedger()
    t0 = time.monotonic()
    started = _now()
    stage: dict[str, float] = {}
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{cfg.mode}"
    out = Path(cfg.out_dir) / run_id
    out.mkdir(parents=True, exist_ok=True)

    # 1. discovery
    t = time.monotonic()
    discovered: list[Candidate] = []
    discovery_status: list[dict] = []
    for ad in adapters:
        st = {"adapter": ad.name, "cost_class": ad.cost_class, "terms_note": ad.terms_note,
              "license": ad.license_note}
        try:
            got = ad.discover()
            st.update(status="ok", count=len(got))
            if getattr(ad, "run_note", ""):
                st["note"] = ad.run_note
            discovered.extend(got)
        except DiscoveryBlocked as exc:
            st.update(status="blocked", count=0, reason=str(exc))
        discovery_status.append(st)
        ledger.record(ad.name, 0.0, "keyless adapter")
    stage["discovery_s"] = round(time.monotonic() - t, 2)

    # 2. canonicalize / dedup / select
    pool, rejected, possible_same = dedup(discovered)
    selected, selection_info = select_with_reasons(pool, cfg.max_candidates, cfg.seed)

    # 3. research
    t = time.monotonic()
    companies = [research_company(c, fetcher, cfg.icp, cfg.max_secondary) for c in selected]
    stage["research_s"] = round(time.monotonic() - t, 2)

    # 4. rank + drafts
    ranked = rank(companies)
    t = time.monotonic()
    drafts = []
    cand_by_domain = {c.domain: c for c in selected}
    for c in ranked:
        if len(drafts) >= cfg.draft_count:
            break
        if c["tier"] not in ("strong", "possible"):
            continue
        from .evidence import Evidence
        evs = [Evidence(**e) for e in c["evidence"]]
        dms = c["decision_makers"]
        from .people import DecisionMaker
        dm_objs = [DecisionMaker(**d) for d in dms]
        d = build_draft(domain=c["domain"], company_name=cand_by_domain[c["domain"]].name, evidence=evs,
                        verified_ids=set(c["verified_evidence_ids"]), decision_makers=dm_objs)
        if d:
            drafts.append(d.to_dict())
    stage["drafts_s"] = round(time.monotonic() - t, 2)

    manifest = {
        "run_id": run_id, "mode": cfg.mode, "started_at": started, "ended_at": _now(),
        "elapsed_s": round(time.monotonic() - t0, 2), "stage_elapsed_s": stage,
        "version": __version__, "python": platform.python_version(), "user_agent": USER_AGENT,
        "icp_id": cfg.icp.get("id"), "seed": cfg.seed, "max_candidates": cfg.max_candidates,
        "discovery_status": discovery_status,
        "counts": {"discovered_raw": len(discovered), "after_dedup_pool": len(pool),
                   "rejected": len(rejected), "selected": len(selected),
                   "selected_automated": sum(1 for c in selected if c.discovery_method == AUTOMATED),
                   "selected_manual": sum(1 for c in selected if c.discovery_method == "manual"),
                   "selected_synthetic": sum(1 for c in selected if c.discovery_method == "synthetic_fixture"),
                   "raw_automated": sum(1 for c in discovered if c.discovery_method == AUTOMATED)},
        "http_requests_logged": len(fetcher.log), "paid_api_spend_usd": ledger.total_usd,
        "spend_ledger_entries": len(ledger.entries),
        "credentials_detected_in_env_but_ignored": credentials_present(),
        "selection_method": "prequalify priority (record description/listing/headcount) then seeded hash",
        "selection_priorities": selection_info,
        "discovery_coverage": coverage(pool),
        "possible_same_company_different_domain": possible_same,
        "sending": "none: this prototype contains no email/Gmail/SMTP code path",
    }
    _write_json(out / "manifest.json", manifest)
    _write_json(out / "candidates.json", [asdict(c) for c in selected])
    _write_json(out / "rejected.json", rejected)
    _write_json(out / "companies.json", companies)
    _write_json(out / "drafts.json", drafts)
    with (out / "fetch_log.jsonl").open("w", encoding="utf-8") as fh:
        for row in fetcher.log:
            fh.write(json.dumps(row) + "\n")
    (out / "drafts").mkdir(exist_ok=True)
    from .drafts import Draft
    for d in drafts:
        (out / "drafts" / f"{d['domain']}.txt").write_text(Draft(**d).to_text(), encoding="utf-8")
    return {"run_dir": str(out), "manifest": manifest, "companies": companies, "drafts": drafts,
            "rejected": rejected}


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
