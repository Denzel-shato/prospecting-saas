"""Build an offline review queue from completed live VM1 research runs."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlsplit

from .canon import canonical_domain
from .evidence import SOURCE_SUPPORTED
from .report import load_run
from .score import EXCLUDED, NOT_RESEARCHABLE

REVIEW_FIELDS = ("decision", "reason", "verified_person", "verified_role", "verified_person_url", "outreach_angle")
FIELDS = (
    "domain", "company", "website", "source", "run_id", "tier", "score",
    "suggested_person", "suggested_role", "suggested_person_url", "service_evidence", "service_url",
    *REVIEW_FIELDS,
)
DECISIONS = {"", "contact", "skip", "needs_research"}


def read_reviews(path: Path) -> dict[str, dict[str, str]]:
    reviews = {}
    with path.open(newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not {"domain", "decision"} <= set(reader.fieldnames or ()):
            raise ValueError(f"{path}: expected domain and decision columns")
        for line, row in enumerate(reader, 2):
            domain = canonical_domain(row["domain"])
            review = {field: (row.get(field) or "").strip() for field in REVIEW_FIELDS}
            review["decision"] = review["decision"].lower()
            if not domain or domain in reviews or review["decision"] not in DECISIONS:
                raise ValueError(f"{path}:{line}: invalid domain, duplicate domain, or unsupported decision")
            reviews[domain] = review
    return reviews


def review_row(company: dict, domain: str, source: str, run_id: str, review: dict) -> dict:
    person = next(iter(company["decision_makers"]), {})
    verified_ids = set(company["verified_evidence_ids"])
    service = next((
        item for item in company["evidence"]
        if item["id"] in verified_ids and item["level"] == SOURCE_SUPPORTED
        and item["source_type"] == "first_party_page" and item["claim_type"].startswith("service:")
    ), {})
    return {
        "domain": domain, "company": company["name"], "website": company["url"],
        "source": source, "run_id": run_id, "tier": company["tier"], "score": company["total"],
        "suggested_person": person.get("name", ""), "suggested_role": person.get("title", ""),
        "suggested_person_url": person.get("source_url", ""),
        "service_evidence": service.get("excerpt", ""), "service_url": service.get("source_url", ""),
        **{field: review.get(field, "") for field in REVIEW_FIELDS},
    }


def ready_to_contact(row: dict) -> bool:
    if row["decision"] != "contact" or not all(row[field] for field in REVIEW_FIELDS[2:]):
        return False
    url = row["verified_person_url"]
    return urlsplit(url).scheme in {"http", "https"} and canonical_domain(url) == row["domain"]


def write_csv(path: Path, rows: list[dict]) -> None:
    pending = path.with_suffix(".tmp")
    with pending.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: "'" + value if isinstance(value, str) and value.startswith(
                ("=", "+", "-", "@", "\t", "\r", "\n")) else value for key, value in row.items()})
    pending.replace(path)


def build_weekly(batches: list[tuple[str, Path]], history: list[Path], out: Path) -> dict:
    queue_path = out / "review.csv"
    reviews = read_reviews(queue_path) if queue_path.exists() else {}
    if any(path.resolve() == queue_path.resolve() for path in history):
        raise ValueError("current review.csv must not also be supplied as history")
    previously_reviewed = {
        domain for path in history for domain, review in read_reviews(path).items()
        if review["decision"] == "skip" or ready_to_contact({"domain": domain, **review})
    }
    seen = set()
    rows = []
    counts = defaultdict(Counter)
    icp = None
    for source, path in batches:
        run = load_run(path)
        manifest = run["manifest"]
        if manifest["mode"] != "live":
            raise ValueError(f"{path}: only live research runs can populate the weekly queue")
        identity = (manifest["icp_id"], manifest.get("policy_digest"))
        if icp and identity != icp:
            raise ValueError("weekly batches must use the same ICP and policy digest")
        icp = identity
        for company in run["companies"]:
            counts[source]["researched"] += 1
            domain = canonical_domain(company["domain"])
            if not domain:
                counts[source]["missing_domain"] += 1
            elif domain in previously_reviewed:
                counts[source]["previously_reviewed"] += 1
            elif domain in seen:
                counts[source]["duplicate"] += 1
            else:
                seen.add(domain)
                rows.append(review_row(company, domain, source, manifest["run_id"], reviews.get(domain, {})))
    if reviews.keys() - {row["domain"] for row in rows}:
        raise ValueError("existing review.csv contains domains absent from these runs; include the original batches")
    rows.sort(key=lambda row: (row["tier"] in {EXCLUDED, NOT_RESEARCHABLE},
                               -(row["score"] or 0), row["domain"]))
    ready = []
    for row in rows:
        counter = counts[row["source"]]
        counter["unique_new"] += 1
        counter[row["decision"] or "unreviewed"] += 1
        if ready_to_contact(row):
            ready.append(row)
            counter["ready"] += 1
    summary = {
        "unique_new_companies": len(rows),
        "ready_to_contact": len(ready),
        "contact_missing_verification_or_angle": sum(row["decision"] == "contact" for row in rows) - len(ready),
        "weekly_ready_target": [150, 200],
        "shortfall_to_150": max(0, 150 - len(ready)),
        "sources": dict(counts),
    }
    out.mkdir(parents=True, exist_ok=True)
    write_csv(queue_path, rows)
    write_csv(out / "ready.csv", ready)
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", nargs=2, metavar=("SOURCE", "RUN_DIR"), action="append", required=True)
    parser.add_argument("--history", type=Path, action="append", default=[], help="prior week's review.csv")
    parser.add_argument("--out", type=Path, required=True, help="this week's output directory")
    args = parser.parse_args()
    try:
        result = build_weekly([(source, Path(path)) for source, path in args.batch], args.history, args.out)
    except (OSError, ValueError, KeyError) as error:
        parser.exit(2, f"weekly: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
