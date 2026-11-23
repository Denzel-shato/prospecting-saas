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
from .discovery_hints import MARKETING_FOCUS, SOFTWARE_FOCUS
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
    # The documented API (openapi.json) has NO pagination or sort: `limit` caps at 25, so three queries can never
    # return more than 75 records and the only lever is WHICH slice each query asks for. The "legacy" profile is the
    # live-proven default (75 raw records collapsed to 37 unique domains, i.e. heavy overlap). "complementary"
    # replaces the free-text query that most plausibly duplicates the category filter with the documented
    # `industry` filter (studios that serve SaaS clients). It is a HYPOTHESIS: per-query yield is recorded so one
    # live run per profile (6 requests) can compare unique, relevant studios per query. Opt-in until measured.
    QUERY_PROFILES = {
        "legacy": SEARCH_QUERIES,
        "complementary": (
            {"service": "Software Development"},
            {"q": "custom software"},
            {"service": "Software Development", "industry": "SaaS"},
        ),
    }
    US_COUNTRY_FILTER = "United States"  # documented `country` example value
    # Directory `team_size` buckets (documented enum). A bucket whose LOWER bound already exceeds this is far outside
    # every shipped ICP's hard size maximum (250-1000), so it is screened out and counted, never silently dropped.
    # Self-reported, so it is a discovery screen only; it is NOT copied into `employees` (that would be
    # recorded as source-supported headcount evidence).
    TEAM_SIZE_BUCKETS = {"1-10": 1, "11-50": 11, "51-200": 51, "201-500": 201, "500+": 500}
    MAX_TEAM_SIZE_LOWER_BOUND = 250
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
    _SOFTWARE_FOCUS = SOFTWARE_FOCUS
    _MARKETING_FOCUS = MARKETING_FOCUS
    _US = {"us", "usa", "united states", "united states of america"}
    _INDIA = {"india", "in", "ind", "republic of india", "bharat"}

    def __init__(self, client: ApiClient, *, worldwide: bool = False,
                 sleeper=time.sleep, search_terms: tuple[str, ...] | None = None,
                 query_profile: str = "legacy"):
        require_zero_cost(self.name, self.cost_class)
        self.client = client
        self.worldwide = worldwide
        self.sleeper = sleeper
        if search_terms is None:
            if query_profile not in self.QUERY_PROFILES:
                raise ValueError(f"unknown pickanagency query profile {query_profile!r}; "
                                 f"known: {sorted(self.QUERY_PROFILES)}")
            self.search_queries = self.QUERY_PROFILES[query_profile]
        else:
            if not search_terms or len(search_terms) > 3 or any(
                    not isinstance(q, str) or not q.strip() or len(q) > 60 for q in search_terms):
                raise ValueError("pickanagency requires 1-3 short fixed search terms")
            self.search_queries = tuple({"q": q} for q in search_terms)
            query_profile = "custom_terms"
        self.query_profile = query_profile
        self.yield_stats = {}
        self.run_note = ""

    def _request_params(self, query: dict) -> dict:
        """Documented parameters only. In US mode the documented `country` filter is sent so no request is spent
        on records the US geography screen would reject anyway; the screen below still runs as a backstop."""
        params = dict(query)
        if not self.worldwide:
            params["country"] = self.US_COUNTRY_FILTER
        params["limit"] = self.RESULT_LIMIT
        return params

    @staticmethod
    def _clean_list(value, limit: int, width: int) -> list[str]:
        if not isinstance(value, list):
            return []
        return [v.strip()[:width] for v in value if isinstance(v, str) and v.strip()][:limit]

    def discover(self) -> list[Candidate]:
        seen: dict[str, Candidate] = {}
        stats = {key: 0 for key in (
            "queries", "records", "invalid_record", "geography_rejected", "country_unknown_kept",
            "no_website", "size_rejected", "team_size_known", "duplicate_domain", "frontend_hint", "candidates")}
        stats["query_profile"] = self.query_profile
        per_query: list[dict] = []
        self.yield_stats = stats
        stamp = utc_now_iso()
        for i, query in enumerate(self.search_queries):
            if i:
                self.sleeper(1.1)  # provider requests to stay below 1/s
            params = urlencode(self._request_params(query))
            query_url = f"{self.ENDPOINT}?{params}"
            response = self.client.request_json("GET", query_url)
            stats["queries"] += 1
            if not isinstance(response, dict) or not isinstance(response.get("results"), list):
                raise DiscoveryBlocked("pickanagency: missing results list; schema may have changed")
            rows = response["results"]
            if len(rows) > self.RESULT_LIMIT:
                raise DiscoveryBlocked("pickanagency: results exceed documented limit")
            stats["records"] += len(rows)
            q = {"query": dict(query), "records": len(rows), "new_candidates": 0, "duplicate_domain": 0,
                 "geography_rejected": 0, "size_rejected": 0, "no_website": 0, "invalid_record": 0,
                 "software_focus_hint": 0, "marketing_focus_hint": 0, "frontend_hint": 0}
            per_query.append(q)
            query_key = repr(sorted(query.items()))
            for row in rows:
                if not isinstance(row, dict):
                    stats["invalid_record"] += 1
                    q["invalid_record"] += 1
                    continue
                name, website = row.get("name"), row.get("website")
                if not isinstance(name, str) or not name.strip():
                    stats["invalid_record"] += 1
                    q["invalid_record"] += 1
                    continue
                loc = row.get("location") or {}
                country = loc.get("country", "") if isinstance(loc, dict) else ""
                country = country.strip().lower() if isinstance(country, str) else ""
                if (country in self._INDIA and self.worldwide) or (
                        not self.worldwide and country not in self._US):
                    stats["geography_rejected"] += 1
                    q["geography_rejected"] += 1
                    continue
                if self.worldwide and not country:
                    stats["country_unknown_kept"] += 1  # unknown is kept, but visible: India cannot be ruled out
                team_size = row.get("team_size")
                team_size = team_size.strip() if isinstance(team_size, str) else ""
                if team_size not in self.TEAM_SIZE_BUCKETS:
                    team_size = ""
                if team_size and self.TEAM_SIZE_BUCKETS[team_size] > self.MAX_TEAM_SIZE_LOWER_BOUND:
                    stats["size_rejected"] += 1
                    q["size_rejected"] += 1
                    continue
                if not isinstance(website, str) or urlsplit(website).scheme not in ("http", "https"):
                    stats["no_website"] += 1
                    q["no_website"] += 1
                    continue
                domain = canonical_domain(website)
                if not is_first_party_candidate(domain) or domain == "pickanagency.com":
                    stats["no_website"] += 1
                    q["no_website"] += 1
                    continue
                if domain in seen:
                    stats["duplicate_domain"] += 1
                    q["duplicate_domain"] += 1
                    hits = seen[domain].attrs["directory_discovery_queries"]
                    if query_key not in {repr(sorted(h.items())) for h in hits}:
                        hits.append(dict(query))
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
                rating = row.get("rating")
                attrs = {"directory_service_hint": bool(self._SERVICE.search(wording)),
                         "directory_frontend_hint": frontend,
                         "directory_software_focus_hint": software_focus,
                         "directory_marketing_focus_hint": marketing_focus,
                         "directory_tagline": tagline[:200],
                         # Provider category labels, kept so vm1.prequalify can compare them with the ICP's
                         # own vocabulary when ordering. Ordering hints only, never qualification evidence.
                         "directory_services": [s.strip()[:60] for s in services if s.strip()][:10],
                         "country": country,
                         "directory_name": self.SOURCE_NAME,
                         "directory_discovery_query": dict(query),
                         "directory_discovery_queries": [dict(query)],
                         # Self-reported directory metadata. Kept for audit/benchmarking only; none of it is
                         # copied into `employees` or any evidence claim.
                         "directory_team_size": team_size,
                         "directory_industries": self._clean_list(row.get("industries"), 10, 40)}
                city = loc.get("city") if isinstance(loc, dict) else None
                if isinstance(city, str) and city.strip():
                    attrs["directory_city"] = city.strip()[:60]
                if isinstance(rating, (int, float)) and not isinstance(rating, bool):
                    attrs["directory_rating"] = rating
                if isinstance(row.get("is_verified"), bool):
                    attrs["directory_verified"] = row["is_verified"]
                seen[domain] = Candidate(
                    name=name.strip(), url=website.strip(), domain=domain,
                    discovery_method=AUTOMATED, source=self.name,
                    source_id=slug if isinstance(slug, str) else "",
                    source_url=profile_url,
                    source_license=self.license_note, retrieved_at=stamp, attrs=attrs)
                stats["frontend_hint"] += int(frontend)
                stats["team_size_known"] += int(bool(team_size))
                q["new_candidates"] += 1
                q["software_focus_hint"] += int(software_focus)
                q["marketing_focus_hint"] += int(marketing_focus)
                q["frontend_hint"] += int(frontend)
        stats["candidates"] = len(seen)
        stats["per_query"] = per_query
        self.run_note = (f"Pick an Agency API ({self.query_profile} profile): {stats['queries']} bounded queries, "
                         f"{stats['records']} records, {len(seen)} unique agency websites; "
                         "directory signals are not qualification proof")
        return list(seen.values())
