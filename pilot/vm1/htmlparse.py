"""Minimal HTML -> structured text. Visible text blocks, links (http/https only), JSON-LD.

Deliberately collects NO mailto:/tel: links: the pilot never harvests contact addresses.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Iterator
from urllib.parse import urldefrag, urljoin, urlsplit

BLOCK_TAGS = {
    "p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "section", "article",
    "header", "footer", "nav", "main", "aside", "tr", "td", "th", "table", "br", "blockquote",
    "address", "figure", "figcaption", "dd", "dt", "dl", "form", "button", "label", "body",
}
SKIP_TAGS = {"style", "noscript", "svg", "template"}
MAX_BLOCK = 2000

# Structural context flags. A block carrying THIRD_PARTY/BLOG/DOCS is not the company speaking
# about itself (testimonial, client logo, partner, article, documentation).
THIRD_PARTY, BLOG, DOCS, CHROME = "third_party", "blog", "docs", "chrome"
VOID_TAGS = {"br", "img", "hr", "input", "meta", "link", "area", "base", "col", "embed", "source",
             "track", "wbr", "param"}
_CLASS_THIRD = re.compile(
    r"testimonial|review|quote|endorse|customer-?stor|client-?logo|logo-?(?:grid|wall|cloud|strip)|"
    r"trusted-?by|case-?stud|portfolio-?item|partner|sponsor|press-?mention|featured-?in", re.I)
_CLASS_BLOG = re.compile(r"(?:^|[\s_-])(?:blog|post|article|news|press|changelog|entry)(?:$|[\s_-])", re.I)
_CLASS_DOCS = re.compile(r"(?:^|[\s_-])(?:docs?|documentation|api-?reference|markdown-body)(?:$|[\s_-])", re.I)
_HEAD_THIRD = re.compile(
    r"testimonial|what (?:our )?(?:clients?|customers?|partners?|users?) (?:say|think|are saying)|"
    r"\b(?:our )?(?:clients?|customers?|partners?)\b|trusted by|featured (?:in|on)|case stud|"
    r"\breviews?\b|\bpress\b|as seen|\badvisors?\b|\binvestors?\b|backed by|\bsponsors?\b|loved by",
    re.I)
_HEAD_BLOG = re.compile(r"\bblog\b|latest (?:posts|news|articles)|\binsights\b|\bresources\b|\bnews\b|from the blog", re.I)


def tag_flags(tag: str, attrs: dict) -> frozenset:
    flags = set()
    if tag in ("blockquote", "q", "cite"):
        flags.add(THIRD_PARTY)
    if tag in ("nav", "footer", "aside"):
        flags.add(CHROME)
    if tag == "article":
        flags.add(BLOG)
    ident = f"{attrs.get('class', '')} {attrs.get('id', '')}"
    if ident.strip():
        if _CLASS_THIRD.search(ident):
            flags.add(THIRD_PARTY)
        if _CLASS_BLOG.search(ident):
            flags.add(BLOG)
        if _CLASS_DOCS.search(ident):
            flags.add(DOCS)
    return frozenset(flags)


def heading_flags(text: str) -> frozenset:
    flags = set()
    if _HEAD_THIRD.search(text):
        flags.add(THIRD_PARTY)
    if _HEAD_BLOG.search(text):
        flags.add(BLOG)
    return frozenset(flags)
MAX_BLOCKS = 5000
MAX_LINKS = 400
_WS = re.compile(r"\s+")


def norm_ws(s: str) -> str:
    return _WS.sub(" ", s).strip()


@dataclass
class PageData:
    url: str
    title: str = ""
    meta_description: str = ""
    site_name: str = ""
    blocks: list[str] = field(default_factory=list)
    links: list[tuple[str, str]] = field(default_factory=list)
    jsonld_raw: list[str] = field(default_factory=list)
    # Parallel to ``blocks``: structural context flags and the nearest preceding heading text.
    block_ctx: list[frozenset] = field(default_factory=list)
    block_section: list[str] = field(default_factory=list)

    def ctx(self, i: int) -> frozenset:
        return self.block_ctx[i] if i < len(self.block_ctx) else frozenset()

    def section(self, i: int) -> str:
        return self.block_section[i] if i < len(self.block_section) else ""

    def iter_blocks(self) -> Iterator[tuple[int, str, frozenset, str]]:
        for i, b in enumerate(self.blocks):
            yield i, b, self.ctx(i), self.section(i)

    def verifiable_texts(self) -> list[str]:
        """Every string an excerpt may legitimately be copied from."""
        extra = [t for t in (self.title, self.meta_description, self.site_name) if t]
        return [*self.blocks, *extra, *self.jsonld_raw]

    def jsonld_nodes(self) -> Iterator[dict]:
        for raw in self.jsonld_raw:
            try:
                data = json.loads(raw)
            except ValueError:
                continue
            yield from _walk(data)


def _walk(node: Any) -> Iterator[dict]:
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v)


class _Extractor(HTMLParser):
    def __init__(self, base_url: str):
        super().__init__(convert_charrefs=True)
        self.base = base_url
        self.blocks: list[str] = []
        self.block_ctx: list[frozenset] = []
        self.block_section: list[str] = []
        self.stack: list[tuple[str, frozenset]] = []
        self.buf_flags: set = set()
        self.section_flags: frozenset = frozenset()
        self.section_text = ""
        self.buf: list[str] = []
        self.skip = 0
        self.in_title = False
        self.title_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.links: list[tuple[str, str]] = []
        self.a_href: str | None = None
        self.a_text: list[str] = []
        self.jsonld_raw: list[str] = []
        self.in_jsonld = False
        self.jsonld_buf: list[str] = []
        self.in_other_script = False

    def _flush(self) -> None:
        text = norm_ws("".join(self.buf))
        self.buf = []
        flags = frozenset(self.buf_flags) | self.section_flags
        self.buf_flags = set()
        if text and len(self.blocks) < MAX_BLOCKS:
            self.blocks.append(text[:MAX_BLOCK])
            self.block_ctx.append(flags)
            self.block_section.append(self.section_text)

    def _stack_flags(self) -> frozenset:
        out: set = set()
        for _, f in self.stack:
            out |= f
        return frozenset(out)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "script":
            kind = a.get("type", "").lower().split(";")[0].strip()
            if kind == "application/ld+json":
                self.in_jsonld = True
                self.jsonld_buf = []
            else:
                self.in_other_script = True
            return
        if tag in SKIP_TAGS:
            self.skip += 1
            return
        if tag == "title":
            self.in_title = True
            return
        if tag == "meta":
            key = (a.get("name") or a.get("property") or "").lower()
            if key in ("description", "og:site_name") and a.get("content"):
                self.meta[key] = norm_ws(a["content"])
            return
        if tag == "a":
            href = a.get("href", "").strip()
            self.a_href = href or None
            self.a_text = []
        if tag in BLOCK_TAGS:
            self._flush()
        if tag not in VOID_TAGS:
            self.stack.append((tag, tag_flags(tag, a)))

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            if self.in_jsonld:
                raw = "".join(self.jsonld_buf).strip()
                if raw:
                    self.jsonld_raw.append(raw[:200_000])
                self.in_jsonld = False
            self.in_other_script = False
            return
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if tag == "title":
            self.in_title = False
            return
        if tag == "a" and self.a_href is not None:
            href = self.a_href
            self.a_href = None
            low = href.lower()
            if not low.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
                absolute, _ = urldefrag(urljoin(self.base, href))
                if urlsplit(absolute).scheme in ("http", "https") and len(self.links) < MAX_LINKS:
                    self.links.append((absolute, norm_ws("".join(self.a_text))))
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            head = norm_ws("".join(self.buf))
            self.section_flags = heading_flags(head)
            self.section_text = head[:120]
        if tag in BLOCK_TAGS:
            self._flush()
        for i in range(len(self.stack) - 1, -1, -1):  # pop to the matching open tag, if any
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data: str) -> None:
        if self.in_jsonld:
            self.jsonld_buf.append(data)
            return
        if self.in_other_script or self.skip:
            return
        if self.in_title:
            self.title_parts.append(data)
            return
        self.buf.append(data)
        if data.strip():
            self.buf_flags |= self._stack_flags()
        if self.a_href is not None:
            self.a_text.append(data)


def parse_html(html: str, url: str) -> PageData:
    ex = _Extractor(url)
    try:
        ex.feed(html)
        ex.close()
    except Exception:  # malformed markup must never crash a run
        pass
    ex._flush()
    return PageData(
        url=url,
        title=norm_ws("".join(ex.title_parts))[:300],
        meta_description=ex.meta.get("description", "")[:500],
        site_name=ex.meta.get("og:site_name", "")[:200],
        blocks=ex.blocks,
        links=ex.links,
        jsonld_raw=ex.jsonld_raw,
        block_ctx=ex.block_ctx,
        block_section=ex.block_section,
    )
