"""Resilient web.search wrapper with a bounded Bing HTML fallback."""

from __future__ import annotations

import base64
import html
import time
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from thomas.tools.base import Tool, ToolResult
from thomas.tools.web_search import WebSearchTool, get_web_search_tool

_BING_SEARCH_URL = "https://www.bing.com/search"


def _decode_bing_url(raw_url: str) -> str:
    """Decode Bing's `u=a1<base64url>` redirect when present."""
    url = html.unescape(str(raw_url or "").strip())
    parsed = urlparse(url)
    if not parsed.netloc.lower().endswith("bing.com") or not parsed.path.startswith("/ck/"):
        return url
    encoded = parse_qs(parsed.query).get("u", [""])[0]
    if not encoded.startswith("a1"):
        return url
    payload = encoded[2:]
    try:
        return base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)).decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return url


class _BingResultsParser(HTMLParser):
    def __init__(self, *, count: int) -> None:
        super().__init__(convert_charrefs=True)
        self.count = count
        self.results: list[dict[str, Any]] = []
        self._in_result = False
        self._in_h2 = False
        self._in_anchor = False
        self._in_description = False
        self._url = ""
        self._title: list[str] = []
        self._description: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = str(attributes.get("class") or "").split()
        if tag == "li" and "b_algo" in classes:
            self._in_result = True
            self._url = ""
            self._title = []
            self._description = []
        elif self._in_result and tag == "h2":
            self._in_h2 = True
        elif self._in_h2 and tag == "a":
            self._in_anchor = True
            self._url = _decode_bing_url(str(attributes.get("href") or ""))
        elif self._in_result and tag == "p" and not self._description:
            self._in_description = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a":
            self._in_anchor = False
        elif tag == "h2":
            self._in_h2 = False
        elif tag == "p":
            self._in_description = False
        elif tag == "li" and self._in_result:
            title = " ".join("".join(self._title).split())
            description = " ".join("".join(self._description).split())
            if title and self._url.startswith(("http://", "https://")) and len(self.results) < self.count:
                self.results.append(
                    {
                        "title": title,
                        "url": self._url,
                        "description": description,
                        "published_date": None,
                    }
                )
            self._in_result = False

    def handle_data(self, data: str) -> None:
        if self._in_anchor:
            self._title.append(data)
        elif self._in_description:
            self._description.append(data)


def _parse_bing_html(raw: str, *, count: int) -> list[dict[str, Any]]:
    parser = _BingResultsParser(count=count)
    parser.feed(raw)
    parser.close()
    return parser.results


class ResilientWebSearchTool(Tool):
    """Run the existing provider chain, then Bing HTML when it returns no rows."""

    name = "web.search"
    category = "web"
    description = WebSearchTool.description
    parameters = WebSearchTool.parameters

    def __init__(self, primary: WebSearchTool | None = None) -> None:
        self._primary = primary or get_web_search_tool()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        """Search using the primary providers, then a bounded public fallback.

        Args:
            args: web.search arguments containing query, optional count, and freshness.

        Returns:
            ToolResult containing normalized result rows and provider metadata.

        Raises:
            No network exceptions escape; provider failures are returned in ToolResult.
        """
        started = time.monotonic()
        primary = await self._primary.execute(args)
        primary_data = primary.data if isinstance(primary.data, dict) else {}
        if primary.ok and list(primary_data.get("results") or []):
            return primary

        query = str(args.get("query") or "").strip()
        if not query:
            return primary
        try:
            count = max(1, min(10, int(args.get("count", 5))))
        except (TypeError, ValueError):
            count = 5

        try:
            results = await self._bing_search(query, count=count)
        except (httpx.HTTPError, UnicodeError, ValueError) as exc:
            if not primary.ok:
                return primary
            return ToolResult(
                ok=False,
                error=f"Web search providers returned no usable results: {exc}",
                duration_ms=(time.monotonic() - started) * 1000,
            )
        if not results:
            return ToolResult(
                ok=False,
                error="Web search providers returned no usable results.",
                duration_ms=(time.monotonic() - started) * 1000,
            )
        return ToolResult(
            ok=True,
            data={
                "provider": "bing_html",
                "query": query,
                "count": count,
                "results": results,
                "meta": {"fallback_from": str(primary_data.get("provider") or "primary")},
            },
            duration_ms=(time.monotonic() - started) * 1000,
        )

    async def _bing_search(self, query: str, *, count: int) -> list[dict[str, Any]]:
        params = urlencode({"q": query, "count": count})
        headers = {"User-Agent": "Mozilla/5.0 (compatible; Thomas/0.17; +https://github.com/)"}
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False, headers=headers) as client:
            response = await client.get(f"{_BING_SEARCH_URL}?{params}")
            response.raise_for_status()
        return _parse_bing_html(response.text, count=count)


def get_resilient_web_search_tool() -> ResilientWebSearchTool:
    """Build the shared resilient web.search implementation."""
    return ResilientWebSearchTool()


__all__ = ["ResilientWebSearchTool", "get_resilient_web_search_tool"]
