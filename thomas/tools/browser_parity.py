"""Sensitive-site pause and console/network telemetry for the browser tools.

Installed on the registry right after ``register_browser_tools`` so
``thomas/tools/browser.py`` itself stays untouched (it sits over the size
guard's limit). Three things:

- ``browser.click`` and ``browser.type`` pause on sensitive hosts (frontier
  parity: Claude in Chrome, ChatGPT agent mode) via ``site_policy``.
- ``browser.open`` attaches console / page-error / response / failed-request
  listeners to the session's page, once per page.
- ``browser.console`` and ``browser.network`` read those rings, newest last.
"""

from __future__ import annotations

import time
from typing import Any

from thomas.tools import browser as _browser
from thomas.tools.base import Tool, ToolResult
from thomas.tools.site_policy import sensitive_action_verdict

_TELEMETRY_KEEP = 200
_TELEMETRY: dict[str, dict[str, Any]] = {}
_SESSION_ERRORS = (RuntimeError, OSError, ValueError, AttributeError, TypeError, KeyError)


def telemetry_for(session_name: str) -> dict[str, Any]:
    return _TELEMETRY.setdefault(str(session_name or "default"), {"console": [], "network": [], "page": None})


def _push(rows: list[dict[str, Any]], row: dict[str, Any]) -> None:
    rows.append(row)
    if len(rows) > _TELEMETRY_KEEP:
        del rows[: len(rows) - _TELEMETRY_KEEP]


def attach_telemetry(session_name: str, page: Any) -> None:
    """Record console messages, page errors, responses and failed requests for this page."""
    bucket = telemetry_for(session_name)
    if bucket.get("page") is page:
        return
    console, network = bucket["console"], bucket["network"]

    def _on_console(msg: Any) -> None:
        try:
            location = getattr(msg, "location", None) or {}
            where = ""
            if isinstance(location, dict) and location.get("url"):
                where = f"{location.get('url')}:{location.get('lineNumber', '')}".rstrip(":")
            _push(
                console,
                {
                    "level": str(getattr(msg, "type", "log") or "log"),
                    "text": str(getattr(msg, "text", "") or ""),
                    "where": where,
                    "at": time.time(),
                },
            )
        except (AttributeError, TypeError, ValueError):
            pass

    def _on_pageerror(err: Any) -> None:
        try:
            text = str(getattr(err, "message", None) or err)
            stack = str(getattr(err, "stack", "") or "")
            _push(console, {"level": "pageerror", "text": text, "where": stack[:300], "at": time.time()})
        except (AttributeError, TypeError, ValueError):
            pass

    def _on_response(resp: Any) -> None:
        try:
            request = getattr(resp, "request", None)
            _push(
                network,
                {
                    "method": str(getattr(request, "method", "") or ""),
                    "url": str(getattr(resp, "url", "") or ""),
                    "status": int(getattr(resp, "status", 0) or 0),
                    "at": time.time(),
                },
            )
        except (AttributeError, TypeError, ValueError):
            pass

    def _on_requestfailed(req: Any) -> None:
        try:
            failure = getattr(req, "failure", None)
            reason = failure() if callable(failure) else failure
            _push(
                network,
                {
                    "method": str(getattr(req, "method", "") or ""),
                    "url": str(getattr(req, "url", "") or ""),
                    "status": "failed",
                    "reason": str(reason or ""),
                    "at": time.time(),
                },
            )
        except (AttributeError, TypeError, ValueError):
            pass

    for event, handler in (
        ("console", _on_console),
        ("pageerror", _on_pageerror),
        ("response", _on_response),
        ("requestfailed", _on_requestfailed),
    ):
        try:
            page.on(event, handler)
        except (AttributeError, TypeError, ValueError):
            pass
    bucket["page"] = page


async def _session_page(args: dict[str, Any]) -> tuple[str, Any, Any]:
    name = _browser._get_session_name(args)
    _sess, page = await _browser._ensure_session_page(name)
    return name, _sess, page


class _Wrapped(Tool):
    """A browser tool with the same name and contract, plus a step before it runs."""

    def __init__(self, inner: Tool) -> None:
        self._inner = inner
        self.name = inner.name
        self.category = inner.category
        self.description = inner.description
        self.parameters = inner.parameters


class SensitiveSiteGuard(_Wrapped):
    def __init__(self, inner: Tool, action: str) -> None:
        super().__init__(inner)
        self._action = action

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            name, _sess, page = await _session_page(args)
        except _SESSION_ERRORS:
            # No page to judge: the inner tool reports its own session error.
            return await self._inner.execute(args)
        attach_telemetry(name, page)
        paused = sensitive_action_verdict(str(getattr(page, "url", "") or ""), action=self._action)
        if paused:
            return ToolResult(ok=False, data=None, error=paused)
        return await self._inner.execute(args)


class TelemetryOnOpen(_Wrapped):
    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            name, _sess, page = await _session_page(args)
            attach_telemetry(name, page)
        except _SESSION_ERRORS:
            pass  # listeners are best effort; opening the page is not
        return await self._inner.execute(args)


class BrowserConsoleTool(Tool):
    name = "browser.console"
    category = "browser"
    description = (
        "Read the current page's console: log/warn/error messages and uncaught page errors, newest last. "
        "Use it to debug what the page did instead of guessing."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "errors_only": {"type": "boolean", "description": "Only errors and page errors (default false)."},
            "limit": {"type": "integer", "description": "Max entries (default 50)."},
            "session": {"type": "string", "description": "Optional session name."},
        },
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            name, _sess, page = await _session_page(args)
        except _SESSION_ERRORS as e:
            return ToolResult(ok=False, data=None, error=f"{type(e).__name__}: {e}")
        attach_telemetry(name, page)
        rows = list(telemetry_for(name)["console"])
        if bool(args.get("errors_only", False)):
            rows = [r for r in rows if r.get("level") in {"error", "pageerror"}]
        limit = max(1, int(args.get("limit", 50) or 50))
        rows = rows[-limit:]
        return ToolResult(
            ok=True, data={"url": str(getattr(page, "url", "") or ""), "count": len(rows), "entries": rows}
        )


class BrowserNetworkTool(Tool):
    name = "browser.network"
    category = "browser"
    description = (
        "Read the current page's network traffic: method, URL and status per response, plus failed "
        "requests, newest last. Use failures_only to see what broke."
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "failures_only": {"type": "boolean", "description": "Only 4xx/5xx and failed requests (default false)."},
            "url_contains": {"type": "string", "description": "Substring filter on the URL."},
            "limit": {"type": "integer", "description": "Max entries (default 50)."},
            "session": {"type": "string", "description": "Optional session name."},
        },
        "additionalProperties": False,
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            name, _sess, page = await _session_page(args)
        except _SESSION_ERRORS as e:
            return ToolResult(ok=False, data=None, error=f"{type(e).__name__}: {e}")
        attach_telemetry(name, page)
        rows = list(telemetry_for(name)["network"])
        if bool(args.get("failures_only", False)):
            rows = [r for r in rows if r.get("status") == "failed" or int(r.get("status") or 0) >= 400]
        needle = str(args.get("url_contains") or "").strip()
        if needle:
            rows = [r for r in rows if needle in str(r.get("url", ""))]
        limit = max(1, int(args.get("limit", 50) or 50))
        rows = rows[-limit:]
        return ToolResult(
            ok=True, data={"url": str(getattr(page, "url", "") or ""), "count": len(rows), "entries": rows}
        )


def install_browser_parity(registry: Any) -> int:
    """Wrap click/type/open in place and add the two telemetry tools. Returns tools added."""
    getter = getattr(registry, "get", None)
    if not callable(getter):
        return 0
    for tool_name, action in (("browser.click", "click"), ("browser.type", "type")):
        inner = getter(tool_name)
        if inner is not None and not isinstance(inner, _Wrapped):
            registry.register(SensitiveSiteGuard(inner, action))
    opener = getter("browser.open")
    if opener is not None and not isinstance(opener, _Wrapped):
        registry.register(TelemetryOnOpen(opener))
    added = 0
    if opener is not None:
        for tool in (BrowserConsoleTool(), BrowserNetworkTool()):
            if getter(tool.name) is None:
                registry.register(tool)
                added += 1
    return added


__all__ = [
    "BrowserConsoleTool",
    "BrowserNetworkTool",
    "SensitiveSiteGuard",
    "TelemetryOnOpen",
    "attach_telemetry",
    "install_browser_parity",
    "telemetry_for",
]
