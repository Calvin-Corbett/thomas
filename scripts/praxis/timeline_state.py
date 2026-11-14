"""Where a Thomas project stands, landed, ended or open, read from its conversation and hand-ins (``praxis_timeline``).

Split from ``timeline_runs``. A project is followed to its landing, to its last event once it has ended, and to the
extraction time only while it is open, so calling a stopped project open puts every hour since it stopped into
``open_now`` and makes it look like it is still being built. The server ends a project after an hour of quiet
(``thomas_project_quiet.settle_quiet``); this is the same rule, read from what is on disk and not from a running server.
"""

from __future__ import annotations

from typing import Any

from scripts.praxis.timeline_sources import iso_to_epoch

# thomas_project_quiet.QUIET_MAX_S, copied rather than imported so the timeline loads no server code;
# tests/test_the_timeline_reports_what_it_cannot_read.py keeps the two equal.
PROJECT_QUIET_S = 3600.0
FINAL_VERDICTS = frozenset({"declined", "refused", "error", "withdrawn"})


def _dict(value: object) -> dict[str, Any]:
    """A Build team writes the conversation: a field of the wrong type is skipped, never raised on."""
    return value if isinstance(value, dict) else {}


def _dicts(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _epoch(value: object) -> float:
    """A time as seconds since the epoch; 0.0 for one that is missing or unreadable (it sorts and compares first)."""
    return iso_to_epoch(value) or 0.0


def _is_final(hand_in: dict[str, Any]) -> bool:
    status = hand_in.get("verdict_status")
    return isinstance(status, str) and status in FINAL_VERDICTS


def _quiet(conversation: dict[str, Any], now: float) -> bool:
    """Last written more than an hour before *now*; false for a conversation whose ``updated_at`` cannot be read."""
    written = iso_to_epoch(conversation.get("updated_at"))
    return written is not None and now - written > PROJECT_QUIET_S


def _waiting(conversation: dict[str, Any], hand_ins: list[dict[str, Any]], now: float, runs: list | None) -> bool:
    """True while something will still move the project: a hand-in with no final verdict, a run, a usage-limit pause."""
    if any(hand_in.get("where") != "withdrawn" and not _is_final(hand_in) for hand_in in hand_ins):
        return True  # in the inbox, held by the promoter, or processed with no verdict written
    if any(isinstance(run, dict) and run.get("outcome") == "running" for run in runs or ()):
        return True
    parked = _dict(conversation.get("autopilot")).get("parked_until")  # autopilot_park.park: Unix seconds
    return isinstance(parked, (int, float)) and not isinstance(parked, bool) and parked > now


def project_state(
    conversation: dict[str, Any], hand_ins: list[dict[str, Any]], *, now: float | None = None, runs: list | None = None
) -> str:
    """landed; ended; or open.

    Ended is a retirement, a final verdict no repair round followed, or, when *now* is given, a conversation last
    written more than :data:`PROJECT_QUIET_S` before it with nothing waiting (*runs* are the project's Build runs). The
    verdict rules come first. A conversation whose ``updated_at`` cannot be read is never called quiet.
    """
    rows = [hand_in for hand_in in hand_ins if isinstance(hand_in, dict)]
    if any(hand_in.get("verdict_status") == "landed" for hand_in in rows):
        return "landed"
    project = _dict(conversation.get("thomas_project"))
    if project.get("retirement"):
        return "ended"
    last = max(rows, key=lambda hand_in: _epoch(hand_in.get("submitted_at")), default=None)
    if last is not None and _is_final(last):
        verdict_at = _epoch(last.get("verdict_ts")) or _epoch(last.get("submitted_at"))
        rounds = [iso_to_epoch(rep.get("at")) for rep in _dicts(project.get("repairs"))]
        if not any(at is not None and at > verdict_at for at in rounds):
            return "ended"
    if now is not None and _quiet(conversation, now) and not _waiting(conversation, rows, now, runs):
        return "ended"
    return "open"


__all__ = ["FINAL_VERDICTS", "PROJECT_QUIET_S", "project_state"]
