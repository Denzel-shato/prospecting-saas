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

from .context import assertive, matches_self, name_alternation, page_kind, sentences
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

# --- service OFFERING detection (Issue #2) -----------------------------------------------------
# A technology word alone proves nothing (docs, supported-language lists, product copy, testimonials).
# A service claim needs an offering structure: "<we/our/Name> build|design|develop ... <tech>", a
# service noun phrase ("React development", "Next.js engineers"), or a short item on a services page.
T_REACT = r"(?:\bReact(?:\.?js)?\b(?!\s+(?:to|on)\b)|(?i:\breact\.?js\b))"
TECH_SRC = {
    "react": T_REACT,
    "nextjs": r"(?i:\bnext\.?js\b)",
    "typescript": r"(?i:\btypescript\b)",
    "frontend": r"(?i:\bfront[- ]?end\b)",
    "web_app": r"(?i:\b(?:web (?:apps?|applications?)|saas|dashboards?|(?:client|customer) portals?|admin panels?)\b)",
    "custom_software": r"(?i:\b(?:custom software|software development|product development|software engineering|product engineering)\b)",
}
TECH_RE = {k: re.compile(v) for k, v in TECH_SRC.items()}
SERVICE_NOUN = r"(?i:\b(?:development|developers?|engineering|engineers?|consult\w+|services?|agency|studio|experts?|specialists?|design)\b)"
NOUN_PHRASE_SRC = {
    "react": rf"{T_REACT}[\w\s/&,.\-]{{0,25}}?{SERVICE_NOUN}",
    "nextjs": rf"{TECH_SRC['nextjs']}[\w\s/&,.\-]{{0,25}}?{SERVICE_NOUN}",
    "typescript": rf"{TECH_SRC['typescript']}[\w\s/&,.\-]{{0,25}}?{SERVICE_NOUN}",
    "frontend": rf"{TECH_SRC['frontend']}[\w\s/&,.\-]{{0,25}}?{SERVICE_NOUN}",
    "web_app": r"(?i:\b(?:(?:web|saas|mobile|custom)\s+(?:apps?|applications?|dashboards?|portals?)\s+(?:development|engineering|design|services?)|"
               r"(?:dashboard|portal|saas)\s+(?:development|design|engineering))\b)",
    "custom_software": r"(?i:\b(?:(?:custom software|software|product|web|mobile|app)\s+(?:development|engineering)\s+"
                       r"(?:services?|agency|company|studio|firm|partner|team|shop)|custom software\s+(?:development|engineering))\b)",
}
NOUN_PHRASE_RE = {k: re.compile(v) for k, v in NOUN_PHRASE_SRC.items()}
OFFER_VERBS = r"(?i:\b(?:build|design|develop|deliver|craft|specializ|specialis|ship|engineer|creat)\w*\b)"
PRODUCT_CUE = re.compile(
    r"(?i)\b(?:supports?|supported|supporting|integrat\w+|sdks?|apis?|compatible|programming languages|plugins?|"
    r"extensions?|libraries|library|works with|runs on)\b")
AUDIENCE_BEFORE = re.compile(r"(?i)\b(?:for|by)\s+(?:\w+\s+)?$")
SERVICES_PAGE_MAX = 200
_OFFER_CACHE: dict[str, dict[str, re.Pattern]] = {}


def _offer_patterns(names: set[str]) -> dict[str, re.Pattern]:
    alt = name_alternation(names)
    if alt not in _OFFER_CACHE:
        subj = rf"(?:(?i:\bwe\b|\bour (?:team|studio|agency|engineers|developers|designers|company)\b)|\b(?i:{alt})\b)"
        _OFFER_CACHE[alt] = {k: re.compile(rf"{subj}[^.]{{0,80}}?{OFFER_VERBS}[^.]{{0,120}}?(?P<t>{v})")
                             for k, v in TECH_SRC.items()}
    return _OFFER_CACHE[alt]


def offering_matches(text: str, kind: str, names: set[str]) -> list[tuple[str, int, int, str]]:
    """(tag, start, end, basis) service-OFFERING statements in ``text``. Product copy yields none."""
    found: list[tuple[str, int, int, str]] = []
    offer = _offer_patterns(names)
    for sent in sentences(text):
        base = text.find(sent)
        if base < 0 or PRODUCT_CUE.search(sent):
            continue
        for tag in TECH_SRC:
            hit = None
            m = offer[tag].search(sent)
            if m:
                hit = (m.start("t"), m.end("t"), "first_person_offering")
            else:
                m = NOUN_PHRASE_RE[tag].search(sent)
                if m:
                    hit = (m.start(), m.end(), "service_noun_phrase")
            if hit is None and kind == "services" and len(sent) <= SERVICES_PAGE_MAX:
                m = TECH_RE[tag].search(sent)
                if m:
                    hit = (m.start(), m.end(), "services_page_item")
            if hit and not AUDIENCE_BEFORE.search(sent[:hit[0]]):
                found.append((tag, base + hit[0], base + hit[1], hit[2]))
    return found


# --- company identity cues ------------------------------------------------------------------
AGENCY_NOUN = (r"(?i:(?:agency|studio|consultancy|consulting (?:firm|company|group)|dev(?:elopment)? shop|"
               r"boutique|collective|(?:engineering|development|product|software) partner)\b)")
AGENCY_TITLE_RE = re.compile(
    rf"{AGENCY_NOUN}|(?i:\b(?:software|web|app|mobile|custom software|product) development (?:company|agency|studio|firm|partner|services)\b)")
OUR_STUDIO_RE = re.compile(r"(?i)\bour (?:studio|agency|consultancy|dev shop)\b")
CS_FOR_RE = re.compile(
    r"(?i)\bwe\b[^.]{0,40}\b(?:build|design|develop|deliver|craft|ship)\w*\b[^.]{0,80}\bfor\s+(?:\w+\s+){0,2}"
    r"(?:startups?|founders?|clients?|businesses|brands|enterprises|companies|scale-?ups|customers)\b")
CS_CTA_RE = re.compile(
    r"(?i)\b(?:start (?:a|your) project|get a (?:free )?quote|request a quote|hire us|work with us|"
    r"discovery call|tell us about your project)\b")
CS_CLIENTS_RE = re.compile(
    r"(?i)\b(?:our clients|client (?:work|projects?)|for our clients|we(?:'ve| have)? (?:built|shipped|delivered|launched)\b[^.]{0,60}\bfor)\b")
VENDOR_CUES = {
    "free_trial": re.compile(r"(?i)\b(?:start (?:your |a )?free trial|free trial|try (?:it )?for free|get started for free|start for free|sign up (?:for )?free)\b"),
    "demo": re.compile(r"(?i)\b(?:book|request|schedule|watch|get)(?: a| your)? demo\b"),
    "pricing": re.compile(r"(?i)^(?:pricing|plans(?: (?:&|and) pricing)?)$|\bpricing plans?\b|\bper (?:user|seat|month|member)\b|\bcompare plans\b"),
    "login": re.compile(r"(?i)^(?:log ?in|sign ?in|sign ?up|login|register)$"),
    "platform": re.compile(
        r"(?i)\b(?:our|the|an?) (?:all-in-one |end-to-end |unified |cloud |ai-powered |ai |saas |intelligent |devsecops )*"
        r"(?:platform|saas|software platform)\b[^.]{0,60}\b(?:helps?|lets?|enables?|allows?|powers?|gives?|automates?|supports?|is)\b|"
        r"\b(?:the|an?) [\w\- ]{0,40}\bplatform (?:for|that|to)\b|\bplatform\b[^.]{0,30}\bfaster\b"),
    "api_docs": re.compile(r"(?i)\bapi (?:docs|reference)\b|\bdeveloper docs\b"),
}
ENTERPRISE_CUES = {
    "listed": re.compile(r"\b(?:NASDAQ|NYSE)\s*:\s*[A-Z]{1,5}\b|(?i:\bpublicly[- ]traded\b)"),
    "fortune": re.compile(r"(?i)\bFortune\s+(?:100|500|1000)\b"),
    "global_leader": re.compile(r"(?i)\bglobal (?:leader|enterprise)\b|\boffices (?:in|across) \d+ countries\b"),
}

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
HIRING_RE = re.compile(
    r"\b(?:we(?:'|’)re hiring|we are hiring|open (?:roles|positions)|join our team|careers)\b", re.I)

# --- employee count: ONLY clearly self-referential, current, scalar statements -------------------
_NUM = r"(\d{1,3}(?:,\d{3})+|\d{1,6})"  # "12,000" must not parse as "000"
SIZE_PATTERNS = [
    re.compile(rf"\b(?:team|staff|company|crew) of (?:about |around |roughly |approximately )?{_NUM}\b", re.I),
    re.compile(rf"\b{_NUM}\+?\s+(?:full[- ]time\s+)?(?:employees|team members|engineers|developers|designers|people|professionals|specialists)\b", re.I),
    re.compile(rf"\b(?:employs|employing)\s+(?:about |around )?{_NUM}\+?\b", re.I),
]
SIZE_QUANT_BEFORE = re.compile(
    r"(?i)(?:\d\s*(?:-|–|—|to)\s*|\b(?:over|more than|up to|under|less than|at least|fewer than)\s+)$")
SIZE_PAST = re.compile(
    r"(?i)\b(?:grew|grown|growing|scaled|scaling|started|began|founded|previously|formerly|used to|once|back in|"
    r"years ago|before|from \d|when we|at the time|acquired|sold)\b|\b(?:19|20)\d\d\b")
SIZE_CAPACITY_VERBS = re.compile(
    r"(?i)\b(?:embed\w*|place[sd]?|staff\w*|suppl\w+|provid\w+|assembl\w+|add|bring|scale up|ramp|augment\w*|hire|"
    r"offer\w*|deploy\w*|allocat\w+|dedicated|your|their|clients?|customers?|partners?)\b")
SIZE_FOLLOW_GROUP = re.compile(r"(?i)^\W*(?:\w+\s+){0,3}?(?:who|that|which)\b")
_CAP_WORD = re.compile(r"\b[A-Z][a-zA-Z]+\b")
_CAP_ALLOW = {"We", "Our", "I", "Us"}


def _self_subject_re(names: set[str]) -> re.Pattern:
    return re.compile(rf"(?:(?i:\bwe\b|\bour\b)|\b(?i:{name_alternation(names)})\b)")


def size_attribution(sentence: str, m: re.Match, names: set[str]) -> tuple[bool, str]:
    """(accepted, reason). Accepted only for a current, scalar count the company states about itself."""
    before = sentence[: m.start()]
    num_end = m.end(1)
    if SIZE_QUANT_BEFORE.search(sentence[: m.start(1)]):
        return False, "range or bounded quantity (not a scalar headcount)"
    if sentence[num_end:num_end + 1] == "+":
        return False, "open-ended 'N+' quantity"
    if SIZE_PAST.search(sentence):
        return False, "historical or other-time wording"
    if SIZE_FOLLOW_GROUP.search(sentence[num_end:]) and not re.match(r"\s*(?:employees|team members)", sentence[num_end:], re.I):
        return False, "number describes a group ('who/that ...'), not the company's headcount"
    subj = list(_self_subject_re(names).finditer(before))
    if not subj:
        return False, "no first-person or company-name subject before the number"
    seg = before[subj[-1].end():]
    if SIZE_CAPACITY_VERBS.search(seg):
        return False, "describes capacity offered/embedded for clients"
    self_tokens = {t for n in names for t in n.split()}
    foreign = [w for w in _CAP_WORD.findall(seg) if w not in _CAP_ALLOW and w.lower() not in self_tokens]
    if foreign:
        return False, f"another entity appears between subject and number: {foreign[0]}"
    return True, "self-referential"


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


def _state_value(raw: str) -> str:
    return STATE_NAMES.get(raw.lower(), raw.upper())


THIRD_PARTY_FLAG = "third_party"


def _ctx_of(hit) -> frozenset:
    """Context flags of the block a _first() hit came from."""
    snap, text, _m = hit
    for _i, t, ctx, _s in snap.page.iter_blocks():
        if t == text:
            return ctx
    return frozenset()


def snap_kind(snap: PageSnapshot) -> str:
    return page_kind(snap.url, snap.is_homepage)


def _blocks(snap: PageSnapshot) -> Iterator[tuple[str, frozenset, str]]:
    """(text, context flags, page kind) for every block, plus title/meta (no structural context)."""
    kind = snap_kind(snap)
    for _i, text, ctx, _sec in snap.page.iter_blocks():
        yield text, ctx, kind
    for t in (snap.page.title, snap.page.meta_description):
        if t:
            yield t, frozenset(), kind


def _first(snaps: Iterable[PageSnapshot], patterns, *, need_assertive: bool = True):
    """First (snap, text, match) over pages in order (homepage first). Optionally only company-voice blocks."""
    for snap in snaps:
        for text, ctx, kind in _blocks(snap):
            if need_assertive and not assertive(ctx, kind):
                continue
            for pat in patterns:
                m = pat.search(text)
                if m:
                    return snap, text, m
    return None


def _ev(company_key, claim_type, value, snap: PageSnapshot, text: str, m: re.Match, notes="",
        level: str = SOURCE_SUPPORTED, span: tuple[int, int] | None = None) -> Evidence:
    start, end = span if span else (m.start(), m.end())
    excerpt = _window(text, start, end)
    return Evidence(
        id=make_id(company_key, claim_type, value, snap.url, excerpt), company_key=company_key,
        claim_type=claim_type, value=value, level=level, source_type="first_party_page",
        source_url=snap.url, fetched_at=snap.fetched_at, excerpt=excerpt, excerpt_parts=[excerpt],
        notes=notes)


def extract_evidence(company_key: str, snaps: list[PageSnapshot], names: set[str] | None = None) -> list[Evidence]:
    """Extract context-aware evidence. ``names`` = the company's own names (see context.derive_self_names).

    Every item is a verbatim excerpt. A verbatim excerpt only proves the page SAYS something; whether it
    is a claim about THIS company is decided here by context, and unclear cases stay ``unknown``.
    """
    names = set(names or ())
    out: list[Evidence] = []
    seen: set[tuple] = set()

    def add(ev: Evidence) -> None:
        key = (ev.claim_type, ev.value)
        if key not in seen:
            seen.add(key)
            out.append(ev)

    dummy = re.compile(r"")  # span-based items pass an explicit span

    # ---- services: OFFERING statements only; other tech mentions are kept as unknown, never scored
    offered: set[str] = set()
    for snap in snaps:
        kind = snap_kind(snap)
        for text, ctx, _k in _blocks(snap):
            if not assertive(ctx, kind) or kind == "work":
                continue
            for tag, st, en, basis in offering_matches(text, kind, names):
                if tag not in offered:
                    offered.add(tag)
                    add(_ev(company_key, f"service:{tag}", tag, snap, text, dummy.match(""), 
                            notes=f"service-offering structure ({basis}); the page says this, it is not verified",
                            span=(st, en)))
    for tag, pat in TECH_RE.items():
        if tag in offered:
            continue
        for snap in snaps:
            hit = None
            for text, ctx, kind in _blocks(snap):
                m = pat.search(text)
                if m:
                    hit = (text, m, ctx, kind)
                    break
            if hit:
                text, m, ctx, kind = hit
                why = ("third-party/blog/docs context" if not assertive(ctx, kind)
                       else "no service-offering structure (mention only)")
                add(_ev(company_key, f"tech_mention:{tag}", tag, snap, text, m,
                        notes=f"{why}; NOT evidence the company offers this service", level=UNKNOWN))
                break

    # ---- company identity cues
    alt = name_alternation(names)
    ident_a = re.compile(
        rf"(?:(?i:\bwe(?:'re|\s+are)\b)|\b(?i:{alt})\s+(?i:is|are))\s+(?i:an?|the)\s+[^.]{{0,60}}?\b{AGENCY_NOUN}")
    hit = _first(snaps, [ident_a])
    if hit:
        add(_ev(company_key, "identity:agency_statement", "self_description", *hit,
                notes="company describes itself as an agency/studio/consultancy"))
    else:
        hit = _first([x for x in snaps if x.is_homepage or snap_kind(x) == "about"], [OUR_STUDIO_RE])
        if hit:
            add(_ev(company_key, "identity:agency_statement", "our_studio", *hit,
                    notes="'our studio/agency' wording"))
        else:
            for snap in snaps:
                if not snap.is_homepage:
                    continue
                for t in (snap.page.title, snap.page.meta_description):
                    m = AGENCY_TITLE_RE.search(t or "")
                    if m:
                        add(_ev(company_key, "identity:agency_statement", "title_or_meta", snap, t, m,
                                notes="agency/studio wording in homepage title or meta description"))
                        break
    cs_cues = {"serves_clients": CS_FOR_RE, "project_cta": CS_CTA_RE, "client_work": CS_CLIENTS_RE}
    for cue, pat in cs_cues.items():
        cue_snaps = snaps if cue == "client_work" else [x for x in snaps if snap_kind(x) != "work"]
        hit = _first(cue_snaps, [pat])
        if hit:
            note = "client-facing service language; NOT evidence of purchase intent" if cue == "client_work" else \
                   "client-facing service language (supports, does not prove, agency identity)"
            add(_ev(company_key, f"identity:client_service", cue, *hit, notes=note))
    for cue, pat in VENDOR_CUES.items():
        hit = _first(snaps, [pat], need_assertive=False)
        if hit and THIRD_PARTY_FLAG not in _ctx_of(hit):
            add(_ev(company_key, "identity:vendor_cue", cue, *hit,
                    notes="product-vendor language (trial/demo/pricing/login/platform)"))
    for cue, pat in ENTERPRISE_CUES.items():
        hit = _first(snaps, [pat])
        if hit:
            add(_ev(company_key, "identity:enterprise_cue", cue, *hit, notes="large/listed-company language"))

    # ---- location (company voice only; footer addresses allowed)
    hit = _first(snaps, [US_ADDRESS_RE])
    if hit:
        snap, text, m = hit
        add(_ev(company_key, "location:us", _state_value(m.group(1)), snap, text, m,
                "US street/city-state-ZIP pattern on first-party page"))
    else:
        hit = _first(snaps, [US_BASED_RE])
        if hit:
            snap, text, m = hit
            add(_ev(company_key, "location:us", _state_value(m.group(1) or m.group(2)), snap, text, m,
                    "'based/located in City, State' statement"))
        else:
            for snap in snaps:
                found = False
                for text, ctx, kind in _blocks(snap):
                    if not assertive(ctx, kind):
                        continue
                    m = US_COUNTRY_RE.search(text)
                    if m and US_COUNTRY_CONTEXT_RE.search(text):
                        add(_ev(company_key, "location:us", "US", snap, text, m,
                                "country mention with location wording"))
                        found = True
                        break
                if found:
                    break
    hit = _first(snaps, [NON_US_RE, UK_POSTCODE_RE, CA_POSTAL_RE])
    if hit:
        snap, text, m = hit
        value = m.group(1) if m.groups() else m.group(0)
        add(_ev(company_key, "location:non_us", value, snap, text, m,
                "non-US place/postcode statement (detection is partial)"))

    # ---- employee count: self-referential scalar statements only; otherwise unknown
    accepted: dict[int, tuple[PageSnapshot, str, re.Match, tuple[int, int]]] = {}
    rejected: list[tuple[PageSnapshot, str, re.Match, tuple[int, int], str]] = []
    for snap in snaps:
        kind = snap_kind(snap)
        for text, ctx, _k in _blocks(snap):
            speaking = assertive(ctx, kind)
            for sent in sentences(text):
                base = text.find(sent)
                for pat in SIZE_PATTERNS:
                    for m in pat.finditer(sent):
                        n = int(m.group(1).replace(",", ""))
                        if not 1 <= n <= 100_000:
                            continue
                        span = (base + m.start(), base + m.end())
                        if not speaking:
                            rejected.append((snap, text, m, span, "third-party/blog/docs context"))
                            continue
                        ok, why = size_attribution(sent, m, names)
                        if ok:
                            accepted.setdefault(n, (snap, text, m, span))
                        else:
                            rejected.append((snap, text, m, span, why))
    if len(accepted) == 1:
        n, (snap, text, m, span) = next(iter(accepted.items()))
        add(_ev(company_key, "size:employees", n, snap, text, m, span=span,
                notes="self-referential count wording on first-party page; page statements can be stale"))
    elif len(accepted) > 1:
        n, (snap, text, m, span) = next(iter(accepted.items()))
        add(_ev(company_key, "size:employees", None, snap, text, m, span=span, level=UNKNOWN,
                notes=f"conflicting self-referential counts found: {sorted(accepted)}; treated as unknown"))
    elif rejected:
        snap, text, m, span, why = rejected[0]
        add(_ev(company_key, "size:employees", None, snap, text, m, span=span, level=UNKNOWN,
                notes=f"a number near headcount wording was NOT attributed to the company: {why}"))

    # ---- negatives / signals (company voice only)
    home_snaps = [x for x in snaps if x.is_homepage]
    other_snaps = [x for x in snaps if not x.is_homepage]
    hit = _first(home_snaps, [STAFFING_HARD_RE])
    if hit:
        add(_ev(company_key, "negative:staffing_recruiting", "staffing_recruiting", *hit,
                notes="self-description on homepage"))
    else:
        hit = _first(other_snaps, [STAFFING_HARD_RE])
        if hit:
            add(_ev(company_key, "negative:staffing_mention", "staffing_mention", *hit,
                    notes="staffing/recruiting wording on a secondary page; needs review"))
    for ctype, pat, val in (("negative:staff_augmentation", STAFF_AUG_RE, "staff_augmentation"),
                            ("negative:global_consultancy", GLOBAL_CONSULTANCY_RE, "global_consultancy"),
                            ("signal:hiring_info_only", HIRING_RE, "hiring")):
        hit = _first(snaps, [pat])
        if hit:
            note = "recorded for information; weight 0; hiring is NOT purchase intent" if val == "hiring" else ""
            add(_ev(company_key, ctype, val, *hit, notes=note))
    cw = next((e for e in out if e.claim_type == "identity:client_service" and e.value == "client_work"), None)
    if cw:  # client-work wording is a signal only when the company states it about its own clients
        add(Evidence(**{**cw.__dict__, "claim_type": "signal:client_work", "value": "client_work",
                        "id": make_id(company_key, "signal:client_work", "client_work", cw.source_url, cw.excerpt)}))
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
