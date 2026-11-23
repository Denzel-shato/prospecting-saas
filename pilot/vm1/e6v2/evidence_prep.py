"""Engine #6 V2 evidence preparation: team / founder / leadership / About passages.

Turns existing ``PageSnapshot`` / ``PageData`` objects into a small, deduplicated, size-bounded list of
``EvidencePassage`` records that a LATER step (AI extraction, then verification) can read. This module
extracts no people, scores nothing, calls no API and makes no network or file access.

Guarantees
* Source text is preserved. A passage is built from whole ``PageData`` blocks (already whitespace-normalised
  by the HTML parser), joined with a newline where two blocks meet. The only edit is contact redaction
  (``[email removed]`` / ``[phone removed]``). ``source_url``, ``fetched_at``, ``page_kind``, the heading
  chain and the originating block indices are kept so the text can be traced back and re-checked.
* Third-party context is KEPT, never silently dropped: a testimonial, client logo, blog byline or
  footer mention that looks like a leadership statement becomes a passage carrying its structural labels and
  ``risk_flags`` (``ctx:quote``, ``section:third_party``, ``adjacent_quote``, ``page:editorial`` ...), so a
  verifier can reject false attribution. A passage never merges text across a third-party boundary.
  A hand-built ``PageData`` with no context labels is flagged ``context_unknown``, never treated as clean.
* ``passage_id`` = hash of (canonical page URL, whitespace-normalised passage text): independent of input
  order, block indices and unrelated page content, so the same text on the same page keeps its id.
* Irrelevant content is dropped: navigation, boilerplate link labels, contact-only blocks, pages of kind
  legal / careers / pricing / docs (configurable), and text with no leadership/team/About signal.

Known limits (deliberate): JSON-LD is not read; headings are the parser's stored chain (original casing is
restored when the heading text is itself a block, otherwise the parser's lower-cased form is kept); role and
section matching is lexical, so it over-selects rather than judging who is a decision-maker. Team cards are kept
apart only where the HTML marks card boundaries (div/article/li); a flat run of <p> tags has none, so neighbouring
people may share a passage (still size-capped and labelled).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Iterable

from ..context import THIRD_PARTY_CTX, THIRD_PARTY_SECTION_RE, TEAM_SECTION_RE, looks_like_quote_neighbour, page_kind
from ..evidence import PageSnapshot
from ..htmlparse import PageData, norm_ws
from ..pageselect import canonical_key

EMAIL_PLACEHOLDER = "[email removed]"
PHONE_PLACEHOLDER = "[phone removed]"
VIEWS = ("blocks", "people")
HEADING_SEP = " > "

# ---- configuration ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PrepConfig:
    """All size limits are explicit and configurable. Counts are passages; sizes are characters."""

    max_passage_chars: int = 1200      # hard cap per passage; longer blocks are split at sentence/word boundaries
    max_passages_per_page: int = 12
    max_passages: int = 30             # overall cap
    max_total_chars: int = 20_000      # overall cap on summed passage text
    context_before: int = 1            # neighbouring blocks (same section, same third-party status) kept around a hit
    context_after: int = 1
    min_about_block_chars: int = 40    # About pages: ignore very short blocks (labels) that carry no role signal
    excluded_page_kinds: frozenset = frozenset({"legal", "careers", "pricing", "docs"})

    def __post_init__(self) -> None:
        for name in ("max_passage_chars", "max_passages_per_page", "max_passages", "max_total_chars"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer, got {value!r}")
        if self.max_passage_chars < 40:
            raise ValueError("max_passage_chars must be at least 40")
        for name in ("context_before", "context_after", "min_about_block_chars"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
        object.__setattr__(self, "excluded_page_kinds", frozenset(self.excluded_page_kinds))

    def to_dict(self) -> dict:
        return {
            "max_passage_chars": self.max_passage_chars, "max_passages_per_page": self.max_passages_per_page,
            "max_passages": self.max_passages, "max_total_chars": self.max_total_chars,
            "context_before": self.context_before, "context_after": self.context_after,
            "min_about_block_chars": self.min_about_block_chars,
            "excluded_page_kinds": sorted(self.excluded_page_kinds),
        }


# ---- output records -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidencePassage:
    passage_id: str
    source_url: str
    page_kind: str                 # home | team | about | editorial | work | other ... (from the URL path)
    fetched_at: str
    is_homepage: bool
    view: str                      # "blocks" (prose view) or "people" (card-boundary view) of PageData
    block_indices: tuple           # indices into that view's block list
    headings: tuple                # heading chain above the passage, outermost first
    text: str                      # source text; blocks joined by "\n"; contacts redacted
    context_labels: tuple          # structural labels from the parser (quote, client, editorial, footer ...)
    risk_flags: tuple              # why a verifier must check attribution (see module docstring)
    reasons: tuple                 # why it was selected (role_keyword, team_section, team_page, about_page)
    redacted_emails: int = 0
    redacted_phones: int = 0
    also_seen_at: tuple = ()       # other pages that contained identical text (deduplicated away)

    def to_dict(self) -> dict:
        return {
            "passage_id": self.passage_id, "source_url": self.source_url, "page_kind": self.page_kind,
            "fetched_at": self.fetched_at, "is_homepage": self.is_homepage, "view": self.view,
            "block_indices": list(self.block_indices), "headings": list(self.headings), "text": self.text,
            "context_labels": list(self.context_labels), "risk_flags": list(self.risk_flags),
            "reasons": list(self.reasons), "redacted_emails": self.redacted_emails,
            "redacted_phones": self.redacted_phones, "also_seen_at": list(self.also_seen_at),
        }


@dataclass(frozen=True)
class EvidencePrepResult:
    passages: tuple
    stats: dict
    config: PrepConfig

    def by_id(self) -> dict:
        return {p.passage_id: p for p in self.passages}

    def to_dict(self) -> dict:
        return {"passages": [p.to_dict() for p in self.passages], "stats": dict(self.stats),
                "config": self.config.to_dict()}


# ---- contact redaction --------------------------------------------------------------------------------------

_CONTACT_URI_RE = re.compile(r"(?i)\b(mailto|tel|sms):\S*")
_OBFUSCATED_EMAIL_RE = re.compile(
    r"(?i)\b[\w.+\-]+\s*(?:\[\s*at\s*\]|\(\s*at\s*\))\s*[\w\-]+(?:\s*(?:\[\s*dot\s*\]|\(\s*dot\s*\)|\.)\s*[\w\-]+)+")
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")
_SNAPSHOT_EMAIL_MARKER_RE = re.compile(r"\[redacted-email\]")
_PHONE_CANDIDATE_RE = re.compile(r"(?<![\w/@])\+?\(?\d[\d\s().\-]{6,}\d(?![\w])")


def redact_contact_details(text: str) -> str:
    """Replace e-mail addresses, obfuscated addresses, mailto:/tel:/sms: strings and phone numbers.

    A phone number is a digit run of 9-15 digits with only space, dot, dash and parenthesis separators,
    so year ranges ("2015-2020") and ordinary figures are left alone.
    """
    def uri(m: re.Match) -> str:
        return EMAIL_PLACEHOLDER if m.group(1).lower() == "mailto" else PHONE_PLACEHOLDER

    def phone(m: re.Match) -> str:
        digits = sum(ch.isdigit() for ch in m.group(0))
        return PHONE_PLACEHOLDER if 9 <= digits <= 15 else m.group(0)

    text = _CONTACT_URI_RE.sub(uri, text)
    text = _OBFUSCATED_EMAIL_RE.sub(EMAIL_PLACEHOLDER, text)
    text = _EMAIL_RE.sub(EMAIL_PLACEHOLDER, text)
    text = _SNAPSHOT_EMAIL_MARKER_RE.sub(EMAIL_PLACEHOLDER, text)
    return _PHONE_CANDIDATE_RE.sub(phone, text)


# ---- relevance ----------------------------------------------------------------------------------------------

_ROLE_RE = re.compile(
    r"(?i)\b(?:co-?founders?|founders?|founding (?:partner|principal|team|member|engineer|designer)|founded by|"
    r"(?:led|headed|run|started) by|(?:co-?)?owners?|chief [a-z]+(?: [a-z]+)? officer|c[etofimp]o|"
    r"managing (?:director|partner|principal)|(?:general|senior|executive) partner|president|vice president|"
    r"vp(?: of)?|principals?|directors?|head of [a-z]+|(?:executive|leadership|management) team|leadership|"
    r"executives?|meet (?:the|our) (?:team|founders?|people|leadership)|our (?:team|people|founders?))\b")
_BOILERPLATE_RE = re.compile(
    r"(?i)(?:read more|learn more|view (?:profile|bio)|see more|find out more|contact(?: us)?|get in touch|"
    r"follow us|linkedin|twitter|instagram|facebook|github|dribbble|behance|youtube|x|subscribe|"
    r"join (?:our|the) team|we(?:'|’)re hiring)[\s.:!→»>\-]*")
_GENERIC_HEADING_RE = re.compile(
    r"(?i)(?:meet |about |who we are|our |the )*(?:team|people|leadership(?: team)?|founders?|"
    r"management(?: team)?|executives?(?: team)?|story|company|studio|us)[\s.:!]*")
_CONTACT_LABEL_RE = re.compile(
    r"(?i)(?:e-?mail|phone|tel(?:ephone)?|mobile|cell|call|contact|fax|whatsapp)?[\s:|,/\-–—•·()]*")

PAGE_PRIORITY = {"team": 0, "about": 1, "home": 2, "editorial": 4, "work": 4}
DEFAULT_PAGE_PRIORITY = 3
REASON_RANK = {"role_keyword": 0, "team_section": 1, "team_page": 2, "about_page": 2}
_THIRD_PARTY_PAGE_KINDS = frozenset({"editorial", "work"})


def _is_empty_or_contact_only(clean: str) -> bool:
    rest = clean.replace(EMAIL_PLACEHOLDER, "").replace(PHONE_PLACEHOLDER, "")
    return not re.search(r"[^\W\d_]", rest) or bool(_CONTACT_LABEL_RE.fullmatch(rest.strip()))


def _reasons(text: str, heading: bool, ctx: frozenset, section: str, kind: str, cfg: PrepConfig,
             view: str) -> tuple:
    """Why a block is a hit. Section/page-kind hits only apply in the card-boundary ("people") view: in the prose
    view adjacent cards have no boundaries, so only explicit role/About statements are hits there."""
    found = []
    if _ROLE_RE.search(text):
        found.append("role_keyword")
    if ctx & {"footer", "aside"}:
        return tuple(found)                     # peripheral regions only count on an explicit role statement
    if not heading:
        if view == "people":
            if section and TEAM_SECTION_RE.search(section):
                found.append("team_section")
            if kind == "team":
                found.append("team_page")
        if kind == "about" and len(text) >= cfg.min_about_block_chars:
            found.append("about_page")
    return tuple(found)


# ---- splitting long blocks ----------------------------------------------------------------------------------


def _split_words(text: str, limit: int) -> list:
    out, cur = [], ""
    for word in text.split(" "):
        while len(word) > limit:
            if cur:
                out.append(cur)
                cur = ""
            out.append(word[:limit])
            word = word[limit:]
        if not word:
            continue
        if cur and len(cur) + 1 + len(word) <= limit:
            cur += " " + word
        else:
            if cur:
                out.append(cur)
            cur = word
    if cur:
        out.append(cur)
    return out


def _chunk(text: str, limit: int) -> list:
    """Split into pieces of at most ``limit`` chars, preferring sentence then word boundaries. Nothing is lost."""
    if len(text) <= limit:
        return [text]
    out, cur = [], ""
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        for piece in ([sentence] if len(sentence) <= limit else _split_words(sentence, limit)):
            if cur and len(cur) + 1 + len(piece) <= limit:
                cur += " " + piece
            else:
                if cur:
                    out.append(cur)
                cur = piece
    if cur:
        out.append(cur)
    return out


# ---- per-page candidate construction --------------------------------------------------------------------------


@dataclass
class _Item:
    text: str
    orig: int
    ctx: frozenset
    section: str
    heading: bool
    reasons: tuple


@dataclass
class _Cand:
    snap_index: int
    view_index: int
    source_url: str
    ckey: str
    kind: str
    fetched_at: str
    is_homepage: bool
    view: str
    block_indices: tuple
    headings: tuple
    text: str
    labels: tuple
    flags: tuple
    reasons: tuple
    also_seen_at: list = field(default_factory=list)

    @property
    def norm(self) -> str:
        return " ".join(self.text.split()).casefold()

    @property
    def lines(self) -> int:
        return self.text.count("\n") + 1

    @property
    def third_party_risk(self) -> bool:
        return any(f.startswith(("ctx:quote", "ctx:client", "ctx:editorial", "section:", "adjacent_", "page:"))
                   for f in self.flags)

    def sort_key(self) -> tuple:
        priority = PAGE_PRIORITY.get(self.kind, DEFAULT_PAGE_PRIORITY)
        rank = min((REASON_RANK[r] for r in self.reasons), default=9)
        return (priority, 1 if self.third_party_risk else 0, rank, self.snap_index, self.view_index,
                self.block_indices[0] if self.block_indices else 0)


def _heading_lookup(page: PageData) -> dict:
    """lower-cased stored heading -> original-case text, when the heading is itself one of the page's blocks."""
    out: dict = {}
    for block in page.blocks:
        head = norm_ws(block)[:80]
        out.setdefault(head.lower(), head)
    return out


def _headings(section: str, lookup: dict) -> tuple:
    return tuple(lookup.get(part, part) for part in section.split(HEADING_SEP) if part) if section else ()


def _build_items(texts: list, ctxs: list, sections: list, kind: str, cfg: PrepConfig, view: str) -> tuple:
    known = bool(texts) and len(ctxs) == len(texts) and len(sections) == len(texts)
    items: list = []
    for i, raw in enumerate(texts):
        text = (raw or "").strip()
        ctx = ctxs[i] if known else frozenset()
        section = sections[i] if known else ""
        if not text or "nav" in ctx or _BOILERPLATE_RE.fullmatch(text):
            items.append(None)                  # also acts as a boundary (people view uses '' between cards)
            continue
        clean = redact_contact_details(text)
        if _is_empty_or_contact_only(clean):
            items.append(None)
            continue
        heading = bool(section) and norm_ws(text)[:80].lower() == section.rsplit(HEADING_SEP, 1)[-1]
        for piece in _chunk(clean, cfg.max_passage_chars):
            items.append(_Item(piece, i, ctx, section, heading, _reasons(piece, heading, ctx, section, kind, cfg, view)))
    return items, known


def _third_party(item: _Item) -> bool:
    return bool(item.ctx & THIRD_PARTY_CTX)


def _can_join(neighbour, anchor: _Item) -> bool:
    return (neighbour is not None and neighbour.section == anchor.section
            and _third_party(neighbour) == _third_party(anchor))


def _claimed_windows(items: list, cfg: PrepConfig) -> list:
    """Final (lo, hi, anchors) passages for one view, already fitted to ``max_passage_chars``."""
    wins = _role_windows(items, cfg)
    fitted = [(a, b, anchors) for lo, hi, anchors in wins
              for a, b in _pieces(items, lo, hi, anchors, cfg.max_passage_chars)]
    covered = {k for a, b, _ in fitted for k in range(a, b + 1)}
    i = 0
    while i < len(items):
        if items[i] is None or i in covered:
            i += 1
            continue
        j = i
        while j + 1 < len(items) and j + 1 not in covered and _can_join(items[j + 1], items[i]):
            j += 1
        weak = {k for k in range(i, j + 1) if items[k].reasons}
        if weak:
            fitted.extend((a, b, weak) for a, b in _pieces(items, i, j, weak, cfg.max_passage_chars))
        i = j + 1
    # A passage that is only a generic section label ("Meet the team") adds nothing: it survives as ``headings``.
    fitted = [w for w in fitted if not all(items[k].heading and _GENERIC_HEADING_RE.fullmatch(items[k].text)
                                           for k in range(w[0], w[1] + 1))]
    return sorted(fitted, key=lambda w: (w[0], w[1]))


def _role_windows(items: list, cfg: PrepConfig) -> list:
    """Windows around explicit role statements. Context is never pulled across another role statement: a block
    between two of them belongs to the nearer one (a tie goes to the later one: names precede titles). Runs of
    blocks left uncovered that carry a weaker hit (team section/page, About page) become passages of their own
    (see ``_claimed_windows``); in the people view such runs are single cards, because card boundaries are gaps."""
    anchors = [i for i, it in enumerate(items) if it is not None and "role_keyword" in it.reasons]
    aset = set(anchors)
    owner: dict = {a: (0, -a) for a in anchors}
    for a in anchors:
        for step, limit in ((-1, cfg.context_before), (1, cfg.context_after)):
            for dist in range(1, limit + 1):
                j = a + step * dist
                if not 0 <= j < len(items) or j in aset or not _can_join(items[j], items[a]):
                    break
                owner[j] = min(owner.get(j, (dist, -a)), (dist, -a))
    wins = []
    for a in anchors:
        lo = hi = a
        while owner.get(lo - 1, (0, 1))[1] == -a:
            lo -= 1
        while owner.get(hi + 1, (0, 1))[1] == -a:
            hi += 1
        wins.append([lo, hi, {a}])
    return wins


def _join(parts: list) -> str:
    out = ""
    for k, item in enumerate(parts):
        if k:
            out += " " if item.orig == parts[k - 1].orig else "\n"   # chunks of one block re-join with a space
        out += item.text
    return out


def _pieces(items: list, lo: int, hi: int, anchors: set, limit: int) -> list:
    """Fit a window into ``limit`` chars: trim context edges first, then split at item boundaries."""
    while hi > lo and len(_join(items[lo:hi + 1])) > limit and hi not in anchors:
        hi -= 1
    while hi > lo and len(_join(items[lo:hi + 1])) > limit and lo not in anchors:
        lo += 1
    if len(_join(items[lo:hi + 1])) <= limit:
        return [(lo, hi)]
    out, start = [], lo
    for k in range(lo, hi + 1):
        if k > start and len(_join(items[start:k + 1])) > limit:
            out.append((start, k - 1))
            start = k
    out.append((start, hi))
    return [(a, b) for a, b in out if any(a <= x <= b for x in anchors)]


def _risk_flags(items: list, lo: int, hi: int, texts: list, ctxs: list, known: bool, kind: str) -> tuple:
    flags: set = set()
    section = items[lo].section
    for k in range(lo, hi + 1):
        for label in items[k].ctx:
            if label in THIRD_PARTY_CTX or label in ("footer", "aside"):
                flags.add(f"ctx:{label}")
    if THIRD_PARTY_SECTION_RE.search(section):
        flags.add("section:third_party")
    if kind in _THIRD_PARTY_PAGE_KINDS:
        flags.add(f"page:{kind}")
    if not known:
        flags.add("context_unknown")
    else:
        view = SimpleNamespace(blocks=texts, ctx_at=lambda j: ctxs[j] if 0 <= j < len(ctxs) else frozenset())
        if any(looks_like_quote_neighbour(view, items[k].orig) for k in range(lo, hi + 1)):
            flags.add("adjacent_quote")
    return tuple(sorted(flags))


def _page_candidates(snap: PageSnapshot, snap_index: int, kind: str, cfg: PrepConfig) -> list:
    page = snap.page
    lookup = _heading_lookup(page)
    cands: list = []
    for view_index, view in enumerate(VIEWS):
        texts, ctxs, sections = ((page.blocks, page.block_ctx, page.block_section) if view == "blocks"
                                 else (page.people_blocks, page.people_ctx, page.people_sections))
        items, known = _build_items(list(texts), list(ctxs), list(sections), kind, cfg, view)
        for a, b, anchors in _claimed_windows(items, cfg):
            parts = items[a:b + 1]
            reasons = sorted({r for k in range(a, b + 1) if k in anchors for r in items[k].reasons},
                             key=lambda r: (REASON_RANK[r], r))
            labels = sorted({label for it in parts for label in it.ctx})
            cands.append(_Cand(
                snap_index=snap_index, view_index=view_index, source_url=snap.url, ckey=canonical_key(snap.url),
                kind=kind, fetched_at=snap.fetched_at, is_homepage=snap.is_homepage, view=view,
                block_indices=tuple(sorted({it.orig for it in parts})),
                headings=_headings(parts[0].section, lookup), text=_join(parts), labels=tuple(labels),
                flags=_risk_flags(items, a, b, list(texts), list(ctxs), known, kind), reasons=tuple(reasons)))
    return cands


# ---- deduplication and limits -------------------------------------------------------------------------------


def _note_seen(keeper: _Cand, other: _Cand) -> None:
    if other.source_url != keeper.source_url and other.source_url not in keeper.also_seen_at:
        keeper.also_seen_at.append(other.source_url)
    for url in other.also_seen_at:
        if url != keeper.source_url and url not in keeper.also_seen_at:
            keeper.also_seen_at.append(url)


def _dedupe(ordered: list) -> tuple:
    """Exact (whitespace/case-insensitive) duplicates anywhere; contained text only within the same page.

    On the same page the version with more block structure (card boundaries) wins an equality; a contained
    passage is dropped unless it preserves more structure than its container.
    """
    kept: list = []
    removed = 0
    for cand in ordered:
        for idx, k in enumerate(kept):
            same_page = k.ckey == cand.ckey
            if k.norm == cand.norm:
                if same_page and cand.lines > k.lines:
                    _note_seen(cand, k)
                    kept[idx] = cand
                else:
                    _note_seen(k, cand)
                break
            if same_page and cand.norm in k.norm and cand.lines <= k.lines:
                break
            if same_page and k.norm in cand.norm and k.lines <= cand.lines:
                _note_seen(cand, k)
                kept[idx] = cand
                break
        else:
            kept.append(cand)
            continue
        removed += 1
    return kept, removed


def _passage_id(source_url: str, text: str) -> str:
    raw = f"{canonical_key(source_url)}\x1f{' '.join(text.split())}"
    return "ps_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def prepare_evidence(snapshots: Iterable[PageSnapshot], config: PrepConfig | None = None) -> EvidencePrepResult:
    """Select, redact, label, deduplicate and size-limit leadership/team/About passages. Pure and deterministic."""
    cfg = config or PrepConfig()
    cands: list = []
    skipped: dict = {}
    pages = 0
    for snap_index, snap in enumerate(snapshots):
        pages += 1
        kind = page_kind(snap.url, snap.is_homepage)
        if kind in cfg.excluded_page_kinds:
            skipped[kind] = skipped.get(kind, 0) + 1
            continue
        cands.extend(_page_candidates(snap, snap_index, kind, cfg))
    total_candidates = len(cands)
    deduped, duplicates = _dedupe(sorted(cands, key=_Cand.sort_key))

    selected: list = []
    per_page: dict = {}
    chars = 0
    dropped = {"per_page": 0, "total_passages": 0, "total_chars": 0}
    for cand in sorted(deduped, key=_Cand.sort_key):
        if len(selected) >= cfg.max_passages:
            dropped["total_passages"] += 1
        elif per_page.get(cand.ckey, 0) >= cfg.max_passages_per_page:
            dropped["per_page"] += 1
        elif chars + len(cand.text) > cfg.max_total_chars:
            dropped["total_chars"] += 1
        else:
            selected.append(cand)
            per_page[cand.ckey] = per_page.get(cand.ckey, 0) + 1
            chars += len(cand.text)
    selected.sort(key=lambda c: (c.snap_index, c.block_indices[0] if c.block_indices else 0, c.view_index))

    passages = tuple(EvidencePassage(
        passage_id=_passage_id(c.source_url, c.text), source_url=c.source_url, page_kind=c.kind,
        fetched_at=c.fetched_at, is_homepage=c.is_homepage, view=c.view, block_indices=c.block_indices,
        headings=c.headings, text=c.text, context_labels=c.labels, risk_flags=c.flags, reasons=c.reasons,
        redacted_emails=c.text.count(EMAIL_PLACEHOLDER), redacted_phones=c.text.count(PHONE_PLACEHOLDER),
        also_seen_at=tuple(c.also_seen_at)) for c in selected)
    stats = {
        "pages_seen": pages, "pages_skipped_by_kind": dict(sorted(skipped.items())),
        "candidates": total_candidates, "duplicates_removed": duplicates,
        "dropped_by_limit": dropped, "passages": len(passages),
        "total_chars": sum(len(p.text) for p in passages),
        "redacted_emails": sum(p.redacted_emails for p in passages),
        "redacted_phones": sum(p.redacted_phones for p in passages),
        "flagged_third_party": sum(1 for p in passages if any(
            f.startswith(("ctx:quote", "ctx:client", "ctx:editorial", "section:", "adjacent_", "page:"))
            for f in p.risk_flags)),
    }
    return EvidencePrepResult(passages=passages, stats=stats, config=cfg)
