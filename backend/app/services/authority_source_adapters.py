from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
import re
from urllib.parse import urljoin, urlparse


@dataclass(frozen=True)
class ParsedArticle:
    content: str
    title: str | None
    publisher: str | None
    published_date: date | None
    parser_version: str


def _normalize_text(parts: list[str]) -> str:
    lines = [" ".join(line.split()) for line in " ".join(parts).splitlines()]
    return "\n".join(line for line in lines if line).strip()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    match = re.search(r"(20\d{2})[年./\-](\d{1,2})[月./\-](\d{1,2})", value)
    if not match:
        return None
    try:
        return date(*map(int, match.groups()))
    except ValueError:
        return None


class _ListingParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attributes = {key.lower(): (value or "").strip() for key, value in attrs}
        self._href = attributes.get("href") or None
        self._text = []

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._href:
            return
        self.links.append((self._href, " ".join(" ".join(self._text).split())))
        self._href = None
        self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None and data.strip():
            self._text.append(data.strip())


class _ArticleParser(HTMLParser):
    _ignored_tags = {"script", "style", "noscript", "svg", "nav", "footer", "aside"}
    _block_tags = {"p", "article", "section", "div", "h1", "h2", "h3", "li", "br", "table", "tr"}
    _void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self, *, content_markers: tuple[str, ...], noise_markers: tuple[str, ...]) -> None:
        super().__init__()
        self.content_markers = tuple(item.lower() for item in content_markers)
        self.noise_markers = tuple(item.lower() for item in noise_markers)
        self.all_parts: list[str] = []
        self.scoped_parts: list[str] = []
        self.meta: dict[str, str] = {}
        self.page_title = ""
        self.first_h1 = ""
        self._capture: str | None = None
        self._capture_parts: list[str] = []
        self._stack: list[tuple[str, bool, bool]] = []
        self._content_depth = 0
        self._ignored_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attributes = {key.lower(): (value or "").strip() for key, value in attrs}
        marker = " ".join((attributes.get(key) or "") for key in ("id", "class", "role")).lower()
        is_content = tag in {"article", "main"} or any(item in marker for item in self.content_markers)
        is_ignored = tag in self._ignored_tags or any(item in marker for item in self.noise_markers)
        if tag not in self._void_tags:
            self._stack.append((tag, is_content, is_ignored))
            if is_content:
                self._content_depth += 1
            if is_ignored:
                self._ignored_depth += 1
        if tag == "meta" and attributes.get("content"):
            key = (attributes.get("property") or attributes.get("name") or attributes.get("itemprop") or "").lower()
            if key:
                self.meta[key] = attributes["content"]
        if tag in {"title", "h1"}:
            self._capture = tag
            self._capture_parts = []
        if tag in self._block_tags:
            self._append("\n")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._void_tags:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self._block_tags:
            self._append("\n")
        if self._capture == tag:
            value = " ".join(" ".join(self._capture_parts).split())
            if tag == "title":
                self.page_title = value
            elif tag == "h1" and not self.first_h1:
                self.first_h1 = value
            self._capture = None
            self._capture_parts = []
        if tag not in {item[0] for item in self._stack}:
            return
        index = len(self._stack) - 1 - [item[0] for item in self._stack][::-1].index(tag)
        closing = self._stack[index:]
        del self._stack[index:]
        self._content_depth = max(0, self._content_depth - sum(item[1] for item in closing))
        self._ignored_depth = max(0, self._ignored_depth - sum(item[2] for item in closing))

    def handle_data(self, data: str) -> None:
        if self._capture and data.strip():
            self._capture_parts.append(data.strip())
        if data.strip():
            self._append(data.strip())

    def _append(self, value: str) -> None:
        if self._ignored_depth:
            return
        self.all_parts.append(value)
        if self._content_depth:
            self.scoped_parts.append(value)

    def content(self) -> str:
        scoped = _normalize_text(self.scoped_parts)
        generic = _normalize_text(self.all_parts)
        if len(re.sub(r"\s+", "", scoped)) >= 60:
            return scoped
        return generic

    def metadata(self, raw_html: str) -> tuple[str | None, str | None, date | None]:
        def first(*keys: str) -> str | None:
            return next((self.meta[key].strip() for key in keys if self.meta.get(key, "").strip()), None)

        title = first("og:title", "twitter:title", "headline") or self.first_h1 or self.page_title or None
        publisher = first(
            "publisher", "source", "og:site_name", "application-name", "sitename",
        )
        raw_date = first(
            "article:published_time", "datepublished", "publishdate", "pubdate",
            "release_date", "date", "sailthru.date",
        )
        visible = _normalize_text(self.all_parts)[:6000]
        published_date = _parse_date(raw_date) or _parse_date(visible)
        source_match = re.search(r"(?:来源|发布机构)[：:]\s*([^\s|]{2,40})", visible)
        if source_match:
            publisher = source_match.group(1).strip()
        return title, publisher, published_date


class AuthoritySourceAdapter:
    name = "generic"
    domains: tuple[str, ...] = ()
    content_markers = (
        "article", "content", "detail", "editor", "trs_editor", "news_body", "pages_content",
    )
    noise_markers = (
        "breadcrumb", "crumb", "footer", "header", "navigation", "sidebar", "recommend",
        "related", "share", "toolbar", "copyright", "friendlink",
    )
    default_publisher: str | None = None
    detail_path_patterns: tuple[str, ...] = ()

    def matches_domain(self, domain: str) -> bool:
        normalized = domain.lower().removeprefix("www.").rstrip(".")
        return any(normalized == item or normalized.endswith(f".{item}") for item in self.domains)

    def parse_listing(self, html: str, base_url: str) -> list[tuple[str, str]]:
        parser = _ListingParser()
        parser.feed(html)
        links = [(urljoin(base_url, href), title) for href, title in parser.links]
        if not self.detail_path_patterns:
            return links
        return [
            item for item in links
            if any(re.search(pattern, urlparse(item[0]).path, re.IGNORECASE) for pattern in self.detail_path_patterns)
        ]

    def parse_article(self, html: str) -> ParsedArticle:
        parser = _ArticleParser(content_markers=self.content_markers, noise_markers=self.noise_markers)
        parser.feed(html)
        content = parser.content()
        title, publisher, published_date = parser.metadata(html)
        return ParsedArticle(
            content=content,
            title=title,
            publisher=publisher or self.default_publisher,
            published_date=published_date,
            parser_version=f"authority-{self.name}-v1",
        )


class GovCnAdapter(AuthoritySourceAdapter):
    name = "gov-cn"
    domains = ("gov.cn",)
    content_markers = (
        "pages_content", "ucap-content", "article", "article-content", "content", "detail", "editor",
    )
    detail_path_patterns = (r"^/zhengce/(?:content/)?20\d{4}/content_\d+\.htm$",)
    default_publisher = "中国政府网"


class MoeGovCnAdapter(AuthoritySourceAdapter):
    name = "moe-gov-cn"
    domains = ("moe.gov.cn",)
    content_markers = (
        "trs_editor", "trs_preappend", "article", "article-content", "content_body", "content",
    )
    detail_path_patterns = (
        r"^/jyb_xwfb/gzdt_gzdt/(?:[^/]+/)+20\d{4}/t20\d{6}_\d+\.html$",
    )
    default_publisher = "教育部"


class QstheoryCnAdapter(AuthoritySourceAdapter):
    name = "qstheory-cn"
    domains = ("qstheory.cn",)
    content_markers = (
        "article-content", "article_content", "article", "text", "content", "detail",
    )
    detail_path_patterns = (r"^/20\d{6}/[0-9a-f]+/c\.html$",)
    default_publisher = "求是网"


_GENERIC_ADAPTER = AuthoritySourceAdapter()
_REGISTERED_ADAPTERS = (MoeGovCnAdapter(), GovCnAdapter(), QstheoryCnAdapter())


def get_source_adapter(domain: str) -> AuthoritySourceAdapter:
    return next((adapter for adapter in _REGISTERED_ADAPTERS if adapter.matches_domain(domain)), _GENERIC_ADAPTER)
