#!/usr/bin/env python3
"""Encoding for one workboard row's ``key=value; key=value`` fields.

Board rows are a single line of semicolon-separated pairs, so any semicolon or
backslash inside a value has to be escaped or the row stops parsing as itself --
and message summaries are free text written by agents, which is exactly where
those characters turn up.

These three are pure string functions: no board, no lock, no module state, and
nothing else in the package called them. Splitting them out is what let the
receipt work land without message.py growing past its monolith baseline, which
is the guard doing its job rather than being worked around.
"""

from __future__ import annotations


def _escape_field_value(value: str) -> str:
    return str(value or "").replace("\\", "\\\\").replace("\r", "\\r").replace("\n", "\\n").replace(";", "\\;")


def _unescape_field_value(value: str) -> str:
    out: list[str] = []
    escaped = False
    for char in str(value or ""):
        if escaped:
            if char == "n":
                out.append("\n")
            elif char == "r":
                out.append("\r")
            elif char in {";", "\\"}:
                out.append(char)
            else:
                out.append("\\")
                out.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        out.append(char)
    if escaped:
        out.append("\\")
    return "".join(out)


def _split_kv_parts(token: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    escaped = False
    for char in str(token or ""):
        if escaped:
            current.append("\\")
            current.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == ";":
            part = "".join(current).strip()
            if part:
                parts.append(part)
            current = []
            continue
        current.append(char)
    if escaped:
        current.append("\\")
    part = "".join(current).strip()
    if part:
        parts.append(part)
    return parts
