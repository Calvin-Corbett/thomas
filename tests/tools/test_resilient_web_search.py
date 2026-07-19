"""Focused tests for the web.search provider fallback."""

from __future__ import annotations

import pytest

from thomas.tools.base import ToolResult
from thomas.tools.resilient_web_search import ResilientWebSearchTool, _parse_bing_html


class _Primary:
    def __init__(self, result: ToolResult) -> None:
        self.result = result
        self.calls: list[dict] = []

    async def execute(self, args: dict) -> ToolResult:
        self.calls.append(args)
        return self.result


def test_parse_bing_html_returns_normalized_rows() -> None:
    raw = """<ol><li class="b_algo"><h2>
    <a href="https://example.test/releases">Release notes</a></h2>
    <p>Latest <b>product</b> update.</p></li></ol>"""

    assert _parse_bing_html(raw, count=5) == [
        {
            "title": "Release notes",
            "url": "https://example.test/releases",
            "description": "Latest product update.",
            "published_date": None,
        }
    ]


@pytest.mark.asyncio
async def test_empty_primary_uses_bing_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    primary = _Primary(ToolResult(ok=True, data={"provider": "duckduckgo", "results": []}))
    tool = ResilientWebSearchTool(primary=primary)  # type: ignore[arg-type]

    async def _rows(_query: str, *, count: int):  # noqa: ANN202
        assert count == 3
        return [{"title": "Result", "url": "https://example.test", "description": "", "published_date": None}]

    monkeypatch.setattr(tool, "_bing_search", _rows)
    result = await tool.execute({"query": "current release", "count": 3})

    assert result.ok
    assert result.data["provider"] == "bing_html"
    assert result.data["results"][0]["url"] == "https://example.test"


@pytest.mark.asyncio
async def test_nonempty_primary_does_not_call_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    primary = _Primary(ToolResult(ok=True, data={"provider": "brave", "results": [{"url": "https://primary.test"}]}))
    tool = ResilientWebSearchTool(primary=primary)  # type: ignore[arg-type]

    async def _unexpected(_query: str, *, count: int):  # noqa: ANN202
        raise AssertionError(f"fallback called with {count=}")

    monkeypatch.setattr(tool, "_bing_search", _unexpected)
    result = await tool.execute({"query": "current release"})

    assert result.ok
    assert result.data["provider"] == "brave"
