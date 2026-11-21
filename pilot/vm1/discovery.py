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
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlencode, urlsplit

from . import USER_AGENT
from .canon import canonical_domain
from .fetch import NETWORK_ERRORS, PinnedTransport, Transport, utc_now_iso
from .guard import FREE_KEYLESS, PaidApiBlocked, require_zero_cost
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
    source: str  # wikidata | openstreetmap | manual_csv | synthetic
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
    """Tiny SSRF-safe JSON client for the two fixed keyless discovery hosts."""

    ALLOWED_HOSTS = {"query.wikidata.org", "overpass-api.de"}

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

    def build_query(self) -> str:
        return f"""SELECT ?item ?itemLabel ?website ?employees WHERE {{
  ?item wdt:P31 wd:{self.CLASS_SOFTWARE_COMPANY} .
  {{ ?item wdt:P17 wd:{self.COUNTRY_US} }} UNION {{ ?item wdt:P159/wdt:P17 wd:{self.COUNTRY_US} }}
  ?item wdt:P856 ?website .
  OPTIONAL {{ ?item wdt:P1128 ?employees . }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "en". }}
}} LIMIT {int(self.limit)}"""

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
            out.append(Candidate(name=name, url=site, discovery_method=AUTOMATED, source=self.name,
                                 source_id=item.rsplit("/", 1)[-1], source_url=item,
                                 source_license=self.license_note, retrieved_at=retrieved_at, attrs=attrs))
        return out

    def discover(self) -> list[Candidate]:
        self._verify_ids()
        data = self._get(self.build_query())
        return self.parse(data, utc_now_iso())


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


KEYLESS_REGISTRY = {"wikidata", "openstreetmap", "manual_csv", "synthetic"}


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
