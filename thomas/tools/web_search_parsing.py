"""Web search result parsing and content extraction utilities.

Handles:
  - HTML content extraction for web.fetch
  - Search result normalization (Brave, DuckDuckGo, etc.)
  - Result deduplication and domain diversification
  - HTML parsing for DuckDuckGo fallback
"""

from __future__ import annotations

from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse


def _safe_str(v: Any) -> str:
    """Safely convert value to string."""
    if isinstance(v, str):
        return v
    if v is None:
        return ""
    return str(v)


def _parse_isoish_date(s: str | None) -> str | None:
    """Parse approximate ISO date formats and return clean ISO date."""
    if not s:
        return None
    s = _safe_str(s).strip()
    if not s:
        return None

    # Try exact ISO 8601 (most common)
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]  # YYYY-MM-DD

    # Accept anything that looks like YYYY (at least)
    for part in s.split()[:3]:
        if len(part) == 4 and part.isdigit():
            return f"{part}-01-01"

    return None


def _canonicalize_url(url: str) -> str:
    """Remove tracking and common query parameters."""
    if not url:
        return url

    try:
        from urllib.parse import parse_qs, urlencode, urlparse, urlunparse
    except ImportError:
        return url

    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query, keep_blank_values=False)

        # Remove tracking parameters
        tracking_params = {
            "utm_source",
            "utm_medium",
            "utm_campaign",
            "utm_content",
            "utm_term",
            "gclid",
            "fbclid",
            "msclkid",
            "dclid",
            "mkwid",
            "pcrid",
        }

        cleaned = {k: v for k, v in params.items() if k.lower() not in tracking_params}
        new_query = urlencode(cleaned, doseq=True) if cleaned else ""
        new_parsed = parsed._replace(query=new_query)
        return urlunparse(new_parsed)
    except Exception:
        return url


def _compact_ws(text: str) -> str:
    """Collapse whitespace to single spaces."""
    return " ".join(text.split())


def _strip_common_noise(text: str) -> str:
    """Remove common HTML cruft: nav, footer, sidebar hints."""
    if not text:
        return text

    lines = text.split("\n")
    cleaned: list[str] = []

    for line in lines:
        lower = line.lower()
        skip = (
            "cookie" in lower
            or "accept all" in lower
            or "javascript required" in lower
            or "advertisement" in lower
            or "subscribe" in lower
            or "newsletter" in lower
        )
        if not skip:
            cleaned.append(line)

    return "\n".join(cleaned)


class _HTMLMainExtractor(HTMLParser):
    """Extract main article/content from HTML (skip nav, footer, etc)."""

    def __init__(self) -> None:
        super().__init__()
        self.main_text: list[str] = []
        self._in_main = False
        self._in_header = False
        self._in_footer = False
        self._in_nav = False
        self._in_script = False
        self._in_style = False
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        {k.lower(): (v or "").lower() for k, v in attrs}

        if t == "script" or t == "style":
            self._in_script = t == "script"
            self._in_style = t == "style"

        if t in ("header", "nav"):
            self._in_nav = True
        elif t == "footer":
            self._in_footer = True
        elif t in ("main", "article", "section"):
            self._in_main = True
            self._depth += 1
        elif t == "head":
            pass

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()

        if t == "script":
            self._in_script = False
        elif t == "style":
            self._in_style = False
        elif t in ("header", "nav"):
            self._in_nav = False
        elif t == "footer":
            self._in_footer = False
        elif t in ("main", "article", "section"):
            self._depth -= 1
            self._in_main = self._depth > 0

    def handle_data(self, data: str) -> None:
        if self._in_script or self._in_style or self._in_nav or self._in_footer:
            return
        if data and data.strip():
            self.main_text.append(_compact_ws(data))


def _extract_html(html: str) -> dict[str, str | None]:
    """Extract clean text from HTML."""
    if not html:
        return {"text": "", "title": None}

    try:
        parser = _HTMLMainExtractor()
        parser.feed(html)
        text = "\n".join(parser.main_text).strip()
        text = _strip_common_noise(text)
        return {"text": text[:8000], "title": None}
    except Exception:
        return {"text": "", "title": None}


def _normalize_brave_result(item: dict[str, Any]) -> dict[str, Any]:
    """Normalize Brave Search API result to common format."""
    title = _safe_str(item.get("title") or item.get("name")).strip()
    url = _safe_str(item.get("url") or item.get("link")).strip()
    desc = _safe_str(item.get("description") or item.get("snippet")).strip()

    published = (
        item.get("age")
        or item.get("published_date")
        or item.get("page_age")
        or item.get("date")
        or item.get("last_crawled")
    )
    published_date = _parse_isoish_date(_safe_str(published)) if published else None

    url = _canonicalize_url(url) if url else url

    return {"title": title, "url": url, "description": desc, "published_date": published_date}


def _flatten_ddg_related_topics(related_topics: Any) -> list[dict[str, Any]]:
    """Flatten DuckDuckGo related topics structure."""
    out: list[dict[str, Any]] = []
    if not isinstance(related_topics, list):
        return out

    for item in related_topics:
        if not isinstance(item, dict):
            continue
        if "Topics" in item and isinstance(item["Topics"], list):
            out.extend(_flatten_ddg_related_topics(item["Topics"]))
            continue
        text = item.get("Text")
        first_url = item.get("FirstURL")
        if text and first_url:
            t = _safe_str(text).strip()
            u = _canonicalize_url(_safe_str(first_url).strip())
            if t and u:
                out.append({"title": t, "url": u, "description": t, "published_date": None})
    return out


def _dedupe_by_url(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Remove duplicate results by URL."""
    seen = set()
    out: list[dict[str, Any]] = []
    for r in results:
        u = (r.get("url") or "").strip()
        if not u or u in seen:
            continue
        seen.add(u)
        out.append(r)
    return out


def _domain(u: str) -> str:
    """Extract domain from URL."""
    try:
        return (urlparse(u).hostname or "").lower()
    except (ValueError, AttributeError):
        return ""


def _diversify_by_domain(results: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    """Prefer unique domains first, then fill remaining slots."""
    picked: list[dict[str, Any]] = []
    seen_dom = set()

    for r in results:
        if len(picked) >= count:
            break
        dom = _domain(r.get("url") or "")
        if dom and dom not in seen_dom:
            picked.append(r)
            seen_dom.add(dom)

    if len(picked) < count:
        for r in results:
            if len(picked) >= count:
                break
            if r in picked:
                continue
            picked.append(r)

    return picked[:count]


class _DDGHtmlResultsParser(HTMLParser):
    """Best-effort parser for DuckDuckGo HTML results page."""

    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, Any]] = []
        self._in_result = False
        self._cur: dict[str, Any] = {}
        self._capture_title = False
        self._capture_snippet = False
        self._title_parts: list[str] = []
        self._snip_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        t = tag.lower()
        a = {k.lower(): (v or "") for k, v in attrs}
        if t == "div" and "result" in (a.get("class", "")):
            self._in_result = True
            self._cur = {}
            self._title_parts = []
            self._snip_parts = []
        if self._in_result and t == "a":
            cls = a.get("class", "")
            href = a.get("href", "").strip()
            if href and ("result__a" in cls or "result-link" in cls or "result__url" in cls):
                self._cur["url"] = href
                self._capture_title = True
        if self._in_result and t in ("a", "div", "span"):
            cls = a.get("class", "")
            if "result__snippet" in cls:
                self._capture_snippet = True

    def handle_endtag(self, tag: str) -> None:
        t = tag.lower()
        if t == "a":
            self._capture_title = False
        if t in ("div", "span"):
            self._capture_snippet = False
        if t == "div" and self._in_result:
            title = _compact_ws(unescape(" ".join(self._title_parts)))
            snip = _compact_ws(unescape(" ".join(self._snip_parts)))
            url = _canonicalize_url(_safe_str(self._cur.get("url")).strip())
            if title and url:
                self.results.append({"title": title, "url": url, "description": snip or title, "published_date": None})
            self._in_result = False
            self._cur = {}
            self._title_parts = []
            self._snip_parts = []

    def handle_data(self, data: str) -> None:
        if not data or not data.strip():
            return
        if self._capture_title:
            self._title_parts.append(data)
        if self._capture_snippet:
            self._snip_parts.append(data)
