"""An execution keeps the first ending recorded for it.

A delegated worker and its watchdog can both end the same execution: the worker completes, fails or sees your Stop,
and the watchdog times it out or records your Stop. Every ending used to be written with ``force=True``, so whichever
came second replaced the first: a task that had completed could be recorded as timed out, and one that had timed out
could be recorded as completed after it.

With ``keep_first_terminal=True`` (``fail_execution``, ``cancel_execution``, ``complete_execution`` and the
``update_execution`` they write through), a record that has already ended keeps its ending. The refused request is
noted on the record in ``late_terminal_requests`` (the newest 20), and the write returns the stored record with
``terminal_write_applied: False``, so the caller can announce the ending that was stored instead of its own. Callers
that do not pass it behave exactly as before.

Ported from refs/salvage/praxis-native-20260919/wt-native-scheduling (694a668b).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from thomas.core.task_bot_lock import _now, _read_json, _to_iso, _write_json

LATE_REQUESTS_KEPT = 20


def refused_ending(
    execution_id: str,
    repo_root: str | Path | None,
    payload: dict[str, Any],
    state: str,
    blocker: str | None,
    summary: str | None,
    actor: str,
) -> dict[str, Any]:
    """Keep *payload*'s ending, note this later request on it, and return the stored record marked refused.

    The caller holds the record's lock and read *payload* under it, so no other ending can land in between.
    """
    from thomas.core import task_bot_runtime  # imported here: the runtime imports this module

    late = list(payload.get("late_terminal_requests") or [])
    late.append(
        {
            "state": str(state or "").strip(),
            "blocker": str(blocker or "").strip(),
            "summary": str(summary or "").strip(),
            "actor": str(actor or "").strip(),
            "requested_at": _to_iso(_now()),
        }
    )
    payload["late_terminal_requests"] = late[-LATE_REQUESTS_KEPT:]
    read_revision = int(payload.get("revision") or 0)
    path = task_bot_runtime.execution_path(execution_id, repo_root)
    on_disk = _read_json(path, None)
    if isinstance(on_disk, dict) and int(on_disk.get("revision") or 0) != read_revision:
        raise task_bot_runtime.StaleExecutionError(
            f"execution `{execution_id}` changed on disk during update "
            f"(revision {read_revision} -> {on_disk.get('revision')}); re-read and retry"
        )
    payload["revision"] = read_revision + 1
    _write_json(path, payload)
    return {**payload, "terminal_write_applied": False}


def ending_was_refused(result: Any) -> bool:
    """True when a ``keep_first_terminal`` write found the execution already ended, and left it as it was."""
    return isinstance(result, dict) and result.get("terminal_write_applied") is False


__all__ = ["LATE_REQUESTS_KEPT", "ending_was_refused", "refused_ending"]
