"""Compatibility helpers for model-emitted read-only tool calls."""

from __future__ import annotations

import json
import re
from typing import Any

TEXT_TOOLCALL_NAME_PATTERN = r"send_task|update_task|operate|web[._]search|web[._]fetch"
TEXT_TOOLCALL_START_RE = re.compile(
    r"(?:("
    + TEXT_TOOLCALL_NAME_PATTERN
    + r")\s*[\]}]?\s*[(\[{]|[\[{]\s*[\"']name[\"']\s*:\s*[\"']("
    + TEXT_TOOLCALL_NAME_PATTERN
    + r")[\"'])",
    re.I,
)
TEXT_TOOLCALL_NAMES = (
    "send_task",
    "update_task",
    "operate",
    "web.search",
    "web_search",
    "web.fetch",
    "web_fetch",
)
TEXT_TOOLCALL_ALIASES = {
    "web_search": "web.search",
    "web.search": "web.search",
    "web_fetch": "web.fetch",
    "web.fetch": "web.fetch",
}


def canonical_text_tool_name(name: str) -> str:
    """Normalize provider-style aliases while preserving unknown names."""
    normalized = str(name or "").strip().lower()
    return TEXT_TOOLCALL_ALIASES.get(normalized, normalized)


def safe_stream_prefix_len(buf: str) -> int:
    """Return the visible prefix while holding a possible text tool call."""
    low = buf.lower()
    n = len(buf)
    for marker in ("{", "["):
        index = low.rfind(marker, max(0, n - 40))
        if index >= 0:
            compact = re.sub(r"\s+", "", low[index:])
            for prefix in ('{"name"', "{'name'", '[{"name"', "[{'name'"):
                if prefix.startswith(compact):
                    return index
    for index in range(max(0, n - 24), n):
        segment = low[index:].lstrip("[")
        if segment == "":
            return index
        for name in TEXT_TOOLCALL_NAMES:
            if len(segment) == 1 and index > 0 and low[index - 1].isalnum():
                continue
            if name.startswith(segment) or segment.startswith(name):
                return index
    return n


def parse_text_toolcall(raw: str) -> tuple[str, dict[str, Any]] | None:
    """Parse literal or OpenAI-style JSON tool calls emitted as text."""
    match = TEXT_TOOLCALL_START_RE.search(raw or "")
    if not match:
        return None
    name = canonical_text_tool_name(match.group(1) or match.group(2) or "")
    args: dict[str, Any] = {}
    start = raw.find("{", match.start())
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return name, args
    try:
        parsed = json.loads(raw[start : end + 1])
        if isinstance(parsed, dict) and "name" in parsed:
            name = canonical_text_tool_name(str(parsed.get("name") or name))
            arguments = parsed.get("arguments", parsed.get("parameters", {}))
            if isinstance(arguments, str):
                arguments = json.loads(arguments or "{}")
            if isinstance(arguments, dict):
                args = arguments
        elif isinstance(parsed, dict):
            args = parsed
    except (json.JSONDecodeError, TypeError, ValueError):
        args = {}
    return name, args


__all__ = [
    "TEXT_TOOLCALL_START_RE",
    "canonical_text_tool_name",
    "parse_text_toolcall",
    "safe_stream_prefix_len",
]
