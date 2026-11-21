"""Evidence extraction and classification.

Evidence levels (docs/VM1-START-HERE.md):
  source_supported  a first-party page (or a dataset record) STATES it. This is attribution,
                    not truth: "the page says X" never proves X.
  corroborated      source_supported by >= 2 independent origins (first-party page AND an
                    independent dataset record) that agree.
  user_verified     a human supplied it (labels file). Never produced by this code path.
  inferred          derived by rule from other evidence. Never asserted in drafts.
  unknown           not found / conflicting. Never guessed.

Rights hygiene: only short verbatim excerpts (<=200 chars, <=2 parts) are kept; no page bodies.
Every page-derived excerpt must be re-verifiable as a verbatim substring of the fetched page.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass, field
from typing import Iterable, Iterator

from .discovery import Candidate
from .htmlparse import PageData, norm_ws

SOURCE_SUPPORTED = "source_supported"
CORROBORATED = "corroborated"
USER_VERIFIED = "user_verified"
INFERRED = "inferred"
UNKNOWN = "unknown"
ASSERTABLE_LEVELS = frozenset({SOURCE_SUPPORTED, CORROBORATED, USER_VERIFIED})

EXCERPT_CAP = 200
MAX_EVIDENCE_PER_COMPANY = 40

STATE_ABBR = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM "
    "NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
).split()
STATE_NAMES = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC",
}
_ABBR_ALT = "|".join(STATE_ABBR)
_NAME_ALT = "|".join(sorted(STATE_NAMES, key=len, reverse=True))

US_ADDRESS_RE = re.compile(rf"\b[A-Z][A-Za-z.'’\- ]{{1,40}},\s*({_ABBR_ALT})\s+\d{{5}}(?:-\d{{4}})?\b")
US_BASED_RE = re.compile(
    rf"\b(?i:based|headquartered|located|offices?)\s+(?i:in)\s+[A-Z][A-Za-z.'’\- ]+?,\s*"
    rf"(?:({_ABBR_ALT})|(?i:({_NAME_ALT})))\b")
US_COUNTRY_RE = re.compile(r"\b(?:United States|U\.S\.A\.?|USA)\b")
US_COUNTRY_CONTEXT_RE = re.compile(r"\b(?:based|headquarter\w*|located|offices?|address)\b", re.I)

NON_US_PLACES = (
    "United Kingdom|UK|England|Scotland|Wales|London|Manchester|Canada|Toronto|Vancouver|Montreal|"
    "Australia|Sydney|Melbourne|India|Bangalore|Bengaluru|Pune|Hyderabad|Germany|Berlin|Poland|"
    "Warsaw|Krakow|Ukraine|Kyiv|Pakistan|Lahore|Karachi|Brazil|Netherlands|Amsterdam|Ireland|Dublin|"
    "Spain|Madrid|Barcelona|France|Paris|Singapore|Nigeria|Lagos|South Africa|Zimbabwe|Kenya|Mexico|"
    "Argentina|Portugal|Lisbon|Romania|Bulgaria|Vietnam|Philippines|Bangladesh|Sri Lanka|Egypt|"
    "Turkey|Israel|UAE|Dubai|Italy|Sweden|Denmark|Norway|Finland|Estonia|Lithuania|Latvia"
)
NON_US_RE = re.compile(
    rf"\b(?i:based|headquartered|located|offices?)\s+(?i:in)\s+"
    rf"(?:[A-Z][\w.'’\-]+(?:\s+[A-Z][\w.'’\-]+)*,?\s+)?({NON_US_PLACES})\b")
UK_POSTCODE_RE = re.compile(r"\b[A-Z]{1,2}\d[A-Z\d]?\s?\d[A-Z]{2}\b")
CA_POSTAL_RE = re.compile(r"\b[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z]\s?\d[ABCEGHJ-NPRSTV-Z]\d\b")

SERVICE_PATTERNS: dict[str, list[re.Pattern]] = {
    "react": [re.compile(r"\bReact(?:\.?js)?\b(?!\s+to\b)"), re.compile(r"\breact\.?js\b", re.I)],
    "nextjs": [re.compile(r"\bnext\.?js\b", re.I)],
    "typescript": [re.compile(r"\btypescript\b", re.I)],
    "frontend": [re.compile(r"\bfront[- ]?end\b", re.I)],
    "web_app": [re.compile(
        r"\b(?:web (?:apps?|applications?)|saas|dashboards?|(?:client|customer) portals?|admin panels?)\b",
        re.I)],
    "custom_software": [re.compile(
        r"\b(?:custom software|software development|product development|software engineering|"
        r"product engineering)\b", re.I)],
}
ENTITY_RE = re.compile(
    r"\b(?:software (?:studio|agency|development (?:company|agency|studio|firm|shop))|product studio|"
    r"digital (?:agency|studio|product studio)|development (?:studio|agency|shop)|"
    r"web (?:agency|studio|development (?:company|agency))|app development (?:company|agency)|"
    r"engineering studio|design (?:and|&) development (?:studio|agency))\b", re.I)
STAFFING_HARD_RE = re.compile(
    r"\b(?:(?:it|tech|technology|software|engineering) )?(?:staffing|recruiting|recruitment) "
    r"(?:agency|firm|company|services|solutions|partner)\b|"
    r"\b(?:talent (?:acquisition|placement)|executive search|headhunting)\b", re.I)
STAFF_AUG_RE = re.compile(
    r"\b(?:staff augmentation|dedicated (?:developers?|teams?) (?:for hire|on demand)|"
    r"hire (?:top |pre-vetted |vetted )?(?:developers|engineers)|offshore (?:development|developers|team))\b",
    re.I)
GLOBAL_CONSULTANCY_RE = re.compile(
    r"\b(?:global|worldwide|international) (?:consultancy|consulting (?:firm|company)|systems integrator)\b",
    re.I)
PORTFOLIO_RE = re.compile(
    r"\b(?:case stud(?:y|ies)|our work|portfolio|client work|our clients|selected work)\b", re.I)
HIRING_RE = re.compile(
    r"\b(?:we(?:'|’)re hiring|we are hiring|open (?:roles|positions)|join our team|careers)\b", re.I)

_NUM = r"(\d{1,3}(?:,\d{3})+|\d{1,6})"  # "12,000" must not parse as "000"
SIZE_PATTERNS = [
    re.compile(rf"\b(?:team|staff|company|crew) of (?:about |around |over |roughly |approximately |nearly )?{_NUM}\b", re.I),
    re.compile(rf"\b{_NUM}\+?\s+(?:full[- ]time\s+)?(?:employees|team members|engineers|developers|designers|people|professionals|specialists)\b", re.I),
    re.compile(rf"\b(?:employs|employing)\s+(?:over |more than |about |around )?{_NUM}\+?\b", re.I),
]


@dataclass
class PageSnapshot:
    url: str
    fetched_at: str
    page: PageData
    is_homepage: bool = False


@dataclass
class Evidence:
    id: str
    company_key: str
    claim_type: str
    value: str | int | None
    level: str
    source_type: str  # first_party_page | discovery_record | user_label
    source_url: str
    fetched_at: str
    excerpt: str
    excerpt_parts: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def make_id(company_key: str, claim_type: str, value, source_url: str, excerpt: str) -> str:
    raw = f"{company_key}|{claim_type}|{value}|{source_url}|{excerpt}".encode()
    return "ev_" + hashlib.sha1(raw).hexdigest()[:10]


def _window(text: str, start: int, end: int, pad: int = 80) -> str:
    """Short verbatim window around a match, trimmed to whole words at cut edges."""
    lo, hi = max(0, start - pad), min(len(text), end + pad)
    if lo > 0 and not text[lo - 1].isspace():
        nxt = text.find(" ", lo)
        lo = nxt + 1 if 0 <= nxt < start else lo
    if hi < len(text) and not text[hi].isspace():
        prv = text.rfind(" ", end, hi)
        hi = prv if prv > end else hi
    out = text[lo:hi].strip()
    if len(out) > EXCERPT_CAP:  # keep the match inside the cap
        cut = out[:EXCERPT_CAP]
        out = cut[: cut.rfind(" ")] if " " in cut[-30:] else cut
    return out


def _texts(snap: PageSnapshot) -> Iterator[str]:
    yield from snap.page.blocks
    for t in (snap.page.title, snap.page.meta_description):
        if t:
            yield t


def _find(snaps: Iterable[PageSnapshot], patterns: list[re.Pattern]):
    """First match across pages in order (homepage first). Yields (snap, text, match)."""
    for snap in snaps:
        for text in _texts(snap):
            for pat in patterns:
                m = pat.search(text)
                if m:
                    return snap, text, m
    return None


def _ev(company_key, claim_type, value, snap: PageSnapshot, text: str, m: re.Match, notes="") -> Evidence:
    excerpt = _window(text, m.start(), m.end())
    return Evidence(
        id=make_id(company_key, claim_type, value, snap.url, excerpt), company_key=company_key,
        claim_type=claim_type, value=value, level=SOURCE_SUPPORTED, source_type="first_party_page",
        source_url=snap.url, fetched_at=snap.fetched_at, excerpt=excerpt, excerpt_parts=[excerpt],
        notes=notes)


def _state_value(raw: str) -> str:
    return STATE_NAMES.get(raw.lower(), raw.upper())


def extract_evidence(company_key: str, snaps: list[PageSnapshot]) -> list[Evidence]:
    out: list[Evidence] = []

    # services (one evidence item per tag; first occurrence, homepage first)
    for tag, pats in SERVICE_PATTERNS.items():
        hit = _find(snaps, pats)
        if hit:
            out.append(_ev(company_key, f"service:{tag}", tag, *hit))

    hit = _find(snaps, [ENTITY_RE])
    if hit:
        out.append(_ev(company_key, "entity_type:studio_or_agency", "studio_or_agency", *hit))

    # location
    hit = _find(snaps, [US_ADDRESS_RE])
    if hit:
        snap, text, m = hit
        out.append(_ev(company_key, "location:us", _state_value(m.group(1)), snap, text, m,
                       "US street/city-state-ZIP pattern on first-party page"))
    else:
        hit = _find(snaps, [US_BASED_RE])
        if hit:
            snap, text, m = hit
            out.append(_ev(company_key, "location:us", _state_value(m.group(1) or m.group(2)), snap, text, m,
                           "'based/located in City, State' statement"))
        else:
            for snap in snaps:
                found = False
                for text in _texts(snap):
                    m = US_COUNTRY_RE.search(text)
                    if m and US_COUNTRY_CONTEXT_RE.search(text):
                        out.append(_ev(company_key, "location:us", "US", snap, text, m,
                                       "country mention with location wording"))
                        found = True
                        break
                if found:
                    break
    hit = _find(snaps, [NON_US_RE, UK_POSTCODE_RE, CA_POSTAL_RE])
    if hit:
        snap, text, m = hit
        value = m.group(1) if m.groups() else m.group(0)
        out.append(_ev(company_key, "location:non_us", value, snap, text, m,
                       "non-US place/postcode statement (detection is partial)"))

    # explicit team size; conflicting counts => unknown, never a guess
    sizes: dict[int, tuple[PageSnapshot, str, re.Match]] = {}
    for snap in snaps:
        for text in _texts(snap):
            for pat in SIZE_PATTERNS:
                for m in pat.finditer(text):
                    n = int(m.group(1).replace(",", ""))
                    if 1 <= n <= 100_000 and n not in sizes:
                        sizes[n] = (snap, text, m)
    if len(sizes) == 1:
        n, (snap, text, m) = next(iter(sizes.items()))
        out.append(_ev(company_key, "size:employees", n, snap, text, m,
                       "explicit count wording on first-party page; page statements can be stale"))
    elif len(sizes) > 1:
        n, (snap, text, m) = next(iter(sizes.items()))
        ev = _ev(company_key, "size:employees", None, snap, text, m,
                 f"conflicting explicit counts found: {sorted(sizes)}; treated as unknown")
        ev.level = UNKNOWN
        out.append(ev)

    # negatives / signals
    home_snaps = [s for s in snaps if s.is_homepage]
    other_snaps = [s for s in snaps if not s.is_homepage]
    hit = _find(home_snaps, [STAFFING_HARD_RE])
    if hit:
        out.append(_ev(company_key, "negative:staffing_recruiting", "staffing_recruiting", *hit,
                       notes="self-description on homepage"))
    else:
        hit = _find(other_snaps, [STAFFING_HARD_RE])
        if hit:
            out.append(_ev(company_key, "negative:staffing_mention", "staffing_mention", *hit,
                           notes="staffing/recruiting wording on a secondary page; needs review"))
    for ctype, pat, val in (("negative:staff_augmentation", STAFF_AUG_RE, "staff_augmentation"),
                            ("negative:global_consultancy", GLOBAL_CONSULTANCY_RE, "global_consultancy"),
                            ("signal:client_work", PORTFOLIO_RE, "client_work"),
                            ("signal:hiring_info_only", HIRING_RE, "hiring")):
        hit = _find(snaps, [pat])
        if hit:
            note = {"signal:client_work": "client work is NOT evidence of purchase intent",
                    "signal:hiring_info_only": "recorded for information; weight 0; hiring is NOT purchase intent",
                    }.get(ctype, "")
            out.append(_ev(company_key, ctype, val, *hit, notes=note))
    return out[:MAX_EVIDENCE_PER_COMPANY]


def apply_discovery_record(company_key: str, cand: Candidate | None, evidence: list[Evidence]) -> list[Evidence]:
    """Add dataset-record evidence; upgrade agreeing first-party location claims to corroborated."""
    if cand is None or cand.discovery_method == "manual" or not cand.attrs:
        return evidence
    out = list(evidence)
    src = cand.source_url or cand.source
    state = cand.attrs.get("addr:state")
    if cand.attrs.get("country") == "US":
        value = state or "US"
        excerpt = f"[{cand.source} {cand.source_id}] country: US" + (f", state: {state}" if state else "")
        out.append(Evidence(
            id=make_id(company_key, "location:us", value, src, excerpt), company_key=company_key,
            claim_type="location:us", value=value, level=SOURCE_SUPPORTED, source_type="discovery_record",
            source_url=src, fetched_at=cand.retrieved_at, excerpt=excerpt, excerpt_parts=[],
            notes=f"dataset record ({cand.source}); independent of the company's own site"))
        for ev in out:
            if ev.claim_type == "location:us" and ev.source_type == "first_party_page" \
                    and ev.level == SOURCE_SUPPORTED:
                if ev.value in ("US", value) or state is None or ev.value == state:
                    ev.level = CORROBORATED
                    ev.notes += "; corroborated by independent dataset record"
    emp = cand.attrs.get("employees")
    if isinstance(emp, int) and not any(e.claim_type == "size:employees" for e in out):
        excerpt = f"[{cand.source} {cand.source_id}] employees: {emp}"
        out.append(Evidence(
            id=make_id(company_key, "size:employees", emp, src, excerpt), company_key=company_key,
            claim_type="size:employees", value=emp, level=SOURCE_SUPPORTED, source_type="discovery_record",
            source_url=src, fetched_at=cand.retrieved_at, excerpt=excerpt, excerpt_parts=[],
            notes="dataset value; as-of date unknown; may be stale"))
    return out[:MAX_EVIDENCE_PER_COMPANY]


def verify_excerpt_parts(parts: list[str], page: PageData | None) -> bool:
    """Every part must be a verbatim (whitespace-normalised) substring of the cited page."""
    if page is None or not parts:
        return False
    texts = [norm_ws(t) for t in page.verifiable_texts()]
    for part in parts:
        p = norm_ws(part)
        if not p or not any(p in t for t in texts):
            return False
    return True


def verify_evidence(ev: Evidence, pages_by_url: dict[str, PageData]) -> bool:
    """Page-derived excerpts must be verbatim substrings of the page they cite."""
    if ev.source_type != "first_party_page":
        return ev.source_type == "discovery_record" and bool(ev.excerpt)
    if len(ev.excerpt) > EXCERPT_CAP * 2:
        return False
    return verify_excerpt_parts(ev.excerpt_parts, pages_by_url.get(ev.source_url))


def best(evidence: list[Evidence], prefix: str) -> list[Evidence]:
    return [e for e in evidence if e.claim_type.startswith(prefix) and e.level in ASSERTABLE_LEVELS]
