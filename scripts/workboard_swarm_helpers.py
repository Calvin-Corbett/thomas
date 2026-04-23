#!/usr/bin/env python3
"""Shared helpers for workboard swarm commands."""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SWARM_STATES = {"planned", "active", "completed", "cancelled"}
PRIORITIES = {"p0", "p1", "p2"}
ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
DEFAULT_COORDINATOR = "thomas"


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _sanitize(label: str, value: str) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{label} is required")
    if ";" in cleaned or "\n" in cleaned or "\r" in cleaned:
        raise ValueError(f"{label} cannot include ';' or newline characters")
    return cleaned


def _validate_priority(priority: str) -> str:
    normalized = _norm(priority)
    if normalized not in PRIORITIES:
        allowed = ", ".join(sorted(PRIORITIES))
        raise ValueError(f"priority must be one of: {allowed}")
    return normalized


def _validate_state(state: str) -> str:
    normalized = _norm(state)
    if normalized not in SWARM_STATES:
        allowed = ", ".join(sorted(SWARM_STATES))
        raise ValueError(f"state must be one of: {allowed}")
    return normalized


def _split_agents(raw: str) -> list[str]:
    rows: list[str] = []
    for token in str(raw or "").split(","):
        clean = str(token or "").strip()
        if clean:
            rows.append(clean)
    return rows


def _load_explicit_scopes(raw: str, scopes_file: str) -> list[str]:
    rows = _split_agents(raw)
    file_value = str(scopes_file or "").strip()
    if file_value:
        path = Path(file_value).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        if not path.exists():
            raise ValueError(f"scopes file does not exist: {path}")
        for line in path.read_text(encoding="utf-8").splitlines():
            clean = line.strip()
            if clean and not clean.startswith("#"):
                rows.append(clean)
    return rows


def _format_agents(values: Sequence[str]) -> str:
    deduped: list[str] = []
    seen: set[str] = set()
    for item in values:
        clean = str(item or "").strip()
        key = _norm(clean)
        if not clean or key in seen:
            continue
        _sanitize("agent", clean)
        seen.add(key)
        deduped.append(clean)
    return ",".join(deduped) if deduped else "none"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _norm(value)).strip("-") or "agent"


def _ps_single_quote(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _parse_env_assignments(values: Sequence[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        if "=" not in text:
            raise ValueError(f"env assignment must use KEY=VALUE: {text}")
        key, value = text.split("=", 1)
        clean_key = key.strip()
        if not ENV_KEY_RE.match(clean_key):
            raise ValueError(f"invalid env key: {clean_key}")
        if "\n" in value or "\r" in value:
            raise ValueError(f"env value for {clean_key} cannot include newlines")
        env[clean_key] = value
    return env
