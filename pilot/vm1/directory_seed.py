"""Source-attributed directory seed ingestion (manual review path).

A human reviews a partner/agency directory in a browser, copies each agency's OFFICIAL name and its OWN
website into a CSV, and this module turns those rows into discovery candidates:

* the directory's name and URL (from ``source_catalog.json``) travel with every candidate;
* rows are deduplicated by canonical company domain, and EVERY listing is kept in an occurrence log;
* candidates are labelled ``manual`` so they never count toward autonomous-discovery metrics;
* nothing here fetches a directory. Candidates continue into the existing first-party qualification
  (research of the company's own site); a directory listing is never evidence about the company.

No automated directory adapter is registered. ``AUTOMATED_DIRECTORY_ADAPTERS`` must stay empty until a
documented API or an explicit permission is verified for a specific directory and recorded in the catalog
(see ``load_catalog`` for the fail-closed rule).

CSV columns: ``name`` and ``url`` (required); ``directory_id`` and ``listing_url`` (optional).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from .canon import canonical_domain, is_first_party_candidate
from .discovery import MANUAL, Adapter, Candidate, DiscoveryBlocked
from .fetch import utc_now_iso
from .guard import FREE_KEYLESS, require_zero_cost

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG = ROOT / "source_catalog.json"
ADAPTER_NAME = "directory_seed"
SEED_LICENSE = ("user-supplied: manual review of the named directory listing; directory statements are not "
                "first-party proof and directory content is not redistributed")

# directory id -> automated adapter factory. EMPTY ON PURPOSE: no directory has a verified documented API
# or permitted collection method yet. Do not add an entry without recording the verification in the catalog.
AUTOMATED_DIRECTORY_ADAPTERS: dict[str, object] = {}


class CatalogError(ValueError):
    """The source catalog is malformed or claims access it has not verified."""


@dataclass(frozen=True)
class DirectorySource:
    id: str
    name: str
    url: str
    priority: int
    icps: tuple[str, ...]
    fit: str
    mode: str
    automated_adapter: bool
    automated_access_verified: bool
    access_review: dict = field(default_factory=dict, compare=False, hash=False)

    @property
    def domain(self) -> str | None:
        return canonical_domain(self.url)


def load_catalog(path: str | Path = DEFAULT_CATALOG) -> dict[str, DirectorySource]:
    """Directory sources by id. Fails closed on any claim of automated access that is not verified."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CatalogError(f"cannot read source catalog {path}: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise CatalogError("source catalog must be an object with schema_version 1")
    rows = data.get("proposed_directory_sources")
    if not isinstance(rows, list):
        raise CatalogError("source catalog has no proposed_directory_sources list")
    out: dict[str, DirectorySource] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise CatalogError("catalog directory entry is not an object")
        sid, name, url = row.get("id"), row.get("name"), row.get("url")
        if not all(isinstance(v, str) and v.strip() for v in (sid, name, url)):
            raise CatalogError(f"catalog entry needs non-empty id, name and url: {row!r}")
        if sid in out:
            raise CatalogError(f"duplicate catalog id {sid!r}")
        if urlsplit(url).scheme != "https" or not canonical_domain(url):
            raise CatalogError(f"{sid}: url must be an https URL with a resolvable domain")
        mode = row.get("mode")
        auto, verified = row.get("automated_adapter"), row.get("automated_access_verified")
        if not isinstance(auto, bool) or not isinstance(verified, bool):
            raise CatalogError(f"{sid}: automated_adapter and automated_access_verified must be booleans")
        if auto and not (verified and mode != "manual_seed_only" and row.get("access_review")):
            raise CatalogError(
                f"{sid}: automated_adapter=true requires automated_access_verified=true, a non-manual mode "
                "and a recorded access_review; refusing to trust an unverified claim")
        if auto and sid not in AUTOMATED_DIRECTORY_ADAPTERS:
            raise CatalogError(f"{sid}: catalog claims an automated adapter but none is registered")
        icps = row.get("icps") or []
        out[sid] = DirectorySource(
            id=sid, name=name.strip(), url=url.strip(), priority=int(row.get("priority") or 0),
            icps=tuple(str(i) for i in icps), fit=str(row.get("fit") or ""), mode=str(mode or ""),
            automated_adapter=auto, automated_access_verified=verified,
            access_review=dict(row.get("access_review") or {}))
    return out


def manual_only_blocker(name: str, catalog_path: str | Path = DEFAULT_CATALOG) -> str | None:
    """Explain why a catalog directory cannot be used as an automated ``--sources`` name (None if unknown)."""
    try:
        catalog = load_catalog(catalog_path)
    except CatalogError:
        return None
    src = catalog.get(name.strip().lower())
    if src is None or src.id in AUTOMATED_DIRECTORY_ADAPTERS:
        return None
    review = src.access_review or {}
    detail = f" Review ({review.get('reviewed_on')}): {'; '.join(review.get('findings', []))}" if review else ""
    return (f"{src.id} ({src.name}) is manual_seed_only: no documented API or permitted collection method is "
            f"verified, so no automated adapter exists.{detail} Review the directory manually and import the "
            f"agencies' own names and websites with --directory-seed-csv --directory-source {src.id}.")


@dataclass
class SeedIngestResult:
    candidates: list[Candidate]
    occurrences: list[dict]
    rejected: list[dict]
    stats: dict
    by_directory: dict[str, dict]


def _is_http(url: str) -> bool:
    return urlsplit(url).scheme in ("http", "https") and bool(urlsplit(url).hostname)


def read_seed_rows(path: str | Path) -> list[dict]:
    p = Path(path)
    if not p.exists():
        raise DiscoveryBlocked(f"directory seed csv not found: {p}")
    with p.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        fields = {(f or "").strip().lower() for f in (reader.fieldnames or [])}
        if not {"name", "url"} <= fields:
            raise DiscoveryBlocked(f"directory seed csv needs 'name' and 'url' columns (found {sorted(fields)})")
        rows = []
        for n, raw in enumerate(reader, start=2):  # line 1 is the header
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in raw.items() if k}
            row["_line"] = n
            rows.append(row)
    return rows


def ingest_rows(rows: list[dict], catalog: dict[str, DirectorySource], *, default_directory: str | None = None,
                retrieved_at: str | None = None) -> SeedIngestResult:
    """Validate, attribute and deduplicate seed rows. Pure: no network, no file writes."""
    now = retrieved_at or utc_now_iso()
    if default_directory is not None and default_directory not in catalog:
        raise DiscoveryBlocked(f"unknown directory id {default_directory!r}; known: {sorted(catalog)}")
    if default_directory is None and rows and not any("directory_id" in r for r in rows):
        raise DiscoveryBlocked("seed rows have no attribution: add a directory_id column or pass "
                               "--directory-source (every candidate must name the directory it came from)")
    stats = {"rows": len(rows), "invalid_rows": 0, "valid_rows": 0, "duplicate_domain_rows": 0,
             "unique_domains": 0}
    by_dir: dict[str, dict] = {}
    rejected: list[dict] = []
    occurrences: list[dict] = []
    first: dict[str, Candidate] = {}

    def reject(row: dict, reason: str, directory_id: str | None = None) -> None:
        stats["invalid_rows"] += 1
        if directory_id:
            by_dir.setdefault(directory_id, {"rows": 0, "invalid_rows": 0, "valid_rows": 0, "new_domains": 0,
                                             "duplicate_domain_rows": 0})["invalid_rows"] += 1
        rejected.append({"line": row.get("_line"), "name": row.get("name", ""), "url": row.get("url", ""),
                         "directory_id": directory_id or row.get("directory_id") or default_directory,
                         "reason": reason})

    for row in rows:
        did = (row.get("directory_id") or default_directory or "").strip()
        if not did:
            reject(row, "no_directory_id")
            continue
        src = catalog.get(did)
        if src is None:
            reject(row, "unknown_directory_id")
            continue
        d = by_dir.setdefault(did, {"rows": 0, "invalid_rows": 0, "valid_rows": 0, "new_domains": 0,
                                    "duplicate_domain_rows": 0})
        d["rows"] += 1
        name, url, listing = row.get("name", ""), row.get("url", ""), row.get("listing_url", "")
        if not name or not url:
            reject(row, "missing_name_or_url", did)
            continue
        probe = url if "://" in url else "https://" + url
        if not _is_http(probe):
            reject(row, "url_not_http", did)
            continue
        domain = canonical_domain(probe)
        if not domain:
            reject(row, "invalid_or_unresolvable_domain", did)
            continue
        if domain == src.domain:
            reject(row, "directory_own_domain", did)  # a profile page on the directory, not the agency's site
            continue
        if not is_first_party_candidate(domain):
            reject(row, "non_first_party_domain", did)
            continue
        if listing and (not _is_http(listing) or canonical_domain(listing) != src.domain):
            reject(row, "listing_url_not_on_directory", did)
            continue
        occ = {"directory_id": src.id, "directory_name": src.name, "directory_url": src.url,
               "listing_url": listing or src.url, "listed_name": name, "listed_url": url, "domain": domain,
               "line": row["_line"], "retrieved_at": now}
        occurrences.append(occ)
        stats["valid_rows"] += 1
        d["valid_rows"] += 1
        cand = first.get(domain)
        if cand is None:
            first[domain] = Candidate(
                name=name, url=url, domain=domain, discovery_method=MANUAL, source=ADAPTER_NAME,
                source_id=src.id, source_url=occ["listing_url"], source_license=SEED_LICENSE,
                retrieved_at=now,
                attrs={"seed_directory": {"id": src.id, "name": src.name, "url": src.url},
                       "seed_occurrences": [occ]})
            d["new_domains"] += 1
        else:
            cand.attrs["seed_occurrences"].append(occ)
            stats["duplicate_domain_rows"] += 1
            d["duplicate_domain_rows"] += 1
    candidates = list(first.values())
    stats["unique_domains"] = len(candidates)
    return SeedIngestResult(candidates, occurrences, rejected, stats, by_dir)


class DirectorySeedAdapter(Adapter):
    """Manual directory seed CSV. Always ``manual``; never counted as autonomous discovery."""

    name = ADAPTER_NAME
    cost_class = FREE_KEYLESS
    terms_note = ("manual review only: no directory page is fetched or crawled; rows are copied by a human "
                  "from the named directory and carry its attribution")
    license_note = SEED_LICENSE

    def __init__(self, csv_path: str | Path, *, directory_id: str | None = None,
                 catalog_path: str | Path = DEFAULT_CATALOG):
        require_zero_cost(self.name, self.cost_class)
        self.csv_path = Path(csv_path)
        self.directory_id = directory_id.strip().lower() if directory_id else None
        self.catalog_path = Path(catalog_path)
        self.run_note = ""
        self.yield_stats: dict = {}
        self.result: SeedIngestResult | None = None

    def discover(self) -> list[Candidate]:
        try:
            catalog = load_catalog(self.catalog_path)
        except CatalogError as exc:
            raise DiscoveryBlocked(f"directory seed: {exc}") from exc
        result = ingest_rows(read_seed_rows(self.csv_path), catalog, default_directory=self.directory_id)
        self.result = result
        self.yield_stats = dict(result.stats)
        self.run_note = (f"{result.stats['rows']} seed rows -> {result.stats['unique_domains']} distinct company "
                         f"domains ({result.stats['invalid_rows']} invalid, "
                         f"{result.stats['duplicate_domain_rows']} duplicate-domain rows kept in the occurrence "
                         "log); manual input, excluded from autonomous-discovery metrics")
        return result.candidates

    def seed_summary(self) -> dict:
        r = self.result
        return {"csv": self.csv_path.name, "stats": dict(r.stats) if r else {},
                "by_directory": r.by_directory if r else {},
                "excluded_from_autonomous_metrics": True}


def write_seed_artifacts(out_dir: str | Path, result: SeedIngestResult) -> dict[str, Path]:
    """Write the reviewable ingestion outputs. Local run artifacts: keep out of git (runs/ is ignored)."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    files = {
        "directory_seeds.json": [{"name": c.name, "url": c.url, "domain": c.domain,
                                  "discovery_method": c.discovery_method, "source": c.source,
                                  "source_id": c.source_id, "source_url": c.source_url,
                                  "directories": sorted({o["directory_id"] for o in c.attrs["seed_occurrences"]}),
                                  "occurrence_count": len(c.attrs["seed_occurrences"])}
                                 for c in result.candidates],
        "directory_seed_occurrences.json": result.occurrences,
        "directory_seed_rejected.json": result.rejected,
        "directory_seed_summary.json": {"stats": result.stats, "by_directory": result.by_directory,
                                        "excluded_from_autonomous_metrics": True},
    }
    paths = {}
    for fname, payload in files.items():
        p = out / fname
        p.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        paths[fname] = p
    return paths
