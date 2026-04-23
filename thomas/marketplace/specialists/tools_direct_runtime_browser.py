"""Direct browser handlers for the tools specialist."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

from thomas.marketplace.orchestrator.protocol import CapabilityToken
from thomas.marketplace.specialists.tools_fast_path import (
    _DIRECT_URL_CLICK_AND_REPLY_RE,
    _DIRECT_URL_HEADLINE_RE,
    _DIRECT_URL_MAIN_TEXT_RE,
    _DIRECT_URL_TITLE_RE,
    _browser_action_open,
    _browser_click_in_session,
    _extract_strict_output,
    _normalize_requested_content,
    _normalize_requested_reply,
)

log = logging.getLogger(__name__)


async def handle_direct_runtime_browser(prompt: str, token: CapabilityToken) -> AsyncIterator[dict[str, Any]]:
    prompt_text = str(prompt or "").strip()
    if not prompt_text:
        return

    headline_match = _DIRECT_URL_HEADLINE_RE.search(prompt_text)
    if headline_match:
        if not token.permits_action("read"):
            yield {"type": "error", "error": "Permission denied: token does not permit reads"}
            return
        url = headline_match.group("url").strip()
        fetch_start = time.monotonic()
        yield {"type": "tool_start", "name": "direct.fetch_url", "id": "direct.fetch_url", "args": {"url": url}}
        try:
            from thomas.marketplace.specialists import tools as tools_mod

            headline = await tools_mod._fetch_browser_headline(url)
        except (OSError, RuntimeError, ValueError) as exc:
            elapsed = int((time.monotonic() - fetch_start) * 1000)
            yield {
                "type": "tool_result",
                "name": "direct.fetch_url",
                "id": "direct.fetch_url",
                "ok": False,
                "result": str(exc),
                "ms": elapsed,
            }
            log.debug("Direct headline fetch unavailable for %s; falling back to codex tools: %s", url, exc)
            return

        elapsed = int((time.monotonic() - fetch_start) * 1000)
        yield {
            "type": "tool_result",
            "name": "direct.fetch_url",
            "id": "direct.fetch_url",
            "ok": True,
            "result": headline,
            "ms": elapsed,
        }
        response = _extract_strict_output(prompt_text, headline, [headline]) or headline
        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1, "tool_calls": 1}
        return

    title_match = _DIRECT_URL_TITLE_RE.search(prompt_text)
    if title_match:
        if not token.permits_action("read"):
            yield {"type": "error", "error": "Permission denied: token does not permit reads"}
            return
        url = title_match.group("url").strip()
        fetch_start = time.monotonic()
        yield {"type": "tool_start", "name": "direct.fetch_url", "id": "direct.fetch_url", "args": {"url": url}}
        try:
            from thomas.marketplace.specialists import tools as tools_mod

            title = await tools_mod._fetch_browser_title(url)
        except (OSError, RuntimeError, ValueError) as exc:
            elapsed = int((time.monotonic() - fetch_start) * 1000)
            yield {
                "type": "tool_result",
                "name": "direct.fetch_url",
                "id": "direct.fetch_url",
                "ok": False,
                "result": str(exc),
                "ms": elapsed,
            }
            log.debug("Direct title fetch unavailable for %s; falling back to codex tools: %s", url, exc)
            return

        elapsed = int((time.monotonic() - fetch_start) * 1000)
        yield {
            "type": "tool_result",
            "name": "direct.fetch_url",
            "id": "direct.fetch_url",
            "ok": True,
            "result": title,
            "ms": elapsed,
        }
        response = _extract_strict_output(prompt_text, title, [title]) or title
        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1, "tool_calls": 1}
        return

    main_text_match = _DIRECT_URL_MAIN_TEXT_RE.search(prompt_text)
    if main_text_match:
        if not token.permits_action("read"):
            yield {"type": "error", "error": "Permission denied: token does not permit reads"}
            return
        url = main_text_match.group("url").strip()
        fetch_start = time.monotonic()
        yield {"type": "tool_start", "name": "direct.fetch_url", "id": "direct.fetch_url", "args": {"url": url}}
        try:
            from thomas.marketplace.specialists import tools as tools_mod

            main_text = await tools_mod._fetch_browser_main_text(url)
        except (OSError, RuntimeError, ValueError) as exc:
            elapsed = int((time.monotonic() - fetch_start) * 1000)
            yield {
                "type": "tool_result",
                "name": "direct.fetch_url",
                "id": "direct.fetch_url",
                "ok": False,
                "result": str(exc),
                "ms": elapsed,
            }
            log.debug("Direct main-text fetch unavailable for %s; falling back to codex tools: %s", url, exc)
            return

        elapsed = int((time.monotonic() - fetch_start) * 1000)
        yield {
            "type": "tool_result",
            "name": "direct.fetch_url",
            "id": "direct.fetch_url",
            "ok": True,
            "result": main_text,
            "ms": elapsed,
        }
        response = _extract_strict_output(prompt_text, main_text, [main_text]) or main_text
        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1, "tool_calls": 1}
        return

    click_match = _DIRECT_URL_CLICK_AND_REPLY_RE.search(prompt_text)
    if click_match:
        if not token.permits_action("execute"):
            yield {"type": "error", "error": "Permission denied: token does not permit execute actions"}
            return
        url = click_match.group("url").strip()
        label = _normalize_requested_content(click_match.group("label"))
        response_text = _normalize_requested_reply(click_match.group("response"))

        open_start = time.monotonic()
        yield {
            "type": "tool_start",
            "name": "direct.open_url",
            "id": "direct.open_url",
            "args": {"url": url},
        }
        try:
            open_result, action_session = await _browser_action_open(url, session_name="action-direct")
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            open_result = SimpleNamespace(ok=False, data=None, error=str(exc))
            action_session = "action-direct"
        open_elapsed = int((time.monotonic() - open_start) * 1000)
        open_ok = bool(getattr(open_result, "ok", False))
        yield {
            "type": "tool_result",
            "name": "direct.open_url",
            "id": "direct.open_url",
            "ok": open_ok,
            "result": str(getattr(open_result, "error", "") or getattr(open_result, "data", "") or ""),
            "ms": open_elapsed,
        }

        click_start = time.monotonic()
        yield {
            "type": "tool_start",
            "name": "direct.click",
            "id": "direct.click",
            "args": {"selector": label},
        }
        try:
            if not open_ok:
                raise RuntimeError(str(getattr(open_result, "error", "") or f"Failed to open {url}"))
            await _browser_click_in_session(label, session_name=action_session)
            click_ok = True
            click_result_text = response_text or "OK"
        except (OSError, RuntimeError, ValueError, TypeError) as exc:
            click_ok = False
            click_result_text = str(exc)
        click_elapsed = int((time.monotonic() - click_start) * 1000)
        yield {
            "type": "tool_result",
            "name": "direct.click",
            "id": "direct.click",
            "ok": click_ok,
            "result": click_result_text if click_ok else click_result_text,
            "ms": click_elapsed,
        }
        if not click_ok:
            log.debug("Direct click fast path unavailable for %s (%s); falling back to codex tools", url, click_result_text)
            return

        response = response_text or "OK"
        yield {"type": "text", "text": response}
        yield {"type": "done", "content": response, "iterations": 1, "tool_calls": 2}
        return
