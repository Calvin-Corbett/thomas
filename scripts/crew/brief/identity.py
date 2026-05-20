#!/usr/bin/env python3
"""Shared agent identity resolution helpers for CLI coordination scripts."""

from __future__ import annotations

import os

AGENT_ID_ENV_KEYS: tuple[str, ...] = (
    "THOMAS_AGENT_ID",
    "AGENT_ID",
    "CODEX_AGENT_ID",
    "GEMINI_AGENT_ID",
    "CLAUDE_AGENT_ID",
)

AGENT_NAME_ENV_KEYS: tuple[str, ...] = (
    "THOMAS_AGENT_NAME",
    "CODEX_AGENT_NAME",
    "AGENT_NAME",
)


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def resolve_agent(
    explicit_agent: str | None,
    *,
    include_name_fallback: bool = True,
) -> str | None:
    """Resolve agent id/name from explicit argument, then env vars."""
    explicit = _clean(explicit_agent)
    if explicit:
        return explicit

    for key in AGENT_ID_ENV_KEYS:
        value = _clean(os.getenv(key))
        if value:
            return value

    if include_name_fallback:
        for key in AGENT_NAME_ENV_KEYS:
            value = _clean(os.getenv(key))
            if value:
                return value

    return None


def resolution_help(*, include_name_fallback: bool = True) -> str:
    keys = list(AGENT_ID_ENV_KEYS)
    if include_name_fallback:
        keys.extend(AGENT_NAME_ENV_KEYS)
    return "/".join(keys)
