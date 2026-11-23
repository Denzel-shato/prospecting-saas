"""Does V2 evidence preparation keep the expected executive in its passages?

Read-only over a saved benchmark run (``results.jsonl`` + ``snapshots/<slug>/``) and the label CSV. Nothing is
fetched, no AI is called, labels and stored snapshots are never modified. Output goes to a NEW directory.

Statuses (``status``), grouped so fetch problems are never confused with preparation problems:
  fetch side : fetch_failed | no_fetch_record | snapshot_unavailable (fetched, but saved HTML missing/corrupt)
  prep side  : prep_error (exception) | no_passages (prep kept nothing)
  coverage   : covered (name and role in ONE passage) | name_without_role | name_not_in_passages
``name_not_in_passages`` carries ``detail`` = name_on_page_not_selected | name_not_on_page.
Matching is lexical (accent/case/whitespace-folded; "&" = "and"); it says the evidence is AVAILABLE to a later
extractor, not that an extractor would find it or that the statement is true.
"""

from __future__ import annotations

import csv
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

from ..e6v2 import prepare_evidence
from ..e6v2_workflow import load_snapshots

FETCH_SIDE = ("fetch_failed", "no_fetch_record", "snapshot_unavailable")
PREP_SIDE = ("prep_error", "no_passages")
COVERAGE = ("covered", "name_without_role", "name_not_in_passages")
_STOP = {"and", "of", "the"}
COLUMNS = ["company", "domain", "expected_name", "expected_role", "status", "detail", "http_status", "fetch_error",
           "passages", "chars", "max_passage_chars", "name_in_passages", "role_in_passages", "name_and_role_together",
           "name_on_page", "risk_flags", "name_passage_flags", "name_passage_ids"]


def fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", text or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold().replace("&", " and ")
    return " ".join(re.sub(r"[^\w\s]", " ", t).split())


def _role_in(role: str, text: str) -> bool:
    r, t = fold(role), fold(text)
    if not r:
        return False
    if r in t:
        return True
    toks = [w for w in r.split() if w not in _STOP]
    return bool(toks) and all(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", t) for w in toks)


def slug(domain: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", domain.lower()).strip("-")


def audit_company(label: dict, fetch_row: dict | None, source: Path) -> dict:
    out = {c: "" for c in COLUMNS}
    out.update(company=label["company"], domain=label["domain"], expected_name=label["expected_name"],
               expected_role=label["expected_role"], passages=0, chars=0, max_passage_chars=0)
    if fetch_row is None:
        return {**out, "status": "no_fetch_record"}
    out["http_status"], out["fetch_error"] = fetch_row.get("http_status") or "", fetch_row.get("fetch_error") or ""
    if not fetch_row.get("fetch_ok"):
        return {**out, "status": "fetch_failed"}
    try:
        snaps = load_snapshots(source / "snapshots" / slug(label["domain"]))
    except (OSError, ValueError) as exc:
        return {**out, "status": "snapshot_unavailable", "detail": f"{type(exc).__name__}"}
    if not snaps:
        return {**out, "status": "snapshot_unavailable", "detail": "no saved HTML 200 response"}
    try:
        passages = prepare_evidence(snaps).passages
    except Exception as exc:  # preparation failure must be reported, not hidden
        return {**out, "status": "prep_error", "detail": f"{type(exc).__name__}: {exc}"}
    flags = Counter(f for p in passages for f in p.risk_flags)
    out.update(passages=len(passages), chars=sum(len(p.text) for p in passages),
               max_passage_chars=max((len(p.text) for p in passages), default=0),
               risk_flags=";".join(f"{k}:{v}" for k, v in sorted(flags.items())))
    if not passages:
        return {**out, "status": "no_passages"}
    name = fold(label["expected_name"])
    with_name = [p for p in passages if name and name in fold(p.text)]
    out["name_in_passages"] = bool(with_name)
    out["role_in_passages"] = any(_role_in(label["expected_role"], p.text) for p in passages)
    out["name_and_role_together"] = any(_role_in(label["expected_role"], p.text) for p in with_name)
    out["name_passage_ids"] = ";".join(p.passage_id for p in with_name)
    out["name_passage_flags"] = ";".join(sorted({f for p in with_name for f in p.risk_flags}))
    out["name_on_page"] = any(name and name in fold(t) for s in snaps for t in [*s.page.blocks, *s.page.people_blocks])
    if out["name_and_role_together"]:
        out["status"] = "covered"
    elif with_name:
        out["status"] = "name_without_role"
    else:
        out["status"] = "name_not_in_passages"
        out["detail"] = "name_on_page_not_selected" if out["name_on_page"] else "name_not_on_page"
    return out


def read_labels(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def read_fetch_rows(source: Path) -> dict:
    path = source / "results.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]
    return {r["domain"]: r for r in rows}


def run_audit(source: Path, labels_csv: Path) -> list[dict]:
    fetch = read_fetch_rows(source)
    return [audit_company(l, fetch.get(l["domain"]), source) for l in read_labels(labels_csv)]


def render_report(rows: list[dict], source: Path) -> str:
    by = Counter(r["status"] for r in rows)
    n = len(rows)
    fetched = n - sum(by[s] for s in FETCH_SIDE)
    lines = ["# Engine 6 V2 passage coverage audit", "",
             f"Source: `{source}` (saved HTML, read-only). {n} benchmark companies. Offline: no AI, no crawling, "
             "labels unchanged. Matching is lexical; `covered` means the evidence is available in a prepared passage, "
             "not that an extractor would find it or that the claim is true.", "",
             "## Summary", "", "| Group | Status | Companies |", "|---|---|---|"]
    for group, statuses in (("fetch side", FETCH_SIDE), ("prep side", PREP_SIDE), ("coverage", COVERAGE)):
        for s in statuses:
            lines.append(f"| {group} | {s} | {by[s]} |")
    lines += ["", f"Fetched and saved: {fetched} of {n}. Of those, evidence available: {by['covered']}; "
              f"prep failures: {sum(by[s] for s in PREP_SIDE)}; other gaps: "
              f"{by['name_without_role'] + by['name_not_in_passages']}.", "",
              "## Per company", "",
              "| Company | Status | Detail | Passages | Chars | Name | Role | Together | Risk flags |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        lines.append("| {company} | {status} | {detail} | {passages} | {chars} | {name_in_passages} | "
                     "{role_in_passages} | {name_and_role_together} | {risk_flags} |".format(**r))
    missing = [r for r in rows if r["status"] in COVERAGE[1:] + PREP_SIDE]
    lines += ["", "## Missing evidence", ""]
    lines += [f"- {r['company']} ({r['domain']}): {r['status']}"
              + (f" / {r['detail']}" if r["detail"] else "") + f" - expected {r['expected_name']}, {r['expected_role']}"
              for r in missing] or ["- none"]
    fetch_gaps = [r for r in rows if r["status"] in FETCH_SIDE]
    lines += ["", "## Fetch-side gaps (not preparation failures)", ""]
    lines += [f"- {r['company']} ({r['domain']}): {r['status']} {r['detail'] or r['fetch_error'] or r['http_status']}"
              for r in fetch_gaps] or ["- none"]
    return "\n".join(lines) + "\n"


def write_outputs(rows: list[dict], source: Path, out_dir: Path) -> tuple:
    if out_dir.exists() and any(out_dir.iterdir()):
        raise FileExistsError(f"output directory {out_dir} already exists and is not empty")
    out_dir.mkdir(parents=True, exist_ok=True)
    csv_path, md_path = out_dir / "audit.csv", out_dir / "report.md"
    with open(csv_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)
    md_path.write_text(render_report(rows, source), encoding="utf-8")
    return md_path, csv_path
