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

from .context import (NON_OFFERING_KINDS, NON_SELF_KINDS, THIRD_PARTY_CTX, UNRELIABLE_CTX,
                      block_is_third_party, page_kind, sentence_bounds)
from .discovery import Candidate
from .htmlparse import PageData, norm_ws

SOURCE_SUPPORTED = "source_supported"
CORROBORATED = "corroborated"
USER_VERIFIED = "user_verified"
INFERRED = "inferred"
UNKNOWN = "unknown"
ASSERTABLE_LEVELS = frozenset({SOURCE_SUPPORTED, CORROBORATED, USER_VERIFIED})

EXCERPT_CAP = 200
MAX_EVIDENCE_PER_COMPANY = 60

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
    r"engineering studio|design (?:and|&) development (?:studio|agency)|"
    r"front-?end (?:agency|studio|shop|consultancy)|react (?:agency|studio|consultancy|development (?:shop|agency))|"
    r"custom software (?:development )?(?:company|agency|studio|shop)|software consultancy|"
    r"(?:software|product|web|mobile|app|digital|technology|e-?commerce|ecommerce)\s+(?:engineering|development|design(?: (?:and|&) (?:development|engineering))?)\s+"
    r"(?:firm|studio|agency|consultancy|shop)|"
    r"(?:design|development)\s+(?:and|&)\s+(?:development|engineering|strategy)\s+(?:firm|studio|agency|consultancy)|"
    r"(?:e-?commerce|ecommerce|shopify|headless)\s+(?:agency|studio|development (?:agency|studio|shop))|"
    r"(?:software|technology|product|engineering) consulting (?:firm|company|practice)|technology consultancy)\b", re.I)
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

# A number is a headcount candidate only if it is NOT part of a range ("20-50", "20 to 50") and
# NOT a fragment of a longer number. Ranges describe something vaguer than a headcount: unknown.
_NUM = (r"(\d{1,3}(?:,\d{3})+|\d{1,6})(?![\d])(?!,\d)(?!\s*(?:[-–—/]|to\b|and\b|or\b)\s*\d)\+?")
_APPROX = r"(?:about |around |over |roughly |approximately |nearly |more than |almost )?"
_SIZE_NOUN = (r"(?:full[- ]time\s+)?(?:employees|team members|engineers|developers|designers|people|"
              r"professionals|specialists|staff|experts|consultants)")
_TEAM_NOUN = r"(?:team|company|studio|agency|crew|firm)"
# Only SELF-REFERENTIAL wordings are accepted: the subject must be "we/our/the team/<company name>".
SELF_SIZE_PATTERNS = [
    re.compile(rf"\bwe(?:'|’)re (?:now |currently |only |just )?(?:an? )?(?:[\w-]+ ){{0,3}}?{_TEAM_NOUN} of {_APPROX}{_NUM}", re.I),
    re.compile(rf"\bwe are (?:now |currently |only |just )?(?:an? )?(?:[\w-]+ ){{0,3}}?{_TEAM_NOUN} of {_APPROX}{_NUM}", re.I),
    re.compile(rf"\b(?:our|the) (?:[\w-]+ ){{0,2}}?(?:team|company|studio|agency|firm|staff|crew) "
               rf"(?:is|has|numbers|consists of|comprises|includes|currently has|now has) (?:made up of )?{_APPROX}{_NUM}"
               rf"(?:\s+{_SIZE_NOUN})?", re.I),
    re.compile(rf"\bwe(?: currently| now)? (?:have|employ|are) {_APPROX}{_NUM}\s+{_SIZE_NOUN}", re.I),
    re.compile(rf"\bour {_NUM}\s+{_SIZE_NOUN}", re.I),
]
HIST_RE = re.compile(
    r"\b(?:started|began|begin|founded|launched|grew|grow|grown|growth|growing|was|were|had|used to|once|"
    r"originally|initially|formerly|previously|back in|acquired|acquisition|merged|joined forces|"
    r"from \d+|since (?:19|20)\d\d|in (?:19|20)\d\d|at the time|at one point)\b", re.I)
THIRD_PARTY_WORDS_RE = re.compile(r"\b(?:clients?|customers?|your|their|they|partners?|vendors?|users?)\b", re.I)
_LEGAL_WORDS = {"inc", "llc", "ltd", "co", "corp", "corporation", "company", "gmbh", "limited", "pllc",
                "lp", "llp", "group"}


def name_forms(company_key: str, company_name: str | None) -> list[str]:
    """Names the company calls itself: its listed name and the first label of its domain."""
    forms: set[str] = set()
    if company_name:
        toks = [t for t in re.findall(r"[A-Za-z0-9&'’]+", company_name) if t.lower() not in _LEGAL_WORDS]
        if toks:
            forms.add(" ".join(toks))
    label = (company_key or "").split(".")[0].replace("-", " ").strip()
    if len(label) >= 4:
        forms.add(label)
    return sorted(forms, key=len, reverse=True)


def _named_size_patterns(forms: list[str]) -> list[re.Pattern]:
    pats = []
    for f in forms:
        n = re.escape(f)
        pats.append(re.compile(rf"\b{n}\s+(?:is|has) (?:now |currently )?(?:an? )?(?:[\w-]+ ){{0,3}}?{_TEAM_NOUN} of {_APPROX}{_NUM}", re.I))
        pats.append(re.compile(rf"\b{n}\s+(?:has|employs|now has|currently has|currently employs) {_APPROX}{_NUM}\s+{_SIZE_NOUN}", re.I))
    return pats


def size_context_ok(text: str, m: re.Match) -> bool:
    """Reject a size match whose clause is historical, about clients/others, or otherwise not
    a present-tense statement by the company about its own headcount."""
    lo, _ = sentence_bounds(text, m.start(), m.end())
    cut = max([lo] + [lo + k.end() for k in re.finditer(r"[,;:–—]\s", text[lo:m.start()])])
    before = text[cut:m.start()]
    seg = text[cut:min(len(text), m.end() + 30)]
    if HIST_RE.search(seg):
        return False
    return not THIRD_PARTY_WORDS_RE.search(before)


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


# ---- self-description / offering context ----------------------------------------------------------
_VERB = (r"(?:design|build|develop|ship|deliver|create|engineer|craft|launch|implement|architect|"
         r"maintain|modernis[ez]e|migrate)")
OFFER_RE = re.compile(
    rf"\b(?:we|our (?:team|studio|agency|engineers|developers|designers))\s+"
    rf"(?:(?:also|primarily|mainly|mostly|proudly|can|will)\s+)?"
    rf"(?:{_VERB}|specialis[ez]e?s? in|specializ\w* in|focus(?:es)? on|provide|offer|"
    rf"help(?:s)?\b[^.!?]{{0,50}}?\b{_VERB})\b"
    r"|\b(?:studio|agency|firm|shop|consultancy|company|team)\s+(?:that |which |who )?"
    r"(?:specializ\w+|specialis\w+|build(?:s|ing)|design(?:s|ing)|develop(?:s|ing)|deliver(?:s|ing)|focus\w*)\b"
    r"|\bour (?:services|expertise|capabilities)\b|\b(?:services|expertise|capabilities)\s+(?:include|includes|are)\b"
    r"|\b(?:is|are) our (?:core|focus|specialty|specialism|speciality|craft)\b"
    r"|\b(?:react|next\.?js|typescript|front-?end|web app\w*|custom software)\s+"
    r"(?:development|engineering|consulting|services)\b", re.I)
# Additional client-development offering structures (Issue #3). Each is only a MARKER inside a sentence that
# also contains the technology keyword; PRODUCT_FEATURE_RE below still vetoes product/feature wording.
CUSTOM_BUILD_RE = re.compile(
    r"\bcustom\s+(?:[\w-]+\s+){0,2}?(?:storefronts?|e-?commerce\s+(?:sites?|stores?|builds?)|websites?|web\s?sites?|"
    r"web\s?apps?|web applications?|software|apps?|integrations?|builds?|sites?|themes?)\b", re.I)
SECOND_PERSON_RE = re.compile(r"\b(?:you|your|you(?:'|’)re|you(?:'|’)ll)\b", re.I)
ENGAGEMENT_RE = re.compile(
    r"\b(?:the|our) (?:firm|studio|agency|company|team)(?:'|’)s\s+(?:[\w-]+\s+){0,3}?"
    r"(?:consulting engagements?|client engagements?|client work|client projects?|engagements?|product development|"
    r"software development|development work)\b|"
    r"\b(?:we|our team)\b[^.!?]{0,60}?\b(?:project[- ]based|fixed[- ](?:price|scope|fee|bid)|"
    r"time (?:and|&) materials|retainers?|commissioned (?:development|work|projects?)|project delivery)\b", re.I)
OFFER_HEADING_RE = re.compile(
    r"\b(?:what we (?:do|build|make|offer|design|create|deliver)|(?:our )?services|capabilities|expertise|"
    r"how we (?:help|work)|we (?:build|design|develop)|specialt(?:y|ies)|offerings)\b", re.I)
# Wording typical of a PRODUCT describing itself (features, supported languages, docs, integrations).
PRODUCT_FEATURE_RE = re.compile(
    r"\b(?:support(?:s|ed|ing)?|integrat\w+|compatible|sdks?|apis?|plugins?|extensions?|programming languages|"
    r"languages|frameworks?|libraries|templates?|our (?:platform|product|app|tool|software|dashboard|portal)|"
    r"the platform|lets you|allows you|enables you|features?|powered by|import|export)\b", re.I)
SELF_PREFIX_RE = re.compile(
    r"(?:\bwe(?:'|’)re|\bwe are|\bwe(?:'|’)ve become|\bis|\bare|\bas|\bour)\b(?:\s+[\w'’-]+){0,6}\s*$", re.I)
ENTITY_BLOCKERS_RE = re.compile(
    r"\b(?:integrat\w*|partner\w*|agencies|clients?|customers?|users?|members?|platform|product|tool|"
    r"trusted by|used by|works? with|compatible|marketplace|directory|reviews?|vs\.?|than|hire|find|like|"
    r"such as|including|alongside|for)\b", re.I)
CLIENT_SERVICES_RE = re.compile(
    r"\bwe\s+(?:(?:also|primarily|mainly|mostly)\s+)?(?:design|build|develop|ship|deliver|create|engineer|craft)\b"
    r"[^.!?]{0,100}?\bfor\s+(?:our\s+|their\s+)?(?:clients?\b|(?:[\w-]+[ -]){0,2}?"
    r"(?:startups?|founders|scale-?ups|businesses|brands|companies|enterprises|organi[sz]ations)\b)"
    r"|\bour clients\s+(?:include|are|range)\b"
    r"|\bwe\s+(?:partner|work)\s+with\s+(?:[\w-]+\s+){0,3}?(?:startups?|founders|scale-?ups|businesses|brands|"
    r"companies|enterprises|organi[sz]ations|clients?)\s+to\s+(?:design|build|develop|ship|launch|create|deliver)\b"
    r"|\bwe\s+(?:take on|run|lead|deliver|handle)\b[^.!?]{0,40}\b(?:consulting|client|project)\s+(?:engagements?|projects?|work)\b",
    re.I)
CONSULTING_ENGAGEMENT_RE = re.compile(
    r"\b(?:the|our) (?:firm|studio|agency)(?:'|’)s\s+(?:[\w-]+\s+){0,2}?(?:consulting|client)\s+"
    r"(?:engagements?|work|projects?)\b", re.I)

# Signals that the site belongs to a PRODUCT vendor / large corporation rather than a services studio.
VENDOR_SIGNALS: dict[str, tuple[re.Pattern, int]] = {
    "free_trial": (re.compile(r"\bfree trial\b|\b(?:start|get|try)\b[^.]{0,15}\bfor free\b|\bget started (?:for )?free\b|"
                              r"\bfree forever\b|\b(?:start|try) free\b", re.I), 90),
    "request_demo": (re.compile(r"\b(?:request|book|schedule|watch|get) (?:a |an |the |your )?(?:live |product |free )?demo\b", re.I), 90),
    "account_signup": (re.compile(r"\b(?:sign[- ]?up|sign[- ]?in|log[- ]?in|create (?:a |an |your )?(?:free )?account)\b", re.I), 60),
    "pricing_plans": (re.compile(r"^(?:pricing|plans|plans (?:and|&) pricing|pricing (?:and|&) plans|see pricing|view pricing)$", re.I), 40),
    "docs_integrations": (re.compile(r"^(?:integrations?|api(?: docs| documentation| reference)?|documentation|"
                                     r"developers?|developer docs|docs|changelog|status|trust center)$", re.I), 40),
    "our_platform": (re.compile(r"\bour\s+(?:[\w-]+\s+){0,2}platform\b|\ball-in-one platform\b|"
                                r"\b(?:[\w-]+\s+){1,2}platform that\b", re.I), 400),
    "customers_at_scale": (re.compile(r"\b(?:trusted|used|loved) by (?:over |more than |nearly )?(?:[\d,]+\+?|thousands|millions|hundreds)\b"
                                      r"[^.]{0,40}\b(?:teams|companies|developers|customers|users)\b|"
                                      r"\b(?:trusted|used|loved) by\b[^.]{0,40}\b(?:teams|companies|developers|customers|users)\b"
                                      r"[^.]{0,25}\b(?:worldwide|globally|around the world)\b|"
                                      r"\b[\d,]+\+? (?:customers|users|teams|developers|companies) "
                                      r"(?:worldwide|around the world|trust|use)\b|"
                                      r"\b(?:millions?|thousands?) of (?:customers|users|developers|teams)\b", re.I), 400),
}
ENTERPRISE_SIGNALS: dict[str, tuple[re.Pattern, int]] = {
    "listed_company": (re.compile(r"\b(?:NASDAQ|NYSE):|\bpublicly[- ]traded\b|\bstock (?:symbol|ticker)\b", re.I), 400),
    "global_scale": (re.compile(r"\b(?:offices|presence|employees|customers) in \d+ countries\b|"
                                r"\b(?:global|worldwide) (?:leader|provider|enterprise|technology company)\b", re.I), 400),
    "enterprise_positioning": (re.compile(r"\benterprise[- ](?:grade|class|software|platform|customers)\b|\bSOC ?2\b|"
                                          r"\bSAML\b|\bsingle sign-on\b|\bFedRAMP\b", re.I), 400),
}


def _items(snap: PageSnapshot):
    """(text, block_index, page_kind, ctx_labels, third_party) for every text the page offers."""
    kind = page_kind(snap.url, snap.is_homepage)
    page = snap.page
    for i, text in enumerate(page.blocks):
        yield text, i, kind, page.ctx_at(i), block_is_third_party(page, i)
    for t in (page.title, page.meta_description):
        if t:
            yield t, -1, kind, frozenset(), False


def _signal_items(snap: PageSnapshot):
    """Items plus each short link label: nav/CTA labels are often inline anchors that share one
    block, and a link label is always a verbatim substring of its block."""
    yield from _items(snap)
    kind = page_kind(snap.url, snap.is_homepage)
    for _href, label in snap.page.links:
        if label and len(label) <= 90:
            yield label, -1, kind, frozenset(), False


def entity_self_referential(text: str, m: re.Match) -> bool:
    """The studio/agency noun phrase describes the company itself ("X is a software studio",
    "We're a product studio"), not a client, partner, integration or directory listing."""
    lo, _ = sentence_bounds(text, m.start(), m.end())
    clause = text[lo:m.start()]
    if ENTITY_BLOCKERS_RE.search(clause):
        return False
    return len(clause.split()) <= 3 or bool(SELF_PREFIX_RE.search(clause))


def _adjacent_offer(page, i: int) -> bool:
    """A list item whose lead-in block ("We design and build:") or governing heading says the company offers it."""
    if page is None or i < 0:
        return False
    if OFFER_HEADING_RE.search(page.section_at(i)):
        return True
    for j in (i - 1, i - 2):
        if 0 <= j < len(page.blocks) and not (page.ctx_at(j) & UNRELIABLE_CTX) and not block_is_third_party(page, j):
            prev = page.blocks[j].rstrip()
            if prev.endswith(":") and (OFFER_RE.search(prev) or ENGAGEMENT_RE.search(prev)):
                return True
    return False


def _offering(text: str, m: re.Match, kind: str, ctx, third_party: bool, page=None, i: int = -1) -> bool:
    """True when the technology match sits in wording where the company offers it to clients."""
    if third_party or (ctx & UNRELIABLE_CTX) or kind in NON_OFFERING_KINDS:
        return False
    lo, hi = sentence_bounds(text, m.start(), m.end())
    sent = text[lo:hi]
    offer = OFFER_RE.search(sent) is not None
    if PRODUCT_FEATURE_RE.search(sent) and not offer:
        return False
    if offer:
        return True
    if kind == "services" and len(text) <= 220:
        return True  # a short services-page list item is the company listing its own services
    if ENGAGEMENT_RE.search(sent):
        return True  # firm-possessive engagements / delivery model ("the firm's consulting engagements")
    if CUSTOM_BUILD_RE.search(sent) and not SECOND_PERSON_RE.search(sent):
        return True  # "Custom storefronts on ... headless on Next.js." (no "you": not product-feature copy)
    if len(text) <= 300 and _adjacent_offer(page, i):
        return True  # short item under a services/what-we-build heading or an offering lead-in line
    return any(entity_self_referential(sent, e) for e in ENTITY_RE.finditer(sent))


def _ev_from(company_key, claim_type, value, snap, text, m, notes="") -> Evidence:
    return _ev(company_key, claim_type, value, snap, text, m, notes)


def _service_evidence(company_key: str, snaps: list[PageSnapshot], tag: str, pats: list[re.Pattern]):
    """Returns (offering_evidence | None, mention_evidence | None). A mention is a technology
    keyword WITHOUT offering context (feature lists, docs, testimonials, client work, ...): it is
    recorded for transparency but earns nothing."""
    mention = None
    for snap in snaps:
        for text, _i, kind, ctx, tp in _items(snap):
            for pat in pats:
                m = pat.search(text)
                if not m:
                    continue
                if _offering(text, m, kind, ctx, tp, snap.page, _i):
                    return _ev(company_key, f"service:{tag}", tag, snap, text, m,
                               "company describes offering this to clients"), None
                if mention is None:
                    mention = _ev(company_key, f"mention:{tag}", tag, snap, text, m,
                                  "keyword present WITHOUT evidence the company offers it as a client service "
                                  "(feature/docs/testimonial/client-work/generic wording); weight 0")
    return None, mention


def _identity_evidence(company_key: str, snaps: list[PageSnapshot]) -> list[Evidence]:
    out: list[Evidence] = []
    for snap in snaps:
        for text, _i, kind, ctx, tp in _items(snap):
            if tp or (ctx & UNRELIABLE_CTX) or kind in NON_SELF_KINDS:
                continue
            for m in ENTITY_RE.finditer(text):
                if entity_self_referential(text, m):
                    out.append(_ev(company_key, "entity_type:studio_or_agency", "studio_or_agency", snap, text, m,
                                   "self-referential studio/agency wording"))
                    return out
    for snap in snaps:
        for text, _i, kind, ctx, tp in _items(snap):
            if tp or (ctx & UNRELIABLE_CTX) or kind in NON_SELF_KINDS:
                continue
            m = CLIENT_SERVICES_RE.search(text)
            if m:
                out.append(_ev(company_key, "entity_type:client_services", "client_services", snap, text, m,
                               "company says it builds for clients (no studio/agency noun found)"))
                return out
    # weakest route: the firm speaks of ITS OWN consulting/client engagements (also on a team bio). Counts toward
    # agency identity only when no vendor/enterprise profile exists (see score.classify_company); never shields.
    for snap in snaps:
        for text, _i, kind, ctx, tp in _items(snap):
            if tp or (ctx & UNRELIABLE_CTX) or kind in NON_SELF_KINDS:
                continue
            m = CONSULTING_ENGAGEMENT_RE.search(text)
            if m:
                out.append(_ev(company_key, "entity_type:consulting_engagements", "consulting_engagements", snap, text, m,
                               "firm refers to its own consulting/client engagements (weak identity; does not override vendor signals)"))
                return out
    return out


# A negated mention ("No free trial needed", "It's not the platform") is not a vendor/enterprise signal.
NEGATION_RE = re.compile(
    r"\b(?:not|no|never|without|rather than|instead of|beyond|aren(?:'|’)t|isn(?:'|’)t|don(?:'|’)t|doesn(?:'|’)t)\b|n(?:'|’)t\b",
    re.I)


def _negated(text: str, m: re.Match) -> bool:
    lo, _ = sentence_bounds(text, m.start(), m.end())
    return NEGATION_RE.search(text[lo:m.start()][-40:]) is not None


def _signal_evidence(company_key: str, snaps: list[PageSnapshot], claim: str,
                     table: dict[str, tuple[re.Pattern, int]], note: str) -> list[Evidence]:
    out: list[Evidence] = []
    for cat, (pat, maxlen) in table.items():
        done = False
        for snap in snaps:
            for text, _i, kind, ctx, tp in _signal_items(snap):
                if tp or kind in ("editorial", "docs") or len(text) > maxlen:
                    continue
                m = next((x for x in pat.finditer(text) if not _negated(text, x)), None)
                if m:
                    out.append(_ev(company_key, claim, cat, snap, text, m, note))
                    done = True
                    break
            if done:
                break
    return out


CLIENT_WORK_RE = re.compile(
    r"\b(?:selected work|our work|client work|our portfolio|portfolio|our clients|case stud(?:y|ies)|"
    r"we(?:'|’)ve (?:built|delivered|shipped)|we have (?:built|delivered|shipped))\b", re.I)


def _client_work_evidence(company_key: str, snaps: list[PageSnapshot]):
    """Client-work wording that is more than a bare nav/footer label such as 'Case studies'."""
    for snap in snaps:
        for text, _i, kind, ctx, tp in _items(snap):
            if tp or (ctx & UNRELIABLE_CTX):
                continue
            m = CLIENT_WORK_RE.search(text)
            if m and (len(text.split()) >= 5 or kind == "work"):
                return _ev(company_key, "signal:client_work", "client_work", snap, text, m,
                           "client work is NOT evidence of purchase intent")
    return None


def _size_evidence(company_key: str, snaps: list[PageSnapshot], company_name: str | None):
    pats = SELF_SIZE_PATTERNS + _named_size_patterns(name_forms(company_key, company_name))
    sizes: dict[int, tuple[PageSnapshot, str, re.Match]] = {}
    for snap in snaps:
        for text, _i, kind, ctx, tp in _items(snap):
            if tp or (ctx & THIRD_PARTY_CTX) or kind in NON_SELF_KINDS:
                continue
            for pat in pats:
                for m in pat.finditer(text):
                    if not size_context_ok(text, m):
                        continue
                    n = int(m.group(1).replace(",", ""))
                    if 1 <= n <= 100_000 and n not in sizes:
                        sizes[n] = (snap, text, m)
    if len(sizes) == 1:
        n, (snap, text, m) = next(iter(sizes.items()))
        return _ev(company_key, "size:employees", n, snap, text, m,
                   "self-referential present-tense headcount wording; page statements can be stale")
    if len(sizes) > 1:
        n, (snap, text, m) = next(iter(sizes.items()))
        ev = _ev(company_key, "size:employees", None, snap, text, m,
                 f"conflicting explicit counts found: {sorted(sizes)}; treated as unknown")
        ev.level = UNKNOWN
        return ev
    return None


def extract_evidence(company_key: str, snaps: list[PageSnapshot],
                     company_name: str | None = None) -> list[Evidence]:
    out: list[Evidence] = []

    # company identity / type signals first so they can never be truncated away
    out += _identity_evidence(company_key, snaps)
    out += _signal_evidence(company_key, snaps, "company_type:saas_vendor_signal", VENDOR_SIGNALS,
                            "product-vendor wording (trial/demo/account/platform/docs); weight 0 alone")
    out += _signal_evidence(company_key, snaps, "company_type:enterprise_signal", ENTERPRISE_SIGNALS,
                            "large/listed-corporation wording; weight 0 alone")

    # services: only wording where the company offers the service to clients (see _offering)
    mentions: list[Evidence] = []
    for tag, pats in SERVICE_PATTERNS.items():
        offered, mention = _service_evidence(company_key, snaps, tag, pats)
        if offered:
            out.append(offered)
        elif mention:
            mentions.append(mention)

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

    # explicit, self-referential team size; ranges/history/third-party/conflicts => unknown
    size_ev = _size_evidence(company_key, snaps, company_name)
    if size_ev:
        out.append(size_ev)

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
                            ("signal:hiring_info_only", HIRING_RE, "hiring")):
        hit = _find(snaps, [pat])
        if hit:
            note = {"signal:hiring_info_only": "recorded for information; weight 0; hiring is NOT purchase intent",
                    }.get(ctype, "")
            out.append(_ev(company_key, ctype, val, *hit, notes=note))
    cw = _client_work_evidence(company_key, snaps)
    if cw:
        out.append(cw)
    out += mentions
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
