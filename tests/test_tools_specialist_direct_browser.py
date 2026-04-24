from __future__ import annotations

from types import SimpleNamespace

import pytest

from tests.test_tools_specialist_support import _collect_events, _direct_token, _FakeCodexEvent, _FakeCodexLLM
from thomas.marketplace.specialists import tools as mod
from thomas.marketplace.specialists.tools import (
    ToolSpecialist,
)


@pytest.mark.asyncio
async def test_direct_fast_path_fetches_headline_and_returns_exact_text(monkeypatch: pytest.MonkeyPatch) -> None:
    specialist = ToolSpecialist(config=None, llm=None, tools=None)

    async def _fake_fetch(url: str) -> str:
        return "ExampleSite: The AI that actually does things"

    monkeypatch.setattr(mod, "_fetch_browser_headline", _fake_fetch)

    events = []
    async for event in specialist._run_direct_fast_path(
        "Use your tools to open https://example-tool.org and answer with only the exact main headline on the page.",
        _direct_token(),
    ):
        events.append(event)

    assert [event["type"] for event in events] == ["tool_start", "tool_result", "text", "done"]
    assert events[0]["name"] == "direct.fetch_url"
    assert events[0]["args"] == {"url": "https://example-tool.org"}
    assert events[1]["result"] == "ExampleSite: The AI that actually does things"
    assert events[2]["text"] == "ExampleSite: The AI that actually does things"
    assert events[3]["content"] == "ExampleSite: The AI that actually does things"


@pytest.mark.asyncio
async def test_direct_fast_path_fetches_title_and_returns_exact_text(monkeypatch: pytest.MonkeyPatch) -> None:
    specialist = ToolSpecialist(config=None, llm=None, tools=None)

    async def _fake_fetch(url: str) -> str:
        return "ExampleSite Home"

    monkeypatch.setattr(mod, "_fetch_browser_title", _fake_fetch)

    events = []
    async for event in specialist._run_direct_fast_path(
        "Use your tools to open https://example-tool.org and answer with only the exact page title.",
        _direct_token(),
    ):
        events.append(event)

    assert [event["type"] for event in events] == ["tool_start", "tool_result", "text", "done"]
    assert events[0]["name"] == "direct.fetch_url"
    assert events[1]["result"] == "ExampleSite Home"
    assert events[2]["text"] == "ExampleSite Home"
    assert events[3]["content"] == "ExampleSite Home"


@pytest.mark.asyncio
async def test_direct_fast_path_fetches_main_text_and_returns_exact_text(monkeypatch: pytest.MonkeyPatch) -> None:
    specialist = ToolSpecialist(config=None, llm=None, tools=None)

    async def _fake_fetch(url: str) -> str:
        return "ExampleSite helps you automate local machine work quickly."

    monkeypatch.setattr(mod, "_fetch_browser_main_text", _fake_fetch)

    events = []
    async for event in specialist._run_direct_fast_path(
        "Use your tools to open https://example-tool.org and answer with only the exact main text.",
        _direct_token(),
    ):
        events.append(event)

    assert [event["type"] for event in events] == ["tool_start", "tool_result", "text", "done"]
    assert events[0]["name"] == "direct.fetch_url"
    assert events[1]["result"] == "ExampleSite helps you automate local machine work quickly."
    assert events[2]["text"] == "ExampleSite helps you automate local machine work quickly."
    assert events[3]["content"] == "ExampleSite helps you automate local machine work quickly."


@pytest.mark.asyncio
async def test_direct_fast_path_clicks_label_and_returns_exact_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    specialist = ToolSpecialist(config=None, llm=None, tools=None)
    open_calls: list[dict[str, object]] = []
    click_calls: list[dict[str, object]] = []

    async def _fake_open(self, args):  # noqa: ANN001
        _ = self
        open_calls.append(dict(args))
        return SimpleNamespace(ok=True, data={"url": "https://example-tool.org/docs"}, error=None)

    async def _fake_click(self, args):  # noqa: ANN001
        _ = self
        click_calls.append(dict(args))
        return SimpleNamespace(ok=True, data={"clicked": "Docs", "url_changed": True}, error=None)

    monkeypatch.setattr(mod.BrowserOpenTool, "execute", _fake_open)
    monkeypatch.setattr(mod.BrowserClickTool, "execute", _fake_click)

    events = []
    async for event in specialist._run_direct_fast_path(
        "Use your tools to open https://example-tool.org and click Docs, then answer with only OK.",
        _direct_token(),
    ):
        events.append(event)

    assert [event["type"] for event in events] == ["tool_start", "tool_result", "tool_start", "tool_result", "text", "done"]
    assert events[0]["name"] == "direct.open_url"
    assert events[2]["name"] == "direct.click"
    assert events[4]["text"] == "OK"
    assert events[5]["content"] == "OK"
    assert open_calls[0]["session"] == "action-direct"
    assert open_calls[0]["lane"] == "action"
    assert open_calls[0]["headline_only"] is True
    assert open_calls[0]["navigation_only"] is True
    assert click_calls[0]["selector"] == 'role=link[name="Docs"]'
    assert click_calls[0]["session"] == "action-direct"
    assert click_calls[0]["post_click_stabilize_ms"] == 800
    assert click_calls[0]["prefer_link_navigation"] is True


@pytest.mark.asyncio
async def test_headline_fast_path_falls_back_to_codex_when_direct_fetch_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _boom(url: str) -> str:
        raise RuntimeError(f"boom for {url}")

    monkeypatch.setattr(mod, "_fetch_browser_headline", _boom)
    llm = _FakeCodexLLM(
        [
            _FakeCodexEvent("token", {"text": "Opening the page now."}),
            _FakeCodexEvent("tool_call_start", {"name": "browser_read", "id": "call-headline"}),
            _FakeCodexEvent(
                "tool_call_end",
                {
                    "name": "browser_read",
                    "id": "call-headline",
                    "output": "ExampleSite: The AI that actually does things",
                },
            ),
            _FakeCodexEvent(
                "token",
                {
                    "text": "Opening the site now and extracting the hero copy.\nExampleSite: The AI that actually does things"
                },
            ),
            _FakeCodexEvent("done"),
        ]
    )
    specialist = ToolSpecialist(config=None, llm=llm, tools=None)

    events = await _collect_events(
        specialist,
        "Use your tools to open https://example-tool.org and answer with only the exact main headline on the page.",
    )

    assert [event["type"] for event in events] == [
        "tool_start",
        "tool_result",
        "tool_start",
        "tool_result",
        "text",
        "done",
    ]
    assert events[0]["name"] == "direct.fetch_url"
    assert events[1]["ok"] is False
    assert events[2]["name"] == "browser_read"
    assert events[4]["text"] == "ExampleSite: The AI that actually does things"
    assert events[5]["content"] == "ExampleSite: The AI that actually does things"
