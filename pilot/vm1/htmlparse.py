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

from .context import page_kind

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
# An <article> is a semantic container, not proof that its contents are editorial.
# It is labelled only when page metadata, schema, or meaningful source classes support it.
TAG_CTX = {"blockquote": "quote", "nav": "nav", "footer": "footer", "aside": "aside"}
ATTR_CTX_TOKENS = {
    "testimonial": "quote", "testimonials": "quote", "review": "quote", "reviews": "quote",
    "quote": "quote", "quotes": "quote", "blockquote": "quote",
    "client": "client", "clients": "client", "customer": "client", "customers": "client",
    "partner": "client", "partners": "client", "sponsor": "client", "sponsors": "client",
    "blog": "editorial", "blogs": "editorial", "post": "editorial", "posts": "editorial",
    "news": "editorial", "press": "editorial", "editorial": "editorial", "article": "editorial",
    "entry": "editorial", "author": "editorial", "byline": "editorial", "podcast": "editorial",
    "speaker": "editorial", "speakers": "editorial", "nav": "nav", "navbar": "nav", "menu": "nav",
    "footer": "footer",
}
_TOKEN_SPLIT = re.compile(r"[^a-z0-9]+")
_SCHEMA_EDITORIAL_TYPES = frozenset({
    "article", "blogposting", "newsarticle", "report", "scholarlyarticle", "techarticle",
})
_BRAND_TOKENS = frozenset({"brand", "brands"})
_LOGO_TOKENS = frozenset({"logo", "logos"})
_LOGO_LAYOUT_TOKENS = frozenset({"grid", "wall", "strip", "carousel", "list"})
_WP_CLASS_EXCLUSIONS = frozenset({
    "wp-custom-logo", "custom-logo", "site-logo", "wp-site-logo", "wp-block-site-logo",
    "wp-block-post-content", "post-type-page",
})
_EDITORIAL_ROOT_CLASS_TOKENS = frozenset({
    "blog", "blogs", "news", "press", "editorial", "single-post", "type-post", "post-type-post", "post",
})
MAX_BLOCK = 2000
MAX_BLOCKS = 5000
MAX_LINKS = 400
_WS = re.compile(r"\s+")


def norm_ws(s: str) -> str:
    return _WS.sub(" ", s).strip()


def _class_tokens(value: str) -> set[str]:
    """Tokenise CSS classes without treating generated WordPress/theme IDs as semantics."""
    tokens: set[str] = set()
    for cls in (value or "").lower().split():
        if cls in _WP_CLASS_EXCLUSIONS or re.fullmatch(r"post-\d+", cls):
            continue
        if cls.startswith("wp-block-post-content-is-layout-") or cls.startswith("ast-article-"):
            continue
        tokens.update(t for t in _TOKEN_SPLIT.split(cls) if t)
    return tokens


def _is_wp_static_page(classes: set[str]) -> bool:
    return any(
        cls in {"page", "type-page", "post-type-page"}
        or cls.startswith("page-id-")
        or cls.startswith("page-template-")
        for cls in classes
    )


def _is_editorial_schema_value(value: str) -> bool:
    if not isinstance(value, str):
        return False
    parts = [p.casefold() for p in re.split(r"[/#:\s]+", value) if p]
    return any(part in _SCHEMA_EDITORIAL_TYPES for part in parts)


def _jsonld_is_editorial(raw_values: list[str]) -> bool:
    for raw in raw_values:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for node in _walk(data):
            types = node.get("@type")
            if isinstance(types, str):
                types = [types]
            if isinstance(types, list) and any(
                _is_editorial_schema_value(t) for t in types if isinstance(t, str)
            ):
                return True
    return False


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
            value = a.get(attr, "").lower()
            if attr in {"class", "id"}:
                tokens = _class_tokens(value)
                if attr == "class":
                    classes = set(value.split())
                    # Root classes describe the CMS/theme more often than the
                    # semantics of every descendant. Keep explicit editorial
                    # page markers, but ignore generic client/logo styling.
                    if tag in {"html", "body"}:
                        if classes & _EDITORIAL_ROOT_CLASS_TOKENS:
                            labels.add("editorial")
                        continue
                    if _is_wp_static_page(classes) and not (
                        classes & {"type-post", "post-type-post", "single-post"}
                    ):
                        tokens.discard("post")
            else:
                tokens = set(_TOKEN_SPLIT.split(value))

            for tok in tokens:
                if tok in ATTR_CTX_TOKENS:
                    labels.add(ATTR_CTX_TOKENS[tok])

            # "brand" and "logo" are common design-system/site-identity words.
            # They become client evidence only in a recognisable collection pattern.
            if attr in {"class", "id", "data-testid"}:
                has_brand_collection = bool(tokens & _BRAND_TOKENS) and bool(
                    tokens & (_LOGO_TOKENS | _LOGO_LAYOUT_TOKENS)
                )
                has_logo_collection = bool(tokens & _LOGO_TOKENS) and bool(
                    tokens & _LOGO_LAYOUT_TOKENS
                )
                if has_brand_collection or has_logo_collection:
                    labels.add("client")
        return frozenset(labels)

    def _article_is_editorial(self, attrs: dict[str, str]) -> bool:
        if page_kind(self.base) == "editorial":
            return True
        if _is_editorial_schema_value(attrs.get("itemtype", "")):
            return True

        classes = set((attrs.get("class", "") or "").lower().split())
        tokens = _class_tokens(attrs.get("class", ""))
        if _is_wp_static_page(classes):
            # WordPress page wrappers commonly use <article> as layout. Require
            # a stronger editorial marker on those pages.
            return bool(tokens & {
                "blog", "blogs", "news", "press", "editorial", "author", "byline", "podcast",
            })
        return bool(tokens & {
            "blog", "blogs", "news", "press", "editorial", "article", "entry",
            "author", "byline", "podcast", "post",
        })

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
            if key in ("description", "og:site_name", "og:type") and a.get("content"):
                self.meta[key] = norm_ws(a["content"])
            return
        if tag == "a":
            href = a.get("href", "").strip()
            self.a_href = href or None
            self.a_text = []
        if tag in BLOCK_TAGS:
            self._flush()
        if tag not in VOID_TAGS:
            labels = set(self._labels(tag, a))
            if tag == "article" and self._article_is_editorial(a):
                labels.add("editorial")
            self.stack.append((tag, frozenset(labels)))

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
    og_type = ex.meta.get("og:type", "").casefold().split(":", 1)[0]
    if og_type == "article" or _jsonld_is_editorial(ex.jsonld_raw):
        ex.block_ctx = [frozenset((*ctx, "editorial")) for ctx in ex.block_ctx]
        people.block_ctx = [frozenset((*ctx, "editorial")) for ctx in people.block_ctx]
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
            labels = set(_Extractor._labels('div', attrs))
        if tag == 'div':
            classes = set(attrs.get('class', '').lower().split())
            # Conservative structural hints, not identity evidence. Only suppress
            # a field-level boundary when BOTH fields belong to a person card.
            if classes & {'person', 'person-card', 'team-member', 'team-member-card'}:
                labels.add('person_card')
            if 'person-info-name' in classes:
                labels.add('person_name_field')
            if 'person-info-title' in classes:
                labels.add('person_title_field')
        return frozenset(labels)

    def _is_team_roster_article(self, attrs):
        # Only accept a bare article as an employee card when nested in an
        # explicit team-list structure. Blogs, testimonials, client/partner
        # articles and generic editorial articles retain their veto.
        a = {k: v or "" for k, v in attrs}
        if _Extractor._labels('div', a) & {'quote', 'client', 'editorial'}:
            return False
        if any(lab & {'quote', 'client', 'editorial', 'nav', 'footer', 'aside'}
               for _, lab in self.stack):
            return False
        tags = [node for node, _ in self.stack]
        if 'ul' not in tags or 'li' not in tags or not self.headings:
            return False
        latest = self.headings[max(self.headings)]
        return bool(re.fullmatch(r"(?:our |the |meet (?:our |the )?)?team",
                                 norm_ws(latest), re.I))

    def handle_starttag(self, tag, attrs):
        team_roster = tag == 'article' and self._is_team_roster_article(attrs)
        if tag == 'span':
            self._flush()
        super().handle_starttag(tag, attrs)
        if team_roster and self.stack and self.stack[-1][0] == 'article':
            # The parser derives this label; source HTML cannot set it.
            labels = set(self.stack[-1][1])
            labels.discard('editorial')  # default label on bare articles
            labels.add('team_roster_article')
            self.stack[-1] = ('article', frozenset(labels))

    def handle_endtag(self, tag):
        if tag == 'span':
            self._flush()
        # Nested divs separating a name and a title must not always act as
        # whole-card separators. A semantic person-card parent explicitly
        # bounds that pair; its own closing div still inserts a separator.
        field_inside_card = False
        if tag == 'div':
            for i in range(len(self.stack) - 1, -1, -1):
                stack_tag, labels = self.stack[i]
                if stack_tag == 'div':
                    ancestors = self.stack[:i]
                    field_inside_card = (
                        any('team_roster_article' in lab for _, lab in ancestors)
                        or (bool(labels & {'person_name_field', 'person_title_field'})
                            and any('person_card' in lab for _, lab in ancestors))
                    )
                    break
        super().handle_endtag(tag)
        if (tag in {'div', 'article', 'li'} and not field_inside_card
                and len(self.blocks) < MAX_BLOCKS):
            # Preserve card boundaries: never pair a name from one card
            # with a title from a neighbouring card.
            self.blocks.append('')
            self.block_ctx.append(frozenset())
            self.block_section.append('')
