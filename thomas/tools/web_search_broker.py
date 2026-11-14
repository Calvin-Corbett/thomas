"""web.search and web.fetch for a Thomas behind the network fence: through the search broker.

A caged Thomas (scripts/cage/caged_server.py) reaches the internet only through
your egress proxy, which knows the model providers and no search engine. When
``THOMAS_SEARCH_BROKER`` is set, web.search and web.fetch ask the search broker
(scripts/cage/search_broker.py) instead: it runs as you, searches, and reads a
page only when that exact url came back as a search result. Without the variable
both tools work exactly as before.
"""

from __future__ import annotations

import asyncio
import os
import socket
import time
from typing import Any
from urllib.parse import urlsplit

import httpx

from thomas.tools.base import ToolResult

ENV_VAR = "THOMAS_SEARCH_BROKER"
# Reading a page may follow three redirects, each up to the broker's own timeouts.
_TIMEOUT_S = 60.0
# The promoter service starts a stopped broker again within a minute (promoter_service._BrokerKeeper).
BROKER_DOWN = (
    "Thomas's search broker is not answering, so this Thomas cannot search or read pages right now. "
    "The promoter service starts it again within a minute, or at your next sign-in."
)
# With the whole promoter gone, its egress proxy is gone too; the ThomasCageKeepalive
# task (scripts/cage/enable_cage_keepalive.ps1) starts it again within 15 minutes.
PROMOTER_DOWN = (
    "Thomas's promoter service, which runs its search broker and its network proxy, is not running, so this "
    "Thomas cannot search, read pages or reach its models right now. It restarts within 15 minutes or at your "
    "next sign-in."
)
FRESHNESS = (None, "pd", "pw", "pm", "py")
NOT_A_RESULT = (
    "web.fetch here reads only pages that came back from web.search: this Thomas runs behind a network "
    "fence, and its search broker reads a url only when a search in the last hour returned it, exactly as "
    "returned. {url} was not one of them. Search first with web.search, then fetch one of its result urls "
    "unchanged."
)


def broker_url() -> str:
    """The broker's base url when this Thomas is caged; empty otherwise."""
    return os.environ.get(ENV_VAR, "").strip().rstrip("/")


def _failed(error: str, start: float) -> ToolResult:
    return ToolResult(ok=False, data=None, error=error, duration_ms=(time.monotonic() - start) * 1000)


def _reason(answer: dict[str, Any]) -> str:
    detail = str(answer.get("detail") or "").strip()
    return str(answer.get("error") or "refused") + (f" ({detail})" if detail else "")


async def _ask(path: str, body: dict[str, Any]) -> dict[str, Any]:
    # Straight to loopback, never through the proxy the model clients use.
    async with httpx.AsyncClient(timeout=_TIMEOUT_S, trust_env=False) as client:
        resp = await client.post(broker_url() + path, json=body)
    try:
        answer = resp.json()
    except ValueError:
        answer = None
    return (
        answer if isinstance(answer, dict) else {"ok": False, "error": f"the broker answered HTTP {resp.status_code}"}
    )


def _proxy_refuses() -> bool:
    """Whether the loopback egress proxy (HTTPS_PROXY) refuses connections, i.e. the promoter itself is gone."""
    try:
        proxy = urlsplit(os.environ.get("HTTPS_PROXY", "").strip())
        host, port = proxy.hostname, proxy.port
    except ValueError:
        return False
    if host not in ("127.0.0.1", "localhost", "::1") or not port:
        return False
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return False
    except OSError:
        return True


async def _call(path: str, body: dict[str, Any], start: float) -> dict[str, Any] | ToolResult:
    try:
        return await _ask(path, body)
    except httpx.ConnectError:
        promoter_gone = await asyncio.to_thread(_proxy_refuses)
        return _failed(PROMOTER_DOWN if promoter_gone else BROKER_DOWN, start)
    except httpx.HTTPError as exc:
        return _failed(f"The search broker did not answer: {type(exc).__name__}: {exc}", start)


async def search(args: dict[str, Any]) -> ToolResult:
    """web.search through the broker, in web.search's own result shape."""
    start = time.monotonic()
    query = str(args.get("query") or "").strip()
    if not query:
        return _failed("Missing required parameter: query", start)
    try:
        count = max(1, min(10, int(args.get("count", 5))))
    except (TypeError, ValueError):
        count = 5
    freshness = str(args.get("freshness") or "").strip() or None
    if freshness not in FRESHNESS:
        return _failed("Invalid freshness. Allowed: pd, pw, pm, py.", start)
    body = {"query": query, "count": count, **({"freshness": freshness} if freshness else {})}
    answer = await _call("/search", body, start)
    if isinstance(answer, ToolResult):
        return answer
    if not answer.get("ok"):
        return _failed(f"Web search through the search broker failed: {_reason(answer)}", start)
    rows = [
        {
            "title": row.get("title"),
            "url": row.get("url"),
            "description": row.get("snippet") or "",
            "published_date": None,
        }
        for row in answer.get("results") or []
        if isinstance(row, dict)
    ]
    if not rows:
        return _failed(f"Web search found nothing for {query!r}.", start)
    data = {
        "provider": str(answer.get("provider") or "search_broker"),
        "query": query,
        "count": count,
        "results": rows,
        "meta": {"via": "search_broker", "cache_hit": False},
    }
    return ToolResult(ok=True, data=data, error=None, duration_ms=(time.monotonic() - start) * 1000)


async def fetch(args: dict[str, Any], *, max_chars: int) -> ToolResult:
    """web.fetch through the broker: a url a search returned, or a plain answer saying why not."""
    start = time.monotonic()
    url = str(args.get("url") or "").strip()
    if not url:
        return _failed("Missing required parameter: url", start)
    answer = await _call("/read", {"url": url}, start)
    if isinstance(answer, ToolResult):
        return answer
    if not answer.get("ok"):
        if answer.get("error") == "not a search result":
            return _failed(NOT_A_RESULT.format(url=url), start)
        return _failed(f"The search broker would not read {url}: {_reason(answer)}", start)
    data = {
        "url": str(answer.get("url") or url),
        "status_code": answer.get("status"),
        "content_type": answer.get("content_type"),
        "title": answer.get("title") or None,
        "text": str(answer.get("text") or "")[:max_chars].strip(),
        "via": "search_broker",
    }
    return ToolResult(ok=True, data=data, error=None, duration_ms=(time.monotonic() - start) * 1000)


__all__ = ["BROKER_DOWN", "ENV_VAR", "NOT_A_RESULT", "broker_url", "fetch", "search"]
