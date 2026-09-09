"""The agent can read the page's console and network traffic while it works.

Frontier parity: Claude in Chrome and Claude Code's browser pane expose console
errors, failed requests and response codes so the model debugs what it sees.
Layered on the registry by ``browser_parity`` so browser.py stays untouched.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from thomas.tools import browser as browser_tools
from thomas.tools import browser_parity as parity
from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _FakePage:
    url = "https://example.com/app"

    def __init__(self) -> None:
        self.handlers: dict[str, list] = {}

    def on(self, event, handler):  # noqa: ANN001
        self.handlers.setdefault(event, []).append(handler)

    def emit(self, event, payload):  # noqa: ANN001
        for handler in self.handlers.get(event, []):
            handler(payload)


def _fresh(name: str):
    parity._TELEMETRY.pop(name, None)
    page = _FakePage()
    parity.attach_telemetry(name, page)
    return page


def test_console_messages_are_kept_in_order_with_level_and_bounded() -> None:
    page = _fresh("s1")
    for i in range(parity._TELEMETRY_KEEP + 5):
        page.emit(
            "console", SimpleNamespace(type="error" if i % 2 == 0 else "log", text=f"m{i}", location={"url": "x"})
        )
    rows = parity.telemetry_for("s1")["console"]
    assert len(rows) == parity._TELEMETRY_KEEP
    assert rows[-1]["text"] == f"m{parity._TELEMETRY_KEEP + 4}" and rows[-1]["level"] == "error"


def test_page_errors_and_failed_requests_are_recorded_and_attach_is_once_per_page() -> None:
    page = _fresh("s2")
    parity.attach_telemetry("s2", page)
    assert len(page.handlers["console"]) == 1
    page.emit("pageerror", SimpleNamespace(message="TypeError: x is not a function", stack="at a.js:1"))
    page.emit(
        "requestfailed",
        SimpleNamespace(url="https://api.example.com/x", method="POST", failure=lambda: "net::ERR_FAILED"),
    )
    page.emit(
        "response",
        SimpleNamespace(url="https://example.com/data.json", status=500, request=SimpleNamespace(method="GET")),
    )
    bucket = parity.telemetry_for("s2")
    assert bucket["console"][-1]["level"] == "pageerror" and "not a function" in bucket["console"][-1]["text"]
    assert [r["status"] for r in bucket["network"]] == ["failed", 500]


def test_console_and_network_tools_filter(monkeypatch) -> None:
    page = _fresh("default")
    page.emit("console", SimpleNamespace(type="log", text="fine", location={}))
    page.emit("console", SimpleNamespace(type="error", text="broken", location={"url": "a.js", "lineNumber": 3}))
    page.emit(
        "response", SimpleNamespace(url="https://example.com/ok", status=200, request=SimpleNamespace(method="GET"))
    )
    page.emit(
        "response", SimpleNamespace(url="https://example.com/nope", status=404, request=SimpleNamespace(method="GET"))
    )

    async def _fake_ensure(_name, **_kw):
        return SimpleNamespace(page=page), page

    monkeypatch.setattr(browser_tools, "_ensure_session_page", _fake_ensure)
    console = asyncio.run(parity.BrowserConsoleTool().execute({"errors_only": True}))
    network = asyncio.run(parity.BrowserNetworkTool().execute({"failures_only": True}))
    assert console.ok and "broken" in str(console.data) and "fine" not in str(console.data)
    assert network.ok and "/nope" in str(network.data) and "/ok" not in str(network.data)


def test_install_wraps_click_type_open_and_adds_two_tools() -> None:
    class _T(Tool):
        category = "browser"
        description = "fake"
        parameters = {"type": "object", "properties": {}}

        def __init__(self, name: str) -> None:
            self.name = name

        async def execute(self, args):  # noqa: ANN001, ARG002
            return ToolResult(ok=True, data=self.name)

    registry = ToolRegistry()
    for name in ("browser.open", "browser.click", "browser.type", "browser.close"):
        registry.register(_T(name))

    added = parity.install_browser_parity(registry)

    assert added == 2
    assert isinstance(registry.get("browser.click"), parity.SensitiveSiteGuard)
    assert isinstance(registry.get("browser.type"), parity.SensitiveSiteGuard)
    assert isinstance(registry.get("browser.open"), parity.TelemetryOnOpen)
    assert registry.get("browser.close").name == "browser.close"
    assert {t.name for t in registry.list_tools("browser")} >= {"browser.console", "browser.network"}
    assert parity.install_browser_parity(registry) == 0
