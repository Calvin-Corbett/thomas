"""Byte-safe transcript decoding and HTTP stream frame translation."""

from __future__ import annotations

import codecs
import json
from typing import Any


def line_to_sse_payload(line: str) -> dict[str, Any]:
    """Map one transcript line to a typed SSE payload when possible."""

    stripped = line.strip()
    if not stripped:
        return {}
    if stripped[0] == "{":
        try:
            obj = json.loads(stripped)
        except (json.JSONDecodeError, TypeError):
            obj = None
        if isinstance(obj, dict) and obj.get("fc"):
            payload: dict[str, Any] = {
                "type": "output",
                "kind": str(obj.get("fc")),
                "text": str(obj.get("text") or ""),
            }
            if obj.get("name"):
                payload["name"] = str(obj.get("name"))
            if obj.get("is_error"):
                payload["is_error"] = True
            if obj.get("delta"):
                payload["delta"] = True
            return payload
    return {"type": "output", "text": line}


class IncrementalLineDecoder:
    """Decode arbitrary UTF-8 chunks while retaining split chars and lines."""

    def __init__(self) -> None:
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._buffer = ""

    def feed(self, chunk: bytes) -> list[str]:
        if chunk:
            self._buffer += self._decoder.decode(chunk)
        *lines, self._buffer = self._buffer.split("\n")
        return lines

    def flush(self) -> list[str]:
        self._buffer += self._decoder.decode(b"", final=True)
        parts = self._buffer.split("\n")
        self._buffer = ""
        remainder = parts.pop() if parts else ""
        if remainder.strip():
            parts.append(remainder)
        return parts
