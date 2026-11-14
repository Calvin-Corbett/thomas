"""Time, scope and overlap arithmetic for presence -- the part with no I/O.

Split out of ``agent_presence`` on 2026-09-09, when adding a scope-hold window
pushed that module past its monolith baseline. Everything here is a pure
function of its arguments and the clock, which is what makes the presence gate's
decisions testable without a repository.

``agent_presence`` re-exports these under their original private names, so
``agent_presence._normalize_scope`` and friends keep resolving. They are moved,
not copied: this module's predecessor split added a new module without removing
the originals, the two drifted, and callers reaching the stale copies silently
skipped every check the new one had gained.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Any

DEFAULT_STALE_SECONDS = 120
DEFAULT_INFERRED_EXPIRY_SECONDS = 600
# How long a lapsed agent keeps its hold on the files it declared. Staleness above
# is a LIVENESS signal at two minutes -- an agent that pauses to think is stale --
# so it cannot also be the abandonment signal, or a three minute pause locks that
# agent's files against everyone for good. Past this window the hold expires and
# the row becomes advisory. Set to the repo's existing notion of "recent" rather
# than a new number invented for the occasion.
DEFAULT_SCOPE_HOLD_SECONDS = 1800


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds")


def _from_iso(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except Exception:
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def _env_int(name: str, default: int) -> int:
    raw = str(os.getenv(name, "")).strip()
    try:
        value = int(raw)
    except Exception:
        return default
    return value if value > 0 else default


def _dedupe(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        token = str(value or "").strip()
        if token and token not in seen:
            seen.add(token)
            out.append(token)
    return out


def _normalize_scope(scope: str | Sequence[str] | None) -> list[str]:
    if scope is None:
        return []
    parts = str(scope).split(",") if isinstance(scope, str) else [str(item or "") for item in scope]
    out: list[str] = []
    for raw in parts:
        token = str(raw or "").strip().replace("\\", "/")
        while token.startswith("./"):
            token = token[2:]
        while "//" in token:
            token = token.replace("//", "/")
        token = token.strip("/") or "."
        out.append(token)
    return _dedupe(out)


def _paths_overlap(a: str, b: str) -> bool:
    left = _normalize_scope([a])[0]
    right = _normalize_scope([b])[0]
    return left == right or left == "." or right == "." or left.startswith(f"{right}/") or right.startswith(f"{left}/")


def _is_coordination_surface(path: str) -> bool:
    """True for the files agents meet on, rather than the files they own.

    The board, the coordination dir and the message log are append-only surfaces
    that EVERY agent touches by design, and each already has its own concurrency
    discipline (claims, inbox acks, the task-manager seat). Counting one of them
    as exclusive scope makes the coordination layer the thing that deadlocks
    coordination: the second agent to reach a commit is refused because the first
    one is also holding the board, and neither can ever let go while working.

    Shape-based rather than a literal path, because every project scaffolds its
    own praxis root (``plans/<project>/WORKBOARD.md``).
    """
    token = _normalize_scope([path])[0]
    if token == "." or not token:
        return False
    if token.rsplit("/", 1)[-1] == "WORKBOARD.md":
        return True
    return token == "runtime/coordination" or token.startswith("runtime/coordination/")


def _row_idle_seconds(row: dict[str, Any]) -> float | None:
    """Seconds since this agent last showed any sign of life, or None if unknown."""
    for key in ("last_heartbeat_at", "last_activity_at"):
        seen = _from_iso(row.get(key))
        if seen is not None:
            return max(0.0, (_now() - seen).total_seconds())
    return None


def _hold_expired(row: dict[str, Any]) -> bool:
    """True once a lapsed agent has been silent longer than the scope-hold window."""
    idle = _row_idle_seconds(row)
    if idle is None:
        return False  # nothing measured; do not take a hold away on a guess
    return idle > _env_int("THOMAS_AGENT_PRESENCE_SCOPE_HOLD_SECONDS", DEFAULT_SCOPE_HOLD_SECONDS)


def _gate_message(
    conflicts: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    not_live: list[dict[str, Any]],
    needs_override: bool,
) -> str:
    counts = []
    if conflicts:
        counts.append(f"{len(conflicts)} conflict(s)")
    if warnings:
        counts.append(f"{len(warnings)} warning(s)")
    if not_live:
        counts.append(f"{len(not_live)} not live: " + ", ".join(str(item["agent_id"]) for item in not_live))
    detail = [
        str(item.get("message") or "")
        for item in [*conflicts[:2], *warnings[:2]]
        if str(item.get("message") or "").strip()
    ]
    if needs_override:
        message = "presence gate requires override: " + ", ".join(counts)
    elif warnings or not_live:
        message = "presence gate passed with " + ", ".join(counts)
    else:
        message = ""
    if message and detail:
        message += ". " + " ".join(detail)
    return message


def _owned_scope(scope: Sequence[str]) -> list[str]:
    return [token for token in scope if not _is_coordination_surface(token)]


def _scope_overlaps(left: Sequence[str], right: Sequence[str]) -> bool:
    return any(_paths_overlap(a, b) for a in left for b in right)


def _scope_sample(left: Sequence[str], right: Sequence[str]) -> list[str]:
    sample: list[str] = []
    for a in left:
        for b in right:
            if _paths_overlap(a, b):
                sample.append(a if len(a) <= len(b) else b)
    return _dedupe(sample)[:5]
