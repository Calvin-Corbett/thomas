from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

TERMINAL_STATES = {"done", "failed", "cancelled"}
COMPLETION_WEBHOOK_KEY = "job_completion"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _safe_string(value: Any) -> str:
    return str(value or "").strip()


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except ImportError:
        return default


def _normalize_tags(value: Any) -> list[str]:
    if value is None:
        return []
    raw_items: list[Any]
    if isinstance(value, str):
        raw_items = [part.strip() for part in value.split(",")]
    elif isinstance(value, (list, tuple, set)):
        raw_items = list(value)
    else:
        raw_items = [value]
    output: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        tag = _safe_string(item)
        key = tag.lower()
        if not tag or key in seen:
            continue
        seen.add(key)
        output.append(tag)
    return output
