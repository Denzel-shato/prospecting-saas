"""Offline, reproducible benchmark for Engine #1 (discovery): yield, unique coverage and human-labelled precision.

Inputs are LOCAL files only; nothing here touches the network or any API.

* ``pool.json`` (written by every run) or any JSON list / {"candidates": [...]} of candidate records
  (flat or with ``attrs``). Each file is one ARM (for example a PickAnAgency query profile) so arms can be compared.
* Optional human labels CSV: ``domain,label[,labeler,reviewed_on,notes]`` with label relevant | not_relevant | unsure.

Two kinds of numbers are kept strictly apart and are never merged:

* AUTOMATED RECORD TIERS: wording in the directory/Wikidata record only. They order research; they are NOT labels and
  say nothing about real lead quality.
* HUMAN LABELS: only rows a person labelled. Precision is reported over labelled rows with the denominator, label
  coverage and a Wilson 95% interval. Unlabelled rows are never assumed relevant or irrelevant.

Synthetic/fictional pools are flagged and can only demonstrate that the method runs.
Deterministic: no clock, no randomness (ranking uses the same seeded order as the pipeline).
"""
from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from types import SimpleNamespace

from .canon import canonical_domain
from .policy import IcpPolicy, load_policy
from .prequalify import rank_pool, record_evidence, record_text

LABEL_VALUES = ("relevant", "not_relevant", "unsure")
_ALIASES = {"y": "relevant", "yes": "relevant", "n": "not_relevant", "no": "not_relevant",
            "u": "unsure", "?": "unsure", "unknown": "unsure"}
TIERS = ("record_target_like", "record_mixed", "record_generic", "record_negative", "record_no_text")
TIER_NOTE = ("automated record tiers are derived from discovery-record wording only; they are NOT human labels "
             "and do not measure lead quality")
DEFAULT_TOP_K = (10, 20)


# ----------------------------------------------------------------------------------------------------- loading
def _domain_of(rec: dict) -> str | None:
    return canonical_domain(rec.get("domain") or rec.get("url") or rec.get("website") or "")


def load_pool(path: str | Path) -> list[dict]:
    """Tolerant loader. Returns [{domain, name, source, method, attrs}]; rows without a usable domain are kept
    out of the pool but counted by the caller via ``len(raw) - len(pool)``."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = data.get("candidates", data.get("results", [])) if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError(f"{path}: expected a list of candidate records")
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        attrs = {**{k: v for k, v in r.items() if k not in ("attrs",)}, **(r.get("attrs") or {})}
        dom = _domain_of(r)
        if not dom:
            continue
        attrs.setdefault("directory_tagline", attrs.get("tagline") or "")
        if "services" in attrs and "directory_services" not in attrs:
            attrs["directory_services"] = [s for s in attrs["services"] if isinstance(s, str)]
        out.append({"domain": dom, "name": r.get("name") or "", "source": r.get("source") or "unknown",
                    "method": r.get("discovery_method") or "unknown", "attrs": attrs})
    return out


def read_labels(path: str | Path | None) -> tuple[dict[str, dict], dict]:
    """Human labels by canonical domain, plus a report of problems. Conflicting duplicate labels are dropped."""
    info = {"rows": 0, "invalid": [], "conflicting_domains": [], "labeled": 0}
    if not path:
        return {}, info
    with Path(path).open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = {(f or "").strip().lower() for f in reader.fieldnames or ()}
        if not {"domain", "label"} <= fields:
            raise ValueError(f"{path}: labels CSV needs 'domain' and 'label' columns (found {sorted(fields)})")
        seen: dict[str, set] = defaultdict(set)
        meta: dict[str, dict] = {}
        for n, raw in enumerate(reader, start=2):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}
            info["rows"] += 1
            dom = canonical_domain(row.get("domain", ""))
            label = _ALIASES.get(row.get("label", "").lower(), row.get("label", "").lower())
            if not dom or label not in LABEL_VALUES:
                info["invalid"].append({"line": n, "domain": row.get("domain", ""), "label": row.get("label", "")})
                continue
            seen[dom].add(label)
            meta[dom] = {"label": label, "labeler": row.get("labeler", ""), "reviewed_on": row.get("reviewed_on", "")}
    labels = {}
    for dom, vals in sorted(seen.items()):
        if len(vals) > 1:
            info["conflicting_domains"].append(dom)
        else:
            labels[dom] = meta[dom]
    info["labeled"] = len(labels)
    return labels, info


# ------------------------------------------------------------------------------------------------- statistics
def wilson(k: int, n: int, z: float = 1.96) -> list[float] | None:
    if n <= 0:
        return None
    p = k / n
    d = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / d
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0.0, centre - half), 3), round(min(1.0, centre + half), 3)]


def human_stats(domains: list[str], labels: dict[str, dict]) -> dict:
    """Precision over HUMAN-labelled rows only; ``None`` when nothing in the group is labelled."""
    c = Counter(labels[d]["label"] for d in domains if d in labels)
    rel, nrel, uns = c["relevant"], c["not_relevant"], c["unsure"]
    decided = rel + nrel
    return {"rows": len(domains), "labeled": rel + nrel + uns, "relevant": rel, "not_relevant": nrel, "unsure": uns,
            "label_coverage": round((rel + nrel + uns) / len(domains), 3) if domains else None,
            "precision": round(rel / decided, 3) if decided else None, "precision_denominator": decided,
            "precision_wilson95": wilson(rel, decided)}


# --------------------------------------------------------------------------------------------- record tiers
def record_tier(attrs: dict, policy: IcpPolicy) -> str:
    """Automated tier from discovery-record wording and structural flags. Never a human label."""
    ev = record_evidence(attrs, policy)
    flagged_negative = bool(attrs.get("listed_on_exchange") or attrs.get("directory_vendor_hint"))
    negative = bool(ev.negative or ev.ambiguous_penalised)
    if flagged_negative and not ev.specific:
        return "record_negative"
    if ev.specific:
        return "record_mixed" if (negative or flagged_negative) else "record_target_like"
    if negative:
        return "record_negative"
    return "record_generic" if record_text(attrs) else "record_no_text"


def _query_key(q: dict) -> str:
    return "; ".join(f"{k}={v}" for k, v in sorted(q.items())) or "(none)"


def _queries(attrs: dict) -> list[str]:
    qs = attrs.get("directory_discovery_queries")
    if not isinstance(qs, list) or not qs:
        one = attrs.get("directory_discovery_query")
        qs = [one] if isinstance(one, dict) else []
    return [_query_key(q) for q in qs if isinstance(q, dict)]


def _first_query(attrs: dict) -> str | None:
    one = attrs.get("directory_discovery_query")
    if isinstance(one, dict):
        return _query_key(one)
    qs = _queries(attrs)
    return qs[0] if qs else None


# ------------------------------------------------------------------------------------------------- the arm
def _tier_counts(items: list[tuple[str, str]]) -> dict:
    c = Counter(t for _, t in items)
    return {t: c.get(t, 0) for t in TIERS}


def analyse_arm(rows: list[dict], policy: IcpPolicy, labels: dict[str, dict], seed: str, top_k=DEFAULT_TOP_K,
                manifest: dict | None = None) -> dict:
    unique: dict[str, dict] = {}
    for r in rows:
        unique.setdefault(r["domain"], r)
    tiers = {d: record_tier(r["attrs"], policy) for d, r in unique.items()}
    domains = sorted(unique)
    arm = {"rows": len(rows), "unique_domains": len(unique), "duplicate_rows": len(rows) - len(unique),
           "methods": dict(sorted(Counter(r["method"] for r in unique.values()).items())),
           "tiers": _tier_counts([(d, tiers[d]) for d in domains]),
           "human": human_stats(domains, labels)}

    by_source = {}
    for src in sorted({r["source"] for r in unique.values()}):
        ds = [d for d in domains if unique[d]["source"] == src]
        by_source[src] = {"unique_domains": len(ds), "tiers": _tier_counts([(d, tiers[d]) for d in ds]),
                          "target_like_share": round(sum(tiers[d] == "record_target_like" for d in ds) / len(ds), 3),
                          "human": human_stats(ds, labels)}
    arm["by_source"] = by_source

    qstats: dict[str, dict] = {}
    for d in domains:
        attrs = unique[d]["attrs"]
        first = _first_query(attrs)
        for q in _queries(attrs):
            s = qstats.setdefault(q, {"returned_unique": [], "first_seen_here": []})
            s["returned_unique"].append(d)
            if q == first:
                s["first_seen_here"].append(d)
    arm["by_query"] = {q: {"returned_unique": len(s["returned_unique"]), "first_seen_here": len(s["first_seen_here"]),
                           "tiers_first_seen": _tier_counts([(d, tiers[d]) for d in s["first_seen_here"]]),
                           "human_first_seen": human_stats(s["first_seen_here"], labels)}
                       for q, s in sorted(qstats.items())}
    arm["queries_observed_lower_bound"] = len(qstats)

    sizes = Counter(unique[d]["attrs"].get("directory_team_size") or "unknown" for d in domains)
    arm["directory_team_size"] = dict(sorted(sizes.items()))

    # research-order proxy: the pipeline's own seeded ranking over this arm's unique pool
    ranked = rank_pool([SimpleNamespace(domain=d, attrs=unique[d]["attrs"]) for d in domains], seed, policy)
    order = [r.candidate.domain for r in ranked]
    arm["ranked_prefix"] = {}
    for k in top_k:
        head = order[:k]
        arm["ranked_prefix"][str(k)] = {"size": len(head), "tiers": _tier_counts([(d, tiers[d]) for d in head]),
                                        "human": human_stats(head, labels)}
    arm["tier_calibration_human"] = {t: human_stats([d for d in domains if tiers[d] == t], labels) for t in TIERS}
    if manifest is not None:
        status = manifest.get("discovery_status") if isinstance(manifest, dict) else None
        arm["adapter_yield_from_manifest"] = {s.get("adapter"): s.get("yield", {}) for s in status or []
                                              if isinstance(s, dict)}
    # Yield per bounded request: the success criterion is relevant studios per permitted query, not candidate count.
    exact = None
    if manifest is not None:
        exact = sum(len((s.get("yield") or {}).get("per_query") or []) for s in manifest.get("discovery_status") or []
                    if isinstance(s, dict)) or None
    requests = exact or len(qstats) or None
    h = arm["human"]
    arm["yield_per_request"] = {
        "requests": requests, "requests_exact": bool(exact),
        "unique_companies_per_request": round(len(unique) / requests, 2) if requests else None,
        "automated_target_like_per_request": (round(arm["tiers"]["record_target_like"] / requests, 2) if requests else None),
        "human_relevant_per_request": (round(h["relevant"] / requests, 2) if requests and h["labeled"] else None),
        "human_relevant_found": h["relevant"], "human_label_coverage": h["label_coverage"]}
    arm["_domains"] = domains
    return arm


# --------------------------------------------------------------------------------------------- full benchmark
def is_synthetic(rows: list[dict]) -> bool:
    return bool(rows) and all(r["method"] == "synthetic_fixture" or r["domain"].endswith(".example") for r in rows)


def run_benchmark(arms: dict[str, list[dict]], policy: IcpPolicy | dict, labels: dict[str, dict] | None = None,
                  label_info: dict | None = None, seed: str = "vm1-pilot-1", manifests: dict | None = None,
                  top_k=DEFAULT_TOP_K, force_synthetic: bool = False) -> dict:
    pol = load_policy(policy)
    labels = labels or {}
    manifests = manifests or {}
    result_arms = {name: analyse_arm(rows, pol, labels, seed, top_k, manifests.get(name))
                   for name, rows in sorted(arms.items())}
    sets = {n: set(a["_domains"]) for n, a in result_arms.items()}
    cross = {"union_unique_domains": len(set().union(*sets.values())) if sets else 0,
             "unique_to_arm": {n: len(s - set().union(*(o for m, o in sets.items() if m != n))) for n, s in sets.items()
                               } if len(sets) > 1 else {},
             "pairwise_overlap": {f"{a}&{b}": len(sets[a] & sets[b])
                                  for i, a in enumerate(sorted(sets)) for b in sorted(sets)[i + 1:]}}
    for a in result_arms.values():
        a.pop("_domains")
    pool_domains = set().union(*sets.values()) if sets else set()
    synthetic = force_synthetic or any(is_synthetic(rows) for rows in arms.values())
    notices = [TIER_NOTE]
    if synthetic:
        notices.insert(0, "SYNTHETIC/FICTIONAL INPUT: this only shows the method runs; it is not evidence of real "
                          "discovery or lead quality, and any improvement here is not a real-world improvement.")
    if not labels:
        notices.append("NO HUMAN LABELS supplied: precision is NOT MEASURED. Only automated record tiers and "
                       "yield counts are shown.")
    else:
        matched = len(pool_domains & set(labels))
        if matched < len(pool_domains):
            notices.append(f"human labels cover {matched} of {len(pool_domains)} pooled companies; precision is over "
                           "labelled rows only and may not generalise to unlabelled ones")
        unmatched = sorted(set(labels) - pool_domains)
        if unmatched:
            notices.append(f"{len(unmatched)} labelled domain(s) are not in any imported pool: {unmatched[:10]}")
    if label_info and (label_info.get("conflicting_domains") or label_info.get("invalid")):
        notices.append(f"label file problems: conflicting={label_info.get('conflicting_domains')}, "
                       f"invalid_rows={len(label_info.get('invalid', []))}; those rows were not used")
    return {"benchmark_version": 1, "icp": pol.id, "policy_version": pol.version if hasattr(pol, "version") else None,
            "seed": seed, "synthetic_input": synthetic, "labels_supplied": len(labels), "notices": notices,
            "arms": result_arms, "cross_arm": cross}


# ------------------------------------------------------------------------------------------------- rendering
def _h(h: dict) -> str:
    if h["precision"] is None:
        return f"not measured ({h['labeled']}/{h['rows']} labelled)"
    lo, hi = h["precision_wilson95"]
    return (f"{h['relevant']}/{h['precision_denominator']} = {h['precision']:.0%} (95% CI {lo:.0%}-{hi:.0%}; "
            f"{h['labeled']}/{h['rows']} labelled, {h['unsure']} unsure excluded)")


def _t(t: dict) -> str:
    return ", ".join(f"{k.removeprefix('record_')}={v}" for k, v in t.items() if v)


def render_markdown(res: dict) -> str:
    L = ["# Discovery benchmark (Engine #1)", ""]
    L += [f"- ICP: `{res['icp']}`; ranking seed `{res['seed']}`; labels supplied: {res['labels_supplied']}"]
    L += [f"- **{n}**" for n in res["notices"]]
    L.append("")
    cross = res["cross_arm"]
    L.append(f"Union of unique companies across arms: **{cross['union_unique_domains']}**"
             + (f"; unique to each arm: {cross['unique_to_arm']}; overlap: {cross['pairwise_overlap']}" if cross["unique_to_arm"] else ""))
    for name, a in res["arms"].items():
        L += ["", f"## Arm `{name}`", "",
              f"- rows {a['rows']} -> unique companies {a['unique_domains']} ({a['duplicate_rows']} duplicate rows); methods {a['methods']}",
              f"- automated record tiers (not labels): {_t(a['tiers'])}",
              f"- directory team-size buckets (self-reported): {a['directory_team_size']}",
              f"- human-labelled precision, all unique: {_h(a['human'])}"]
        y = a["yield_per_request"]
        if y["requests"]:
            hum = (f"{y['human_relevant_per_request']} human-confirmed relevant per request ({y['human_relevant_found']} found; "
                   f"label coverage {y['human_label_coverage']:.0%}, a floor if rows are unlabelled)"
                   if y["human_relevant_per_request"] is not None else "human-relevant per request NOT MEASURED")
            L.append(f"- yield per request ({y['requests']} requests, {'exact from manifest' if y['requests_exact'] else 'lower-bound estimate'}): "
                     f"{y['unique_companies_per_request']} unique companies, {y['automated_target_like_per_request']} automated target-like (not a label); {hum}")
        for k, p in a["ranked_prefix"].items():
            L.append(f"- research-order top {k}: tiers {_t(p['tiers'])}; human precision {_h(p['human'])}")
        L.append("")
        L.append("| source | unique | target-like share (automated) | human precision |")
        L.append("|---|---|---|---|")
        for s, v in a["by_source"].items():
            L.append(f"| {s} | {v['unique_domains']} | {v['target_like_share']:.0%} | {_h(v['human'])} |")
        if a["by_query"]:
            L += ["", f"Per-query yield (queries observed: {a['queries_observed_lower_bound']}, a lower bound unless a manifest is given):", "",
                  "| query | returned | first seen here | tiers of first-seen (automated) | human precision of first-seen |",
                  "|---|---|---|---|---|"]
            for q, v in a["by_query"].items():
                L.append(f"| {q} | {v['returned_unique']} | {v['first_seen_here']} | {_t(v['tiers_first_seen'])} | {_h(v['human_first_seen'])} |")
        if res["labels_supplied"]:
            L += ["", "Tier calibration against human labels (does the automated tier predict a human 'relevant'?):"]
            for t, h in a["tier_calibration_human"].items():
                if h["rows"]:
                    L.append(f"- {t}: {_h(h)}")
    return "\n".join(L) + "\n"


def write_outputs(result: dict, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    js, md = out / "discovery_benchmark.json", out / "discovery_benchmark.md"
    js.write_text(json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False), encoding="utf-8")
    md.write_text(render_markdown(result), encoding="utf-8")
    return {"json": js, "markdown": md}


def labels_template(path: str | Path, arms: dict[str, list[dict]]) -> int:
    """Blank labelling sheet (domain, name, source) for a human; label/labeler/reviewed_on stay empty."""
    seen: dict[str, dict] = {}
    for rows in arms.values():
        for r in rows:
            seen.setdefault(r["domain"], r)
    with Path(path).open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["domain", "name", "source", "label", "labeler", "reviewed_on", "notes"])
        for d in sorted(seen):
            w.writerow([d, seen[d]["name"], seen[d]["source"], "", "", "", ""])
    return len(seen)
