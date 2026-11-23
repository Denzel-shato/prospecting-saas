"""Report generation. Metrics always carry denominators; nothing is claimed as passed without
real, reproducible, independently labelled evidence. Human labels are read from a CSV the user
fills in; this code never labels anything itself."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from .score import EXCLUDED, NOT_RESEARCHABLE

BENCHMARKS = {  # reference benchmarks from docs/VM1-START-HERE.md; NOT adopted pass criteria
    "top20_relevance": 0.70, "reachable_sites": 0.95, "own_site_home_and_secondary": 0.80,
    "duplicates": 0.02, "false_strong": 0.15, "decision_maker_top1": 0.70, "wrong_person": 0.05,
}
LABEL_FIELDS = ["domain", "relevant", "us_based", "decision_maker_correct", "notes"]


def load_run(run_dir: str | Path) -> dict:
    d = Path(run_dir)
    load = lambda n: json.loads((d / n).read_text(encoding="utf-8"))  # noqa: E731
    return {"dir": str(d), "manifest": load("manifest.json"), "companies": load("companies.json"),
            "drafts": load("drafts.json"), "rejected": load("rejected.json"),
            "candidates": load("candidates.json")}


def read_labels(path: str | Path | None) -> dict[str, dict]:
    if not path or not Path(path).exists():
        return {}
    out: dict[str, dict] = {}
    with Path(path).open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            dom = (row.get("domain") or "").strip().lower()
            if dom:
                out[dom] = {k: (row.get(k) or "").strip().lower() if k != "notes" else row.get(k, "")
                            for k in LABEL_FIELDS[1:]}
    return out


def write_labels_template(run_dir: str | Path, companies: list[dict]) -> Path:
    path = Path(run_dir) / "labels_template.csv"
    ranked = sorted([c for c in companies if c["total"] is not None], key=lambda c: (-c["total"], c["domain"]))
    rest = [c for c in companies if c["total"] is None]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(LABEL_FIELDS)
        for c in ranked + rest:
            w.writerow([c["domain"], "", "", "", ""])
    return path


def _frac(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.0%})" if d else f"{n}/{d} (n/a)"


def compute_metrics(run: dict, labels: dict[str, dict] | None = None) -> dict:
    labels = labels or {}
    comps, man = run["companies"], run["manifest"]
    attempted = len(comps)
    ranked = sorted([c for c in comps if c["total"] is not None], key=lambda c: (-c["total"], c["domain"]))
    top20 = ranked[:20]
    m: dict = {"attempted": attempted, "ranked_eligible": len(ranked)}

    m["homepage_ok"] = sum(1 for c in comps if c["homepage"].get("ok"))
    m["robots_blocked"] = sum(1 for c in comps if c["tier"] == NOT_RESEARCHABLE)
    m["fetch_errors"] = Counter((c["homepage"].get("error") or "").split(":")[0]
                                for c in comps if not c["homepage"].get("ok"))
    m["home_and_secondary_ok"] = sum(1 for c in comps if c["homepage"].get("ok")
                                     and any(s["ok"] for s in c["secondary"]))
    m["no_secondary_link_found"] = sum(1 for c in comps if c["homepage"].get("ok")
                                       and c["secondary_links_found"] == 0)
    m["exclusions"] = Counter(e["rule"] for c in comps for e in c["score"]["hard_exclusions"])
    m["tiers"] = Counter(c["tier"] for c in comps)
    # Older runs predate the field: counted as "unrecorded", never inferred.
    m["dispositions"] = Counter((c.get("score") or {}).get("disposition") or "unrecorded" for c in comps)
    eligible = [c for c in comps if c["tier"] not in (EXCLUDED, NOT_RESEARCHABLE)]
    m["dm_named"] = sum(1 for c in eligible if c["decision_makers"])
    m["eligible"] = len(eligible)
    m["raw_discovered"] = man["counts"]["discovered_raw"]
    m["pool"] = man["counts"]["after_dedup_pool"]
    m["duplicates_removed"] = sum(1 for r in run["rejected"] if r["reason"] == "duplicate_domain")
    m["residual_duplicate_domains"] = len(comps) - len({c["domain"] for c in comps})
    m["drafts"] = len(run["drafts"])
    m["drafts_lint_passed"] = sum(1 for d in run["drafts"] if d["lint"]["passed"])
    m["dropped_unverifiable_evidence"] = sum(c["dropped_unverifiable_evidence"] for c in comps)
    m["evidence_items_verified"] = sum(len(c["evidence"]) for c in comps)

    # human-label metrics (only if labels exist)
    lab_top = [(c, labels.get(c["domain"])) for c in top20]
    judged = [(c, l) for c, l in lab_top if l and l["relevant"] in ("y", "n")]
    m["top20_labeled"] = len(judged)
    m["top20_relevant_y"] = sum(1 for _, l in judged if l["relevant"] == "y")
    m["top20_size"] = len(top20)
    strong = [(c, labels.get(c["domain"])) for c in comps if c["tier"] == "strong"]
    sj = [(c, l) for c, l in strong if l and l["relevant"] in ("y", "n")]
    m["strong_labeled"], m["strong_false"] = len(sj), sum(1 for _, l in sj if l["relevant"] == "n")
    hs = [(c, l) for c in comps if (l := labels.get(c["domain"])) and l["relevant"] == "y"]
    m["human_relevant_labeled"] = len(hs)
    m["human_relevant_marked_weak_or_excluded"] = sum(1 for c, _ in hs if c["tier"] in ("weak", EXCLUDED))
    dmj = [(c, labels[c["domain"]]) for c in comps
           if c["decision_makers"] and c["domain"] in labels
           and labels[c["domain"]]["decision_maker_correct"] in ("y", "n")]
    m["dm_labeled"], m["dm_correct"] = len(dmj), sum(1 for _, l in dmj if l["decision_maker_correct"] == "y")
    m["labels_provided"] = len(labels)
    return m


def verdict(run: dict, m: dict) -> list[str]:
    man = run["manifest"]
    c = man["counts"]
    if man["mode"] == "replay":
        return ["**REPLAY - NOT A FINDING.** Re-analysis of previously captured page snapshots with the current code. "
                "It is not fresh discovery and not an independent live relevance result; evidence timestamps are the "
                "original capture times. Use it only to compare code versions on identical inputs."]
    if man["mode"] == "requalify":
        return ["**OFFLINE REQUALIFICATION - NOT A NEW DISCOVERY RESULT.** Existing stored evidence was rescored "
                "under another ICP without new web research. Original evidence may be incomplete for the new policy; "
                "historical discovery counts are reused, not fresh metrics."]
    if man["mode"] == "synthetic_fixture":
        return ["**NOT A FINDING.** This run used FICTIONAL synthetic fixtures to exercise the pipeline. "
                "It says nothing about real discovery quality, real companies, or ICP fit."]
    sources = {source["adapter"] for source in man.get("discovery_status", [])}
    if sources and sources <= {"manual_csv", "directory_seed"}:
        return [f"**MANUAL QUALIFICATION RUN.** Evaluated {c['selected_manual']} manually supplied candidates. "
                "Autonomous discovery was outside this run's scope."]
    lines = []
    auto = c["selected_automated"]
    if auto < 30:
        lines.append(
            f"**INCONCLUSIVE / NO-GO for expansion.** Autonomous zero-cost discovery produced "
            f"{c['raw_automated']} raw / {auto} evaluated candidates (target 30-40). The discovery test "
            f"has NOT succeeded; see 'Discovery status' for the exact blockers. Manual/CSV inputs do not "
            f"count toward autonomous-discovery metrics.")
    elif m["top20_labeled"] == 0:
        lines.append("**PENDING.** Autonomous discovery reached the target size, but there are no human "
                     "relevance labels yet, so relevance, accuracy and go/no-go cannot be assessed. "
                     "Fill in labels_template.csv and re-run `report --labels`.")
    else:
        lines.append("**Evidence available; interpret with caution.** Compare the measured values below "
                     "to the reference benchmarks. Benchmarks are not adopted pass criteria and the "
                     "sample is small; this is not a pass claim.")
    return lines


def render_report(run: dict, m: dict) -> str:
    man, comps = run["manifest"], run["companies"]
    c = man["counts"]
    L: list[str] = []
    L.append(f"# VM1 pilot report — run `{man['run_id']}`")
    L.append("")
    if man["mode"] == "synthetic_fixture":
        L.append("> **SYNTHETIC FIXTURE RUN — FICTIONAL DATA. PIPELINE CHECK ONLY. NOT PILOT FINDINGS.**")
        L.append("")
    if man["mode"] == "requalify":
        origin = man.get("requalification") or {}
        L.append(f"> **OFFLINE REQUALIFICATION of stored evidence only.** Source run `{origin.get('source_run_id')}` "
                 f"(original mode `{origin.get('source_mode')}`). No new discovery, HTTP fetch or extraction. "
                 "Historical discovery counts are inherited, not new findings; missing evidence remains unknown.")
        L.append("")
    if man["mode"] == "replay":
        rp = man.get("replay") or {}
        L.append(f"> **REPLAY OF SNAPSHOTS - network disabled.** capture `{rp.get('capture_id')}` "
                 f"(captured {rp.get('captured_at')}). Not fresh discovery; not an independent live result.")
        if man.get("replay_missing_pages"):
            L.append(f"> **INCOMPLETE: {len(man['replay_missing_pages'])} page(s) the current code wanted were not "
                     f"captured:** {', '.join(man['replay_missing_pages'][:10])}")
        L.append("")
    L.append("## Verdict")
    L += verdict(run, m)
    L.append("")
    L.append("## Scope and ICP")
    L.append(f"ICP id: `{man['icp_id']}`"
             + (f" v{man['policy_version']} (digest `{man.get('policy_digest', 'unknown')}`)" if man.get("policy_version") else "")
             + ". One ICP, no Gmail, no sending, no paid APIs. "
             f"Actual paid API spend: **${man['paid_api_spend_usd']:.2f}**. "
             f"Credentials detected in env but ignored: {man['credentials_detected_in_env_but_ignored'] or 'none'}.")
    L.append("")
    L.append("## Discovery status")
    for s in man["discovery_status"]:
        extra = f" — **{s['reason']}**" if s.get("reason") else ""
        L.append(f"- `{s['adapter']}` ({s['cost_class']}): **{s['status']}**, {s['count']} candidates{extra}")
        if s.get("note"):
            L.append(f"  - query note: {s['note']}")
        if s.get("yield"):
            L.append("  - source yield (rejection reasons; counts of directory records, not qualified leads): "
                     + ", ".join(f"{k}={v}" for k, v in s["yield"].items() if not isinstance(v, (list, dict))))
            for i, q in enumerate(s["yield"].get("per_query") or [], start=1):
                L.append(f"    - query {i} {q.get('query')}: records={q.get('records')}, new={q.get('new_candidates')}, "
                         f"duplicate={q.get('duplicate_domain')}, rejected(geo/size/site)="
                         f"{q.get('geography_rejected')}/{q.get('size_rejected')}/{q.get('no_website')}")
        if s.get("terms_note"):
            L.append(f"  - terms noted: {s['terms_note']} (verify before relying on it; license: {s.get('license') or 'n/a'})")
    if not man["discovery_status"]:
        L.append("- no adapters were run")
    L.append("")
    L.append("## Funnel (automation vs manual inputs kept separate)")
    L.append(f"- raw candidates: {c['discovered_raw']} (automated: {c['raw_automated']})")
    L.append(f"- after canonical-domain dedup/first-party filter: {c['after_dedup_pool']} "
             f"(rejected: {c['rejected']}; duplicate domains removed: {m['duplicates_removed']})")
    L.append(f"- evaluated: {c['selected']} = automated {c['selected_automated']} + manual "
             f"{c['selected_manual']} + synthetic {c['selected_synthetic']}")
    L.append(f"- selection: {man.get('selection_method', 'deterministic hash order')}; seed `{man['seed']}`, "
             f"cap {man['max_candidates']}")
    rp = man.get("research_plan")
    if rp:
        oc = rp["outcomes"]
        L.append(f"- research plan: target {rp['target_assessed']} assessed within a budget of {rp['max_research']} "
                 f"attempts; attempted {rp['attempted']} (initial {rp['initial_attempted']}, backfill "
                 f"{rp['backfill_attempted']}); assessed {oc['assessed']}, inaccessible {oc['inaccessible']}, "
                 f"robots-refused {oc['not_researchable']}, excluded by evidence {oc['excluded']}; "
                 f"stopped: {rp['stop_reason']}; not researched {rp['unresearched_in_pool']} (skipped.json)")
    cov = man.get("discovery_coverage")
    if cov and cov.get("pool"):
        if "agency_like_description" in cov:
            L.append(f"- discovery-record coverage of the pool ({cov['pool']}): description present "
                     f"{cov['with_record_description']}, agency-like description {cov['agency_like_description']}, "
                     f"vendor-like description {cov['vendor_like_description']}, listed on an exchange "
                     f"{cov['listed_on_exchange']}. Description matches are unverified discovery hints.")
        else:
            L.append(f"- ICP-relative discovery-record coverage of the pool ({cov['pool']}): description present "
                     f"{cov['with_record_description']}, target-like description {cov.get('target_like_description', 0)}, "
                     f"negative-keyword description {cov.get('negative_like_description', 0)}, listed on an exchange "
                     f"{cov['listed_on_exchange']}. These are record-term signals, NOT verified ICP matches.")
    L.append("")
    L.append("## Metrics (denominators shown; reference benchmarks are NOT adopted gates)")
    a = m["attempted"]
    L.append("| Metric | Measured | Reference | Note |")
    L.append("|---|---|---|---|")
    L.append(f"| Reachable first-party homepages | {_frac(m['homepage_ok'], a)} | >=95% | robots-blocked: {m['robots_blocked']}; errors: {dict(m['fetch_errors'])} |")
    L.append(f"| Homepage + >=1 secondary page fetched | {_frac(m['home_and_secondary_ok'], a)} | >=80% | no secondary link found: {m['no_secondary_link_found']} |")
    L.append(f"| Residual duplicate domains after dedup | {_frac(m['residual_duplicate_domains'], a)} | <=2% | by construction of the key; name-collision review list in manifest |")
    L.append(f"| Hard-exclusion rules triggered (companies removed) | {sum(m['exclusions'].values())} | 0 violations | rule-based only; independent check needs human labels: {dict(m['exclusions'])} |")
    L.append(f"| Excerpt re-verification (verbatim in fetched page) | {m['evidence_items_verified']} kept / {m['dropped_unverifiable_evidence']} dropped | 95% supported claims | this checks quoting, NOT whether the page's claim is true |")
    L.append(f"| Unsupported factual assertions in drafts (lint) | {m['drafts'] - m['drafts_lint_passed']} failing of {m['drafts']} drafts | 0 | automated lint; human review still required |")
    L.append(f"| Decision-maker named on first-party site | {_frac(m['dm_named'], m['eligible'])} of eligible | report only | coverage, not accuracy |")
    L.append("| Fabricated/guessed emails | 0 | 0 | no email is collected or generated at all |")
    if m["top20_labeled"]:
        L.append(f"| Top-20 relevance (human labels) | {_frac(m['top20_relevant_y'], m['top20_labeled'])} (top-20 size {m['top20_size']}) | >=70% | only labeled rows count; 'unsure' excluded |")
    else:
        L.append(f"| Top-20 relevance | NOT MEASURED (no human labels) | >=70% | top-20 size {m['top20_size']} |")
    if m["strong_labeled"]:
        L.append(f"| False strong matches | {_frac(m['strong_false'], m['strong_labeled'])} | <=15% | |")
    if m["human_relevant_labeled"]:
        L.append(f"| Human-relevant marked weak/excluded | {_frac(m['human_relevant_marked_weak_or_excluded'], m['human_relevant_labeled'])} | <=20% | |")
    if m["dm_labeled"]:
        L.append(f"| Decision-maker correct (labels) | {_frac(m['dm_correct'], m['dm_labeled'])} | >=70% top-1 | wrong-person rate {1 - m['dm_correct'] / m['dm_labeled']:.0%} (ref <=5%) |")
    L.append("")
    L.append("Tier counts: " + ", ".join(f"{k}={v}" for k, v in sorted(m["tiers"].items())))
    L.append("Dispositions (confirmed disqualification vs missing information): "
             + ", ".join(f"{k}={v}" for k, v in sorted(m["dispositions"].items())))
    L.append("")
    L.append("## Ranked top 20")
    ranked = sorted([x for x in comps if x["total"] is not None], key=lambda x: (-x["total"], x["domain"]))[:20]
    if not ranked:
        L.append("_No eligible ranked companies._")
    else:
        L.append("| # | Domain | Score | Tier | Company type | Why (rule points) | Decision-maker (first-party site) | Discovery |")
        L.append("|---|---|---|---|---|---|---|---|")
        for i, x in enumerate(ranked, 1):
            dm = x["decision_makers"][0] if x["decision_makers"] else None
            dm_s = f"{dm['name']}, {dm['title']}" if dm else "unknown"
            why = "; ".join(f"{p['points']:+d} {p['rule']}" for p in x["score"]["components"])
            why = why if len(why) <= 400 else why[:397] + "..."
            L.append(f"| {i} | {x['domain']} | {x['total']} | {x['tier']} | {x.get('company_type', 'n/a')} | "
                     f"{why} | {dm_s} | {x['discovery']['method']} |")
    L.append("")
    if man.get("policy_version"):
        L.append("## Policy-specific qualification evidence (top five ranked)")
        for c in ranked[:5]:
            L.append(f"### `{c['domain']}`")
            evidence_by_id = {e["id"]: e for e in c.get("evidence", [])}
            for criterion in c.get("score", {}).get("criteria", []):
                L.append(f"- {criterion['criterion']}: **{criterion['status']}** — {criterion['detail']}")
                for eid in criterion.get("evidence_ids", [])[:2]:
                    e = evidence_by_id.get(eid)
                    if e:
                        excerpt = str(e.get("excerpt", "")).replace("\\n", " ")[:140]
                        L.append(f"  - evidence `{eid}` ({e['source_url']}): {excerpt}")
        if not ranked:
            L.append("_No eligible companies._")
        L.append("")
    L.append("## Excluded / ineligible")
    for x in comps:
        if x["tier"] in (EXCLUDED, NOT_RESEARCHABLE):
            why = ", ".join(e["rule"] for e in x["score"]["hard_exclusions"]) or "; ".join(x["score"]["flags"])
            L.append(f"- `{x['domain']}`: {x['tier']} — {why}")
    L.append("")
    L.append("## Evidence samples (timestamped, short verbatim excerpts)")
    shown = 0
    for x in ranked[:5]:
        for ev in x["evidence"][:2]:
            L.append(f"- `{x['domain']}` · {ev['claim_type']} = {ev['value']} · **{ev['level']}** · "
                     f"{ev['fetched_at']} · {ev['source_url']}\n  > {ev['excerpt']}")
            shown += 1
    if not shown:
        L.append("_No evidence to show._")
    L.append("")
    L.append("## Error cases")
    errs = [x for x in comps if not x["homepage"].get("ok")]
    for x in errs:
        L.append(f"- `{x['domain']}`: homepage {x['homepage'].get('error')}")
    L.append(f"- evidence items dropped because the excerpt was not re-verifiable: {m['dropped_unverifiable_evidence']}")
    if not errs:
        L.append("- no homepage fetch errors in this run")
    L.append("")
    L.append("## Unsent drafts")
    L.append(f"{m['drafts']} drafts in `drafts/` and `drafts.json`; every one is status UNSENT_DRAFT, "
             f"has no recipient email, and uses placeholders for seller identity.")
    L.append("")
    L.append("## Time and cost")
    L.append(f"Elapsed {man['elapsed_s']}s ({man['stage_elapsed_s']}); HTTP requests logged: "
             f"{man['http_requests_logged']}; **paid API spend: $0.00**.")
    L.append("")
    L.append("## Limitations")
    L.append("- Page statements are attribution, not verified truth; sizes/locations may be stale.\n"
             "- Non-US detection is partial; absence of non-US evidence is not proof of US presence.\n"
             "- Relevance and decision-maker accuracy need independent human labels; none are produced here.\n"
             "- Scoring thresholds are arbitrary starting points, uncalibrated.\n"
             "- Free discovery sources have thin coverage of small studios; coverage is measured, not assumed.")
    return "\n".join(L) + "\n"


def write_report(run_dir: str | Path, labels_path: str | Path | None = None) -> Path:
    run = load_run(run_dir)
    m = compute_metrics(run, read_labels(labels_path))
    write_labels_template(run_dir, run["companies"])
    path = Path(run_dir) / "report.md"
    path.write_text(render_report(run, m), encoding="utf-8")
    return path
