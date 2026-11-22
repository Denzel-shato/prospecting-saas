"""Discovery adapters. Only FREE, KEYLESS sources are registered.

Every candidate is labelled with HOW it was found:
  automated          -> found by a live keyless adapter from the ICP alone (counts toward
                        autonomous-discovery metrics)
  manual             -> user-supplied CSV (does NOT count toward autonomous discovery)
  synthetic_fixture  -> fictional test data used to exercise the pipeline (never a finding)

No adapter fabricates results. If a source cannot be reached or is not permitted, the
adapter raises DiscoveryBlocked and the run records the exact reason.
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode, urlsplit

from . import USER_AGENT
from .canon import canonical_domain, is_first_party_candidate
from .fetch import NETWORK_ERRORS, PinnedTransport, Transport, utc_now_iso
from .guard import FREE_KEYLESS, PaidApiBlocked, require_zero_cost
from .htmlparse import parse_html
from .netsafe import Resolver, UnsafeURL, default_resolver, validate_url

AUTOMATED = "automated"
MANUAL = "manual"
SYNTHETIC = "synthetic_fixture"


class DiscoveryBlocked(Exception):
    """A discovery source cannot be used right now; the message is the exact blocker."""


@dataclass
class Candidate:
    name: str
    url: str
    discovery_method: str  # automated | manual | synthetic_fixture
    source: str  # discovery adapter name
    source_id: str = ""
    source_url: str = ""
    source_license: str = ""
    retrieved_at: str = ""
    attrs: dict = field(default_factory=dict)
    domain: str | None = None

    def __post_init__(self) -> None:
        if self.domain is None:
            self.domain = canonical_domain(self.url)


class ApiClient:
    """Tiny SSRF-safe JSON client for fixed keyless discovery hosts."""

    ALLOWED_HOSTS = {"query.wikidata.org", "overpass-api.de", "www.drupal.org"}

    def __init__(self, transport: Transport | None = None, resolver: Resolver | None = None,
                 timeout: float = 90.0, max_bytes: int = 25_000_000):
        self.transport = transport or PinnedTransport()
        self.resolver = resolver or default_resolver
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.calls = 0

    def request_json(self, method: str, url: str, form: dict | None = None,
                     accept: str = "application/json") -> dict:
        host = urlsplit(url).hostname or ""
        if host not in self.ALLOWED_HOSTS:
            raise DiscoveryBlocked(f"host {host!r} is not an approved keyless discovery host")
        try:
            target = validate_url(url, self.resolver)
        except UnsafeURL as exc:
            raise DiscoveryBlocked(f"{host}: unsafe or unresolvable ({exc})") from exc
        headers = {"User-Agent": USER_AGENT, "Accept": accept, "Accept-Encoding": "identity",
                   "Connection": "close"}
        body = None
        if form is not None:
            body = urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        self.calls += 1
        try:
            raw = self.transport.request(method, target, headers, body, self.timeout, self.max_bytes)
        except NETWORK_ERRORS as exc:
            raise DiscoveryBlocked(f"{host}: network failure {type(exc).__name__}: {exc}") from exc
        if raw.status != 200:
            raise DiscoveryBlocked(f"{host}: HTTP {raw.status} (no retry; respect rate controls)")
        if raw.truncated:
            raise DiscoveryBlocked(f"{host}: response exceeded {self.max_bytes} bytes")
        try:
            return json.loads(raw.body.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise DiscoveryBlocked(f"{host}: non-JSON response") from exc


class Adapter:
    name = "adapter"
    cost_class = FREE_KEYLESS
    requires_ack: str | None = None
    terms_note = ""
    license_note = ""

    def discover(self) -> list[Candidate]:  # pragma: no cover - interface
        raise NotImplementedError


class WikidataAdapter(Adapter):
    """Wikidata SPARQL (CC0 data, keyless). Coverage of small studios is expected to be thin.

    IDs are VERIFIED at runtime against their English labels before the main query runs;
    a mismatch aborts (fail closed) rather than silently querying the wrong class.
    """

    name = "wikidata"
    SPARQL = "https://query.wikidata.org/sparql"
    CLASS_SOFTWARE_COMPANY = "Q1058914"
    COUNTRY_US = "Q30"
    terms_note = ("Wikidata Query Service: keyless; send a descriptive User-Agent; keep queries "
                  "narrow; back off on 429. Data is CC0.")
    license_note = "CC0 (Wikidata)"

    def __init__(self, client: ApiClient, limit: int = 500):
        require_zero_cost(self.name, self.cost_class)
        self.client = client
        self.limit = limit

    def _get(self, query: str) -> dict:
        url = f"{self.SPARQL}?{urlencode({'query': query, 'format': 'json'})}"
        return self.client.request_json("GET", url, accept="application/sparql-results+json")

    def _verify_ids(self) -> None:
        q = (f"SELECT ?q ?l WHERE {{ VALUES ?q {{ wd:{self.CLASS_SOFTWARE_COMPANY} wd:{self.COUNTRY_US} }} "
             f"?q rdfs:label ?l . FILTER(LANG(?l)=\"en\") }}")
        rows = self._get(q).get("results", {}).get("bindings", [])
        labels = {r["q"]["value"].rsplit("/", 1)[-1]: r["l"]["value"].lower() for r in rows}
        if "software company" not in labels.get(self.CLASS_SOFTWARE_COMPANY, ""):
            raise DiscoveryBlocked(
                f"wikidata ID check failed: {self.CLASS_SOFTWARE_COMPANY} label="
                f"{labels.get(self.CLASS_SOFTWARE_COMPANY)!r}, expected 'software company'")
        if not labels.get(self.COUNTRY_US, "").startswith("united states"):
            raise DiscoveryBlocked(
                f"wikidata ID check failed: {self.COUNTRY_US} label={labels.get(self.COUNTRY_US)!r}")

    def build_query(self, enriched: bool = True) -> str:
        if not enriched:
            # Original (live-proven in run 20261121T150320Z-live) query: used only as a fallback.
            return f"""SELECT ?item ?itemLabel ?website ?employees WHERE {{
  ?item wdt:P31 wd:{self.CLASS_SOFTWARE_COMPANY} .
  {{ ?item wdt:P17 wd:{self.COUNTRY_US} }} UNION {{ ?item wdt:P159/wdt:P17 wd:{self.COUNTRY_US} }}
  ?item wdt:P856 ?website .
  OPTIONAL {{ ?item wdt:P1128 ?employees . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT {int(self.limit)}"""
        # ?desc (English item description) and ?listed (has a stock-exchange statement) are used ONLY
        # for pre-research prioritisation (vm1.prequalify); they never qualify a company by themselves.
        # ORDER BY makes the LIMIT window deterministic instead of an arbitrary server-side slice.
        # NOT yet live-verified: if the service rejects it (HTTP 400) discover() falls back, visibly.
        return f"""SELECT ?item ?itemLabel ?website ?employees ?desc ?listed WHERE {{
  ?item wdt:P31 wd:{self.CLASS_SOFTWARE_COMPANY} .
  {{ ?item wdt:P17 wd:{self.COUNTRY_US} }} UNION {{ ?item wdt:P159/wdt:P17 wd:{self.COUNTRY_US} }}
  ?item wdt:P856 ?website .
  OPTIONAL {{ ?item wdt:P1128 ?employees . }}
  OPTIONAL {{ ?item schema:description ?desc . FILTER(LANG(?desc) = "en") }}
  BIND(EXISTS {{ ?item wdt:P414 ?exchange }} AS ?listed)
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} ORDER BY ?item LIMIT {int(self.limit)}"""

    def parse(self, data: dict, retrieved_at: str) -> list[Candidate]:
        out: list[Candidate] = []
        for row in data.get("results", {}).get("bindings", []):
            try:
                item = row["item"]["value"]
                name = row["itemLabel"]["value"]
                site = row["website"]["value"]
            except KeyError:
                continue
            attrs: dict = {"country": "US"}
            emp = row.get("employees", {}).get("value")
            if emp and emp.isdigit():
                attrs["employees"] = int(emp)
            desc = row.get("desc", {}).get("value")
            if desc:
                attrs["description"] = desc[:300]
            if row.get("listed", {}).get("value") in ("true", "1"):
                attrs["listed_on_exchange"] = True
            out.append(Candidate(name=name, url=site, discovery_method=AUTOMATED, source=self.name,
                                 source_id=item.rsplit("/", 1)[-1], source_url=item,
                                 source_license=self.license_note, retrieved_at=retrieved_at, attrs=attrs))
        return out

    run_note = ""

    def discover(self) -> list[Candidate]:
        self._verify_ids()
        try:
            data = self._get(self.build_query(enriched=True))
            self.run_note = "enriched query (description/listing flag) used for pre-research prioritisation"
        except DiscoveryBlocked as exc:
            if "HTTP 400" not in str(exc):  # only a malformed-query rejection; never retry 429/5xx
                raise
            data = self._get(self.build_query(enriched=False))
            self.run_note = (f"enriched query rejected ({exc}); fell back to the basic query: "
                             "no description/listing data, so no record-based prioritisation")
        return self.parse(data, utc_now_iso())


class DrupalOrgAdapter(Adapter):
    """Bounded organization-directory discovery for US client-service studios."""

    name = "drupal_org"
    ENDPOINT = "https://www.drupal.org/api-d7/node.json"
    PAGE_SIZE = 50
    MAX_PAGES = 4
    terms_note = "Drupal.org REST API: identify the client, limit requests, and retain attribution."
    license_note = "CC BY-SA 2.0 (Drupal.org contributed content)"
    _SERVICES = re.compile(
        r"\b(?:agency|studio|consulting|consultancy|development services|we (?:build|develop|design))\b", re.I)
    _FRONTEND = re.compile(r"\b(?:React|Next\.?js|TypeScript|headless|decoupled)\b", re.I)

    def __init__(self, client: ApiClient):
        require_zero_cost(self.name, self.cost_class)
        self.client = client
        self.run_note = ""

    def discover(self) -> list[Candidate]:
        # Reuse the first-party geography patterns as directory screening hints only.
        from .evidence import NON_US_RE, US_ADDRESS_RE, US_BASED_RE, US_COUNTRY_RE

        found = {}
        records = 0
        retrieved_at = utc_now_iso()
        for page in range(self.MAX_PAGES):
            query = urlencode({"type": "organization", "limit": self.PAGE_SIZE, "sort": "changed",
                               "direction": "DESC", "page": page})
            data = self.client.request_json("GET", f"{self.ENDPOINT}?{query}")
            rows = data.get("list") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                raise DiscoveryBlocked("drupal_org: expected an organization list in the API response")
            records += len(rows)
            for row in rows:
                if not isinstance(row, dict) or row.get("type") != "organization":
                    continue
                location = row.get("field_organization_headquarters")
                link = row.get("field_link")
                body = row.get("body")
                name, node_id = row.get("title"), row.get("nid")
                if not all(isinstance(value, str) and value.strip() for value in (location, name, node_id)):
                    continue
                if not node_id.isascii() or not node_id.isdecimal():
                    continue
                if not (US_COUNTRY_RE.search(location) or location.strip() == "US"
                        or US_ADDRESS_RE.search(location) or US_BASED_RE.search(f"based in {location}")):
                    continue
                if NON_US_RE.search(f"based in {location}") and not US_COUNTRY_RE.search(location):
                    continue
                url = link.get("url") if isinstance(link, dict) else None
                if not isinstance(url, str) or not url.strip().lower().startswith(("https://", "http://")):
                    continue
                url = url.strip()
                domain = canonical_domain(url)
                if not is_first_party_candidate(domain) or domain == "drupal.org":
                    continue
                html = body.get("value") if isinstance(body, dict) else None
                if not isinstance(html, str):
                    continue
                source = f"https://www.drupal.org/node/{node_id}"
                description = " ".join(parse_html(html, source).blocks)
                if not self._SERVICES.search(description):
                    continue
                # Save flags and attribution only. The directory profile is not qualification evidence.
                candidate = Candidate(name=name.strip(), url=url, domain=domain, discovery_method=AUTOMATED,
                                      source=self.name, source_id=node_id, source_url=source,
                                      source_license=self.license_note, retrieved_at=retrieved_at,
                                      attrs={"directory_service_hint": True,
                                             "directory_frontend_hint": bool(self._FRONTEND.search(description))})
                found.setdefault(domain, candidate)
            if not data.get("next") or not rows:
                break
        self.run_note = (f"{records} directory records screened; {len(found)} distinct candidate domains "
                         "with US location and client-services wording in directory profiles")
        return list(found.values())


class OverpassAdapter(Adapter):
    """OpenStreetMap Overpass: US ``office=it`` objects that carry a ``website`` tag.

    Requires an explicit acknowledgement flag because the public instance's policy says
    commercial use should use self-hosted/paid servers, and OSM data is ODbL.
    """

    name = "openstreetmap"
    ENDPOINT = "https://overpass-api.de/api/interpreter"
    requires_ack = "overpass_terms"
    terms_note = ("Public Overpass instance: <=10k queries & 1GB/day (use ~1% for regular use), "
                  "identifying User-Agent, no parallel scripts, cache results, wait 30s after "
                  "429/406; commercial use should use self-hosted or paid servers.")
    license_note = "ODbL; (c) OpenStreetMap contributors"

    def __init__(self, client: ApiClient, acknowledged: bool, limit: int = 2000):
        require_zero_cost(self.name, self.cost_class)
        self.client = client
        self.acknowledged = acknowledged
        self.limit = limit

    def build_query(self) -> str:
        return ('[out:json][timeout:90];\n'
                'area["ISO3166-1"="US"][admin_level=2]->.us;\n'
                'nwr["office"="it"]["website"](area.us);\n'
                f'out tags center {int(self.limit)};')

    def parse(self, data: dict, retrieved_at: str) -> list[Candidate]:
        out: list[Candidate] = []
        for el in data.get("elements", []):
            tags = el.get("tags", {})
            site, name = tags.get("website"), tags.get("name")
            if not site or not name:
                continue
            if "://" not in site:
                site = "http://" + site
            attrs = {k: tags[k] for k in ("addr:state", "addr:city") if k in tags}
            attrs["country"] = "US"  # query is restricted to the US area
            out.append(Candidate(
                name=name, url=site, discovery_method=AUTOMATED, source=self.name,
                source_id=f"{el.get('type')}/{el.get('id')}",
                source_url=f"https://www.openstreetmap.org/{el.get('type')}/{el.get('id')}",
                source_license=self.license_note, retrieved_at=retrieved_at, attrs=attrs))
        return out

    def discover(self) -> list[Candidate]:
        if not self.acknowledged:
            raise DiscoveryBlocked(
                "openstreetmap/overpass skipped: needs --ack-overpass-terms (you confirm you have read "
                "the public-instance usage policy and accept its commercial-use caveat)")
        data = self.client.request_json("POST", self.ENDPOINT, form={"data": self.build_query()})
        return self.parse(data, utc_now_iso())


class ManualCsvAdapter(Adapter):
    """User-supplied ``name,url`` CSV. Always labelled ``manual``."""

    name = "manual_csv"

    def __init__(self, path: str | Path):
        require_zero_cost(self.name, self.cost_class)
        self.path = Path(path)

    def discover(self) -> list[Candidate]:
        if not self.path.exists():
            raise DiscoveryBlocked(f"manual csv not found: {self.path}")
        now = utc_now_iso()
        out: list[Candidate] = []
        with self.path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                name, url = (row.get("name") or "").strip(), (row.get("url") or "").strip()
                if name and url:
                    out.append(Candidate(name=name, url=url, discovery_method=MANUAL,
                                         source=self.name, retrieved_at=now,
                                         source_license="user-supplied"))
        return out


class SyntheticFixtureAdapter(Adapter):
    """FICTIONAL candidates from fixtures/synthetic/world.json. Pipeline testing only."""

    name = "synthetic"

    def __init__(self, world_path: str | Path):
        require_zero_cost(self.name, self.cost_class)
        self.world = json.loads(Path(world_path).read_text(encoding="utf-8"))

    def discover(self) -> list[Candidate]:
        now = utc_now_iso()
        return [Candidate(name=c["name"], url=c["url"], discovery_method=SYNTHETIC, source="synthetic",
                          retrieved_at=now, source_license="synthetic-test-data",
                          attrs=c.get("attrs", {}))
                for c in self.world["candidates"]]


KEYLESS_REGISTRY = {"drupal_org", "wikidata", "openstreetmap", "manual_csv", "synthetic"}


def build_adapters(names: list[str], *, client: ApiClient | None = None,
                   ack_overpass_terms: bool = False, manual_csv: str | None = None,
                   synthetic_world: str | None = None,
                   wikidata_limit: int = 500) -> list[Adapter]:
    """Build adapters by name. Unknown/paid/keyed names fail closed."""
    adapters: list[Adapter] = []
    for raw in names:
        n = raw.strip().lower()
        if n in ("overpass", "osm"):
            n = "openstreetmap"
        if n not in KEYLESS_REGISTRY:
            raise PaidApiBlocked(
                f"discovery source {raw!r} is not a registered free-keyless source "
                f"({sorted(KEYLESS_REGISTRY)}). Paid/keyed providers (Exa, Tavily, Brave, Hunter, "
                f"Apollo, ...) are blocked in the $0 pilot.")
        if n == "wikidata":
            adapters.append(WikidataAdapter(client or ApiClient(), limit=wikidata_limit))
        elif n == "drupal_org":
            adapters.append(DrupalOrgAdapter(client or ApiClient()))
        elif n == "openstreetmap":
            adapters.append(OverpassAdapter(client or ApiClient(), acknowledged=ack_overpass_terms))
        elif n == "manual_csv":
            if not manual_csv:
                raise DiscoveryBlocked("manual_csv source needs --manual-csv PATH")
            adapters.append(ManualCsvAdapter(manual_csv))
        elif n == "synthetic":
            if not synthetic_world:
                raise DiscoveryBlocked("synthetic source needs a world.json path")
            adapters.append(SyntheticFixtureAdapter(synthetic_world))
    return adapters
