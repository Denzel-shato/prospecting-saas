"""Pick an Agency: bounded, documented, free agency-directory API.

Provider: https://www.pickanagency.com/developers
API: https://www.pickanagency.com/api/v1/search (keyless, CC BY 4.0).
Directory fields are discovery hints only, never qualification evidence.
Only official business websites are returned; no contacts or emails are collected.
"""
from __future__ import annotations

import re
import time
from urllib.parse import urlencode, urlsplit

from .canon import canonical_domain, is_first_party_candidate
from .discovery import AUTOMATED, Adapter, ApiClient, Candidate, DiscoveryBlocked
from .fetch import utc_now_iso
from .guard import FREE_KEYLESS, require_zero_cost


class PickAnAgencyAdapter(Adapter):
    name = "pickanagency"
    cost_class = FREE_KEYLESS
    ENDPOINT = "https://www.pickanagency.com/api/v1/search"
    SOURCE_NAME = "Pick an Agency"
    license_note = "CC BY 4.0; attribution: Pick an Agency (https://www.pickanagency.com)"
    terms_note = ("Documented, keyless read-only API, CC BY 4.0 attribution; "
                  "cache results, <1 request/second, no bulk harvesting")
    # Bounded hypotheses, not a claim about actual yield. The provider is
    # marketing/web-agency focused, not an exhaustive software-studio registry.
    # Prefer providers explicitly listing software development. Keyword searches
    # broaden the pool without forcing the unrelated "Web Design" filter.
    # "React" matches agency names and "Next.js" yielded nothing in a live probe.
    SEARCH_QUERIES = (
        {"service": "Software Development"},
        {"q": "custom software"},
        {"q": "software development"},
    )
    RESULT_LIMIT = 25
    # A "Software Development" directory category is NOT evidence of frontend
    # specialization. Boost only when the listing names explicit frontend work
    # or frontend technologies; first-party qualification still decides fit.
    _TECH = re.compile(r"\b(?:react(?:\.?js)?|next\.?js|typescript|front[\s-]?end|"
                       r"vue(?:\.?js)?|nuxt(?:\.?js)?|angular|svelte|headless)\b", re.I)
    _SERVICE = re.compile(r"\b(?:web design|web development|software development|"
                          r"app development|development|digital agency)\b", re.I)
    # First-party research, NOT directory labels, determines actual qualification.
    # These are only light-weight discovery ordering hints from the name/tagline.
    _SOFTWARE_FOCUS = re.compile(
        r"\b(?:custom software|bespoke software|software development|software solutions|"
        r"software studio|software agency|software consultancy|product studio|"
        r"product development|app development|app developers|development studio)\b", re.I)
    _MARKETING_FOCUS = re.compile(
        r"\b(?:seo|marketing|branding|advertising|social media|lead generation)\b", re.I)
    _US = {"us", "usa", "united states", "united states of america"}

    def __init__(self, client: ApiClient, *, worldwide: bool = False,
                 sleeper=time.sleep, search_terms: tuple[str, ...] | None = None):
        require_zero_cost(self.name, self.cost_class)
        self.client = client
        self.worldwide = worldwide
        self.sleeper = sleeper
        if search_terms is None:
            self.search_queries = self.SEARCH_QUERIES
        else:
            if not search_terms or len(search_terms) > 3 or any(
                    not isinstance(q, str) or not q.strip() or len(q) > 60 for q in search_terms):
                raise ValueError("pickanagency requires 1-3 short fixed search terms")
            self.search_queries = tuple({"q": q} for q in search_terms)
        self.yield_stats = {}
        self.run_note = ""

    def discover(self) -> list[Candidate]:
        seen: dict[str, Candidate] = {}
        stats = {key: 0 for key in (
            "queries", "records", "invalid_record", "geography_rejected",
            "no_website", "duplicate_domain", "frontend_hint", "candidates")}
        self.yield_stats = stats
        stamp = utc_now_iso()
        for i, query in enumerate(self.search_queries):
            if i:
                self.sleeper(1.1)  # provider requests to stay below 1/s
            params = urlencode({**query, "limit": self.RESULT_LIMIT})
            query_url = f"{self.ENDPOINT}?{params}"
            response = self.client.request_json("GET", query_url)
            stats["queries"] += 1
            if not isinstance(response, dict) or not isinstance(response.get("results"), list):
                raise DiscoveryBlocked("pickanagency: missing results list; schema may have changed")
            rows = response["results"]
            if len(rows) > self.RESULT_LIMIT:
                raise DiscoveryBlocked("pickanagency: results exceed documented limit")
            stats["records"] += len(rows)
            for row in rows:
                if not isinstance(row, dict):
                    stats["invalid_record"] += 1
                    continue
                name, website = row.get("name"), row.get("website")
                if not isinstance(name, str) or not name.strip():
                    stats["invalid_record"] += 1
                    continue
                loc = row.get("location") or {}
                country = loc.get("country", "") if isinstance(loc, dict) else ""
                country = country.strip().lower() if isinstance(country, str) else ""
                if (country == "india" and self.worldwide) or (
                        not self.worldwide and country not in self._US):
                    stats["geography_rejected"] += 1
                    continue
                if not isinstance(website, str) or urlsplit(website).scheme not in ("http", "https"):
                    stats["no_website"] += 1
                    continue
                domain = canonical_domain(website)
                if not is_first_party_candidate(domain) or domain == "pickanagency.com":
                    stats["no_website"] += 1
                    continue
                if domain in seen:
                    stats["duplicate_domain"] += 1
                    continue
                slug = row.get("slug", "")
                profile_url = row.get("profile_url", "")
                # Only retain a provider-owned first-party attribution URL.
                if not (isinstance(profile_url, str) and
                        urlsplit(profile_url).scheme == "https" and
                        canonical_domain(profile_url) == "pickanagency.com"):
                    profile_url = query_url
                services = row.get("services") if isinstance(row.get("services"), list) else []
                services = [s for s in services if isinstance(s, str)]
                tagline = row.get("tagline") if isinstance(row.get("tagline"), str) else ""
                wording = " ".join([tagline, *services])
                frontend = bool(self._TECH.search(wording))
                identity_wording = f"{name} {tagline}"
                software_focus = bool(self._SOFTWARE_FOCUS.search(identity_wording))
                marketing_focus = bool(self._MARKETING_FOCUS.search(identity_wording))
                seen[domain] = Candidate(
                    name=name.strip(), url=website.strip(), domain=domain,
                    discovery_method=AUTOMATED, source=self.name,
                    source_id=slug if isinstance(slug, str) else "",
                    source_url=profile_url,
                    source_license=self.license_note, retrieved_at=stamp,
                    attrs={"directory_service_hint": bool(self._SERVICE.search(wording)),
                           "directory_frontend_hint": frontend,
                           "directory_software_focus_hint": software_focus,
                           "directory_marketing_focus_hint": marketing_focus,
                           "directory_tagline": tagline[:200],
                           "country": country,
                           "directory_name": self.SOURCE_NAME,
                           "directory_discovery_query": dict(query)})
                stats["frontend_hint"] += int(frontend)
        stats["candidates"] = len(seen)
        self.run_note = (f"Pick an Agency API: {stats['queries']} bounded queries, "
                         f"{stats['records']} records, {len(seen)} unique agency websites; "
                         "directory signals are not qualification proof")
        return list(seen.values())
