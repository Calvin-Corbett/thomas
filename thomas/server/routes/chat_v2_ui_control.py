"""Shared Chat V2 stream headers.

Natural-language UI control interception was removed. Settings changes must
arrive through structured UI/API controls or a structured model capability.
"""

from __future__ import annotations

from aiohttp import web


def chat_stream_headers(request: web.Request) -> dict[str, str]:
    headers = {
        "Content-Type": "application/x-ndjson; charset=utf-8",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
        "X-Thomas-Chat-Engine": "v2",
    }
    if request.path == "/api/chat":
        headers.update({"Deprecation": "true", "Link": '</api/v2/chat>; rel="successor-version"'})
    return headers


_chat_stream_headers = chat_stream_headers

__all__ = ["_chat_stream_headers", "chat_stream_headers"]
