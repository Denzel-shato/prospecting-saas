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
VOID_TAGS = {"br", "img", "meta", "link", "input", "hr", "area", "base", "col", "embed", "source",
             "track", "wbr"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
# Structural/semantic context labels attached to every text block (used to reject testimonials,
# client logos, blog/author bylines, navigation, etc. as first-party company claims).
TAG_CTX = {"blockquote": "quote", "nav": "nav", "footer": "footer", "aside": "aside", "article": "editorial"}
ATTR_CTX_TOKENS = {
    "testimonial": "quote", "testimonials": "quote", "review": "quote", "reviews": "quote",
    "quote": "quote", "quotes": "quote", "blockquote": "quote",
    "client": "client", "clients": "client", "customer": "client", "customers": "client",
    "logo": "client", "logos": "client", "partner": "client", "partners": "client",
    "sponsor": "client", "sponsors": "client", "brand": "client", "brands": "client",
    "blog": "editorial", "post": "editorial", "posts": "editorial", "news": "editorial",
    "press": "editorial", "author": "editorial", "byline": "editorial", "podcast": "editorial",
    "speaker": "editorial", "speakers": "editorial", "nav": "nav", "navbar": "nav", "menu": "nav",
    "footer": "footer",
}
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
MAX_BLOCK = 2000
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
    # Parallel to ``blocks``: structural context labels and the heading chain above each block.
    # Empty lists (e.g. a hand-built PageData) mean "context unknown", never "context is clean".
    block_ctx: list[frozenset] = field(default_factory=list)
    block_section: list[str] = field(default_factory=list)
    people_blocks: list[str] = field(default_factory=list)
    people_ctx: list[frozenset] = field(default_factory=list)
    people_sections: list[str] = field(default_factory=list)

    def ctx_at(self, i: int) -> frozenset:
        return self.block_ctx[i] if 0 <= i < len(self.block_ctx) else frozenset()

    def section_at(self, i: int) -> str:
        return self.block_section[i] if 0 <= i < len(self.block_section) else ""

    def verifiable_texts(self) -> list[str]:
        """Every string an excerpt may legitimately be copied from."""
        extra = [t for t in (self.title, self.meta_description, self.site_name) if t]
        return [*self.blocks, *self.people_blocks, *extra, *self.jsonld_raw]

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
        self.stack: list[tuple[str, frozenset]] = []
        self.block_ctx: list[frozenset] = []
        self.block_section: list[str] = []
        self.headings: dict[int, str] = {}

    def _flush(self) -> None:
        text = norm_ws("".join(self.buf))
        self.buf = []
        if text and len(self.blocks) < MAX_BLOCKS:
            self.blocks.append(text[:MAX_BLOCK])
            labels: set[str] = set()
            for _, lab in self.stack:
                labels |= lab
            self.block_ctx.append(frozenset(labels))
            chain = " > ".join(self.headings[k] for k in sorted(self.headings))
            self.block_section.append(chain.lower()[:300])

    @staticmethod
    def _labels(tag: str, a: dict[str, str]) -> frozenset:
        labels = set()
        if tag in TAG_CTX:
            labels.add(TAG_CTX[tag])
        for attr in ("class", "id", "itemprop", "itemtype", "data-testid", "role"):
            for tok in _TOKEN_SPLIT.split(a.get(attr, "").lower()):
                if tok in ATTR_CTX_TOKENS:
                    labels.add(ATTR_CTX_TOKENS[tok])
        return frozenset(labels)

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
            self.stack.append((tag, self._labels(tag, a)))

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
        if tag in HEADING_TAGS:
            level = int(tag[1])
            text = norm_ws("".join(self.buf))
            for k in [k for k in self.headings if k >= level]:
                del self.headings[k]
            if text:
                self.headings[level] = text[:80]
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
    # A separate view preserves inline card boundaries without changing service evidence.
    people = _PeopleExtractor(url)
    try:
        people.feed(html)
        people.close()
    except Exception:
        pass
    people._flush()
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
        people_blocks=people.blocks,
        people_ctx=people.block_ctx,
        people_sections=people.block_section,
    )


class _PeopleExtractor(_Extractor):
    """Split inline card fields; article is allowed only with explicit Person markup.

    Editorial classes and testimonial/client ancestors retain their vetoes.
    The ordinary evidence parser remains unchanged.
    """
    @staticmethod
    def _labels(tag, attrs):
        labels = set(_Extractor._labels(tag, attrs))
        if tag == 'article' and attrs.get('itemtype', '').rstrip('/').endswith('/Person'):
            labels.discard('editorial')
            for token in _TOKEN_SPLIT.split(attrs.get('class', '').lower()):
                if ATTR_CTX_TOKENS.get(token) == 'editorial':
                    labels.add('editorial')
        return frozenset(labels)

    def handle_starttag(self, tag, attrs):
        if tag == 'span':
            self._flush()
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag == 'span':
            self._flush()
        super().handle_endtag(tag)
        if tag in {'div', 'article', 'li'} and len(self.blocks) < MAX_BLOCKS:
            # Do not pair a dangling name in one card with a title in the next.
            self.blocks.append('')
            self.block_ctx.append(frozenset())
            self.block_section.append('')
