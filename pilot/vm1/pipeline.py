"""Pipeline: discovery -> canonicalize/dedup -> own-site research -> evidence -> score ->
decision-makers -> unsent drafts -> artifacts. Nothing here can send anything."""

from __future__ import annotations

import hashlib
import json
import math
import platform
import re
import time
from collections import Counter, deque
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
from .pageselect import canonical_key, plan_selection, project_path, rank_candidates
from .prequalify import Ranked, coverage, rank_pool
from .htmlparse import PageData, parse_html
from .people import find_decision_makers
from .score import EXCLUDED, NOT_RESEARCHABLE, score_company
from .policy import IcpPolicy, load_policy

_ASSET_RE = re.compile(r"\.(pdf|jpe?g|png|gif|svg|webp|zip|mp4|mov|docx?|xlsx?|pptx?)$", re.I)


@dataclass
class RunConfig:
    icp: dict | IcpPolicy
    out_dir: Path
    mode: str = "live"  # live | synthetic_fixture
    max_candidates: int = 40  # companies the run wants ASSESSED (failed attempts are backfilled)
    max_research: int | None = None  # hard cap on research attempts incl. backfill; None -> default_research_budget
    seed: str = "vm1-pilot-1"
    max_secondary: int = 4
    draft_count: int = 10
    extra: dict = field(default_factory=dict)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def rank_secondary(home: PageData, home_url: str) -> list[tuple[int, str]]:
    """All eligible same-site pages, best first, as (priority, url). See vm1.pageselect."""
    return [(c.priority, c.url) for c in rank_candidates(home.links, home_url)]


def pick_secondary(home: PageData, home_url: str, limit: int) -> list[str]:
    """URLs to fetch (<= limit) in fetch order, chosen by the ICP-aware slot plan (Issue #4)."""
    chosen = plan_selection(rank_candidates(home.links, home_url), limit)
    return [c.url for c in chosen]


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
                             "duplicate_of": kept[c.domain].name, "method": c.discovery_method,
                             "source": c.source, "source_id": c.source_id})
        else:
            kept[c.domain] = c
    by_name: dict[str, list[str]] = {}
    for d, c in kept.items():
        by_name.setdefault(normalize_name(c.name), []).append(d)
    possible_same = [{"normalized_name": n, "domains": ds} for n, ds in by_name.items() if n and len(ds) > 1]
    return list(kept.values()), rejected, possible_same


def _selection_info(rows: list[Ranked]) -> dict:
    info = {}
    for r in rows:
        tie = r.tie_break()
        if r.priority or r.reasons or tie:
            entry = {"priority": r.priority, "reasons": r.reasons}
            if tie:
                entry["tie_break"] = tie
            info[r.candidate.domain] = entry
    return info


def prioritize_pool(pool: list[Candidate], seed: str,
                    policy: IcpPolicy | None = None) -> tuple[list[Ranked], dict]:
    """The WHOLE pool, best research candidate first, plus per-domain explanations. Order: record-based
    prequalification priority, ICP-term breadth in the record's text, then seeded hash. With no usable
    record fields every key ties and the order is the original seeded-hash order."""
    rows = rank_pool(pool, seed, policy)
    return rows, _selection_info(rows)


def select_with_reasons(pool: list[Candidate], max_candidates: int, seed: str,
                        policy: IcpPolicy | None = None) -> tuple[list[Candidate], dict]:
    """The first `max_candidates` of prioritize_pool (everything when the pool fits the cap)."""
    rows, _ = prioritize_pool(pool, seed, policy)
    chosen = rows if len(pool) <= max_candidates else rows[:max_candidates]
    return [r.candidate for r in chosen], _selection_info(chosen)


def select(pool: list[Candidate], max_candidates: int, seed: str) -> list[Candidate]:
    return select_with_reasons(pool, max_candidates, seed)[0]


def fetch_secondary_pages(fetcher, home_url, ranked, limit, page_policy):
    """Yield actual selections, responses and parses. A project index may spend one remaining slot."""
    plan = plan_selection(ranked, limit, page_policy)
    known = {canonical_key(s.url): s for s in ranked}
    seen = {canonical_key(home_url)}
    used = 0
    while plan and used < limit:
        sel = plan.pop(0)
        key = canonical_key(sel.url)
        seen.add(key)
        used += 1
        sel.selected, sel.slot = True, used
        res = fetcher.fetch(sel.url)
        url = res.final_url or sel.url
        page = parse_html(res.text or "", url) if res.ok else None
        seen.add(canonical_key(url))
        yield sel, res, page
        if page is not None and used < limit and sel.category == "about":
            children = rank_candidates(page.links, home_url, page_policy)
            child = next((s for s in children if s.category == "team" and canonical_key(s.url) not in seen), None)
            if child is not None:
                child = known.setdefault(canonical_key(child.url), child)
                if child not in ranked:
                    ranked.append(child)
                child.reason += f", linked from {url}"
                plan = [child] + [s for s in plan if canonical_key(s.url) != canonical_key(child.url)]
                while used + len(plan) > limit:
                    displaced = plan.pop()
                    displaced.selected, displaced.slot = False, None
        if (page is None or used >= limit or sel.category != "project_index" or
                project_path(urlsplit(url).path) != "index"):
            continue
        children = rank_candidates(page.links, home_url, page_policy)
        child = next((s for s in children if s.category == "project_detail" and canonical_key(s.url) not in seen), None)
        if child is None:
            continue
        key = canonical_key(child.url)
        detail = known.get(key)
        if detail is None:
            detail = child
            known[key] = child
            ranked.append(detail)
        detail.reason = f"{child.reason}, linked from {url}"
        plan = [detail] + [s for s in plan if s is not detail]
        if used + len(plan) > limit:
            displaced = plan.pop()
            displaced.selected, displaced.slot = False, None


def research_company(cand: Candidate, fetcher: PoliteFetcher,
                     icp: dict | IcpPolicy, max_secondary: int) -> dict:
    policy = load_policy(icp)
    key = cand.domain or cand.url
    rec: dict = {
        "domain": key, "name": cand.name, "url": cand.url,
        "discovery": {"method": cand.discovery_method, "source": cand.source, "source_id": cand.source_id,
                      "source_url": cand.source_url, "license": cand.source_license,
                      "retrieved_at": cand.retrieved_at},
        "homepage": {}, "secondary": [], "secondary_links_found": 0,
    }
    if cand.attrs.get("seed_directory"):  # manual directory seed: keep the directory attribution (not evidence)
        rec["discovery"]["directory"] = dict(cand.attrs["seed_directory"])
        rec["discovery"]["directory_occurrences"] = [
            {k: o[k] for k in ("directory_id", "directory_name", "directory_url", "listing_url", "listed_name",
                               "listed_url")} for o in cand.attrs.get("seed_occurrences", [])]
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
        ranked_sel = rank_candidates(page.links, url, policy.page_selection)
        rec["homepage_text_blocks"] = len(page.blocks)
        fetched_keys = {canonical_key(url): url}  # duplicate FINAL destinations (redirects) are not double-counted
        for sel, sres, spage in fetch_secondary_pages(fetcher, url, ranked_sel, max_secondary, policy.page_selection):
            sec = sel.url
            entry = {"url": sec, "ok": sres.ok, "error": sres.error, "status": sres.status,
                     "category": sel.category, "reason": sel.reason, "slot": sel.slot}
            if spage is not None:
                surl = sres.final_url or sec
                entry.update(final_url=surl, text_blocks=len(spage.blocks), text_chars=len(sres.text or ""),
                             links=len(spage.links))
                dup = fetched_keys.get(canonical_key(surl))
                if dup is not None:
                    entry["duplicate_of"] = dup  # same page already fetched: spent a request, adds no snapshot
                else:
                    fetched_keys[canonical_key(surl)] = surl
                    snaps.append(PageSnapshot(url=surl, fetched_at=sres.fetched_at, page=spage))
                    pages_by_url[surl] = spage
            rec["secondary"].append(entry)
        rec["secondary_links_found"] = len(rec["secondary"])
        # Keep every actual selection visible even when the index supplied a new link after the homepage.
        visible = ranked_sel[:15] + [s for s in ranked_sel[15:] if s.selected]
        rec["secondary_candidates"] = [s.to_dict() for s in visible]

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
    score = score_company(
        verified, dms, homepage_ok=res.ok, robots_blocked=robots_blocked,
        first_party_domain=is_first_party_candidate(cand.domain), policy=policy)

    rec.update({"evidence": [e.to_dict() for e in verified], "dropped_unverifiable_evidence": dropped,
                "verified_evidence_ids": sorted(verified_ids),
                "decision_makers": [d.to_dict() for d in dms], "score": score.to_dict(),
                "tier": score.tier, "total": score.total, "company_type": score.company_type})
    people_pages = [s for s in rec["secondary"] if s.get("category") in {"team", "about"}]
    rec["decision_maker_outcome"] = (
        "named" if dms else "homepage_unreachable" if not res.ok else
        "no_attributable_person_extracted" if any(s.get("ok") for s in people_pages) else
        "people_pages_inaccessible" if people_pages else "no_people_page_fetched")
    return rec


def rank(companies: list[dict]) -> list[dict]:
    elig = [c for c in companies if c["total"] is not None]
    return sorted(elig, key=lambda c: (-c["total"], c["domain"]))


# --- bounded research backfill (Engine #2) -------------------------------------------------------
# `max_candidates` is the number of companies the run wants ASSESSED. A research attempt that yields no
# assessment is replaced by the next candidate in priority order, up to `max_research` attempts in total.
DEFAULT_BACKFILL_RATIO = 0.5  # default extra attempts, as a share of max_candidates (configurable per run)

ASSESSED = "assessed"                # a first-party homepage was read and the company was scored (any tier)
INACCESSIBLE = "inaccessible"        # homepage not fetched: HTTP error such as 403, timeout, TLS/network, redirect
NOT_RESEARCHABLE_ROBOTS = "not_researchable"  # robots.txt/crawl-delay refusal: nothing was fetched
EXCLUDED_BY_EVIDENCE = "excluded"    # fetched, and first-party evidence confirms a hard exclusion rule


def default_research_budget(max_candidates: int) -> int:
    return max_candidates + math.ceil(max(max_candidates, 0) * DEFAULT_BACKFILL_RATIO)


def research_outcome(rec: dict) -> str:
    """Why a research attempt did or did not produce an assessment. Only ASSESSED counts toward the target.
    A weak or low-fit company is still ASSESSED: backfill replaces failed attempts, it never chases tiers."""
    if rec.get("tier") == NOT_RESEARCHABLE:
        return NOT_RESEARCHABLE_ROBOTS
    if not (rec.get("homepage") or {}).get("ok"):
        return INACCESSIBLE
    if rec.get("tier") == EXCLUDED:
        return EXCLUDED_BY_EVIDENCE
    return ASSESSED


def research_with_backfill(ranked: list[Ranked], target: int, budget: int, research) -> tuple[list[dict], list[Candidate], dict]:
    """Research `ranked` in order until `target` companies are assessed, `budget` attempts are spent, or the
    pool is exhausted. Deterministic: the order is fixed up front and each step depends only on the previous
    outcomes. `research(candidate) -> record` is research_company; its fetch protections apply unchanged."""
    companies: list[dict] = []
    researched: list[Candidate] = []
    unreplaced: deque[str] = deque()  # failed attempts not yet matched with a backfill, oldest first
    assessed = 0
    for pos, row in enumerate(ranked, start=1):
        if assessed >= target or len(companies) >= budget:
            break
        rec = research(row.candidate)
        outcome = research_outcome(rec)
        attempt = len(companies) + 1
        meta = {"attempt": attempt, "wave": "initial" if attempt <= target else "backfill",
                "pool_rank": pos, "priority": row.priority, "outcome": outcome}
        if meta["wave"] == "backfill" and unreplaced:
            meta["backfill_for"] = unreplaced.popleft()
        if outcome == ASSESSED:
            assessed += 1
        else:
            unreplaced.append(rec["domain"])
        rec["research_selection"] = meta
        companies.append(rec)
        researched.append(row.candidate)
    stop = "target_met" if assessed >= target else "budget_exhausted" if len(companies) >= budget else "pool_exhausted"
    outcomes = Counter(c["research_selection"]["outcome"] for c in companies)
    plan = {"target_assessed": target, "max_research": budget, "attempted": len(companies), "assessed": assessed,
            "initial_attempted": sum(c["research_selection"]["wave"] == "initial" for c in companies),
            "backfill_attempted": sum(c["research_selection"]["wave"] == "backfill" for c in companies),
            "outcomes": {k: outcomes.get(k, 0) for k in (ASSESSED, INACCESSIBLE, NOT_RESEARCHABLE_ROBOTS,
                                                         EXCLUDED_BY_EVIDENCE)},
            "target_shortfall": max(0, target - assessed), "stop_reason": stop,
            "unresearched_in_pool": len(ranked) - len(companies)}
    return companies, researched, plan


def skipped_records(ranked: list[Ranked], researched: list[Candidate], plan: dict) -> list[dict]:
    """Every pool candidate that was NOT researched, with its rank and why research stopped before it."""
    done = {c.domain for c in researched}
    why = {"target_met": "not_reached: target of assessed companies met",
           "budget_exhausted": "not_reached: research budget exhausted",
           "pool_exhausted": "not_reached"}[plan["stop_reason"]]
    return [{"name": r.candidate.name, "url": r.candidate.url, "domain": r.candidate.domain,
             "method": r.candidate.discovery_method, "source": r.candidate.source,
             "source_id": r.candidate.source_id, "source_url": r.candidate.source_url,
             "pool_rank": pos, "priority": r.priority, "reasons": r.reasons, "skipped_reason": why}
            for pos, r in enumerate(ranked, start=1) if r.candidate.domain not in done]


def run_pipeline(cfg: RunConfig, adapters: list[Adapter], fetcher: PoliteFetcher,
                 ledger: SpendLedger | None = None) -> dict:
    ledger = ledger or SpendLedger()
    policy = load_policy(cfg.icp)  # fail closed on invalid/non-baseline ICPs before discovery or HTTP
    budget = default_research_budget(cfg.max_candidates) if cfg.max_research is None else cfg.max_research
    if budget < cfg.max_candidates:
        raise ValueError(f"max_research ({budget}) must be >= max_candidates ({cfg.max_candidates})")
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
    seed_summaries: list[dict] = []
    for ad in adapters:
        st = {"adapter": ad.name, "cost_class": ad.cost_class, "terms_note": ad.terms_note,
              "license": ad.license_note}
        try:
            got = ad.discover()
            st.update(status="ok", count=len(got))
            if getattr(ad, "run_note", ""):
                st["note"] = ad.run_note
            if getattr(ad, "yield_stats", None):
                st["yield"] = dict(ad.yield_stats)
            discovered.extend(got)
            if hasattr(ad, "seed_summary"):
                seed_summaries.append(ad.seed_summary())
        except DiscoveryBlocked as exc:
            st.update(status="blocked", count=0, reason=str(exc))
        discovery_status.append(st)
        ledger.record(ad.name, 0.0, "keyless adapter")
    stage["discovery_s"] = round(time.monotonic() - t, 2)

    # 2. canonicalize / dedup / select
    pool, rejected, possible_same = dedup(discovered)
    ranked_pool, priority_info = prioritize_pool(pool, cfg.seed, policy)

    # 3. research: best-first until `max_candidates` companies are assessed; failed attempts are backfilled
    t = time.monotonic()
    companies, selected, research_plan = research_with_backfill(
        ranked_pool, cfg.max_candidates, budget,
        lambda c: research_company(c, fetcher, policy, cfg.max_secondary))
    selection_info = {c.domain: priority_info[c.domain] for c in selected if c.domain in priority_info}
    skipped = skipped_records(ranked_pool, selected, research_plan)
    stage["research_s"] = round(time.monotonic() - t, 2)

    # 4. rank + drafts
    ranked = rank(companies)
    t = time.monotonic()
    drafts = []
    cand_by_domain = {c.domain: c for c in selected}
    for c in ranked:
        if not policy.drafts_enabled or len(drafts) >= cfg.draft_count:
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
        "icp_id": policy.id, "policy_version": policy.policy_version, "policy_digest": policy.digest,
        "policy_source_format": policy.source_format, "seed": cfg.seed, "max_candidates": cfg.max_candidates,
        "max_research": budget, "research_plan": research_plan,
        "discovery_status": discovery_status,
        # "selected" means RESEARCHED (initial wave + backfill), so the report funnel adds up.
        "counts": {"discovered_raw": len(discovered), "after_dedup_pool": len(pool),
                   "rejected": len(rejected), "selected": len(selected), "researched": len(selected),
                   "skipped_not_researched": len(skipped),
                   "selected_automated": sum(1 for c in selected if c.discovery_method == AUTOMATED),
                   "selected_manual": sum(1 for c in selected if c.discovery_method == "manual"),
                   "selected_synthetic": sum(1 for c in selected if c.discovery_method == "synthetic_fixture"),
                   "raw_automated": sum(1 for c in discovered if c.discovery_method == AUTOMATED),
                   # Manual directory seeds are a SUBSET of the manual counts above and never of automated.
                   "raw_manual_directory_seed": sum(1 for c in discovered if c.source == "directory_seed"),
                   "selected_manual_directory_seed": sum(1 for c in selected if c.source == "directory_seed")},
        "http_requests_logged": len(fetcher.log), "paid_api_spend_usd": ledger.total_usd,
        "spend_ledger_entries": len(ledger.entries),
        "credentials_detected_in_env_but_ignored": credentials_present(),
        "selection_method": ("prequalify priority (record description/listing/headcount), then ICP-term breadth "
                             "in record text, then seeded hash; failed attempts backfilled within max_research"),
        "selection_priorities": selection_info,
        "discovery_coverage": coverage(pool, policy),
        "possible_same_company_different_domain": possible_same,
        "sending": "none: this prototype contains no email/Gmail/SMTP code path",
    }
    if seed_summaries:
        manifest["directory_seed"] = {"inputs": seed_summaries, "excluded_from_autonomous_metrics": True,
                                      "note": "manual review of directory listings; occurrence log in "
                                              "directory_seed_occurrences.json"}
    if cfg.mode == "replay":
        manifest["replay"] = dict(cfg.extra.get("replay") or {}, network="disabled",
                                  counts_as_fresh_discovery=False, counts_as_independent_live_result=False)
        manifest["replay_missing_pages"] = list(getattr(fetcher, "missing", []))
        manifest["counts"]["selected_replay"] = sum(1 for c in selected if c.discovery_method == "replay")
    _write_json(out / "manifest.json", manifest)
    _write_json(out / "candidates.json", [asdict(c) for c in selected])
    # The full post-dedup pool WITH discovery attributes. candidates.json keeps only the researched companies, so the
    # discovery metadata of everything else was lost and a run's pool could never be re-ranked or benchmarked later.
    _write_json(out / "pool.json", [asdict(c) for c in pool])
    _write_json(out / "rejected.json", rejected)
    _write_json(out / "skipped.json", skipped)
    if seed_summaries:
        _write_json(out / "directory_seed_occurrences.json",
                    [o for c in discovered for o in c.attrs.get("seed_occurrences", [])])
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
            "rejected": rejected, "skipped": skipped}


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
