"""Utility helpers for local agent engine runtime behavior."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any


def env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 10_000) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return int(default)
    try:
        value = int(raw)
    except Exception:
        return int(default)
    return int(max(min_value, min(max_value, value)))


def env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return bool(default)
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def extract_topic_tokens(text: str) -> list[str]:
    if not text:
        return []
    tokens = re.findall(r"[a-zA-Z][a-zA-Z0-9_-]{4,}", str(text).lower())
    stop = {
        "about",
        "after",
        "again",
        "agent",
        "could",
        "every",
        "model",
        "please",
        "there",
        "their",
        "these",
        "those",
        "using",
        "which",
        "would",
    }
    return [tok for tok in tokens if tok not in stop][:200]


def parse_iso_utc(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
