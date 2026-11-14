"""One Thomas project's Build runs and hand-ins, read from its conversation and the cage (``praxis_timeline``)."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from scripts.praxis.timeline_sources import cid_epoch, iso_to_epoch, transcript_times
from scripts.praxis.timeline_state import PROJECT_QUIET_S, project_state

# How the message that started a run opens (thomas/server/routes/autopilot_messages.py, thomas_project.py).
KIND_RULES = [
    ("done_check", "Autopilot: continuing: done check"),
    ("repair_round", "Autopilot: continuing: repair round"),
    ("resume", "Autopilot: continuing: resuming after the usage limit"),
    ("resume", "Autopilot: continuing: resuming after provider trouble"),
    ("restart", "Autopilot: continuing: resuming after a restart"),
    ("steer", "Autopilot: continuing with your steering update"),
    ("continuation", "Autopilot: continuing"),
]
MANUAL_RESTART = re.compile(r"^Carry on with the task above\. Thomas's server restarted", re.I)
# The repair rounds the server starts by itself; any other round came through a send-back by a person.
AUTO_REPAIR_CAUSES = frozenset({"second_look_not_safe", "precard_check_failed", "dev_moved", "too_large"})
FAILURE_CLASSES = [
    ("completion_gate_blocked", "Completion gate blocked"),
    ("provider_overloaded", "Our servers are currently overloaded"),
    ("tool_loop_stability", "Tool loop stability"),
    ("pass_budget_exhausted", "Pass budget exhausted"),
    ("lost_connection", "Lost the connection"),
    ("gpt_answer_unusable", "GPT gave an answer"),
    ("stopped_for_steering", "stopped for your steering update"),
    ("stopped_by_you", "stopped by you"),
]
# A last run with no recorded end counts as still running while its transcript was written this recently.
RUNNING_QUIET_S = 900.0


def _dict(value: object) -> dict[str, Any]:
    """A Build team writes these files: a turn, hand-in or field of the wrong type is skipped, never raised on."""
    return value if isinstance(value, dict) else {}


def _dicts(value: object) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _epoch(value: object) -> float:
    """A time as seconds since the epoch; 0.0 for one that is missing or unreadable (it sorts and compares first)."""
    return iso_to_epoch(value) or 0.0


def classify(text: str, first: bool) -> tuple[str, str]:
    """(kind, source) of the user turn that started a run."""
    for kind, prefix in KIND_RULES:
        if text.startswith(prefix):
            return kind, "autopilot"
    if first:
        return "first_build", "launch"
    if MANUAL_RESTART.match(text):
        return "restart", "manual"
    return "manual_message", "manual"


def failure_class(run: dict[str, Any], reason: str) -> str:
    """Why a run did not end ok, from the agent turn's whole reason; "" for a run that did or is still going."""
    if run.get("ok"):
        return ""
    outcome = str(run.get("outcome") or "")
    if outcome == "running":
        return ""
    if outcome.startswith(("cut without", "ended without")):
        return "cut_without_a_turn"
    for name, needle in FAILURE_CLASSES:
        if needle in reason:
            return name
    return "other_failure" if outcome not in ("completed", "conversation") else ""


def repair_cause(rep: dict[str, Any]) -> str:
    """Why a repair round started: one the server starts itself, or a send-back by a person."""
    detail, why = str(rep.get("detail") or ""), str(rep.get("why") or "")
    if detail.startswith("A second model read your change"):
        return "second_look_not_safe"
    if detail.startswith("The check before your card"):
        return "precard_check_failed"
    if why in ("dev_moved", "too_large"):
        return why
    return "manual_send_back" + ("_after_hand_in" if rep.get("sid") else "")


def _new_run(turn: dict[str, Any], number: int, first: bool) -> dict[str, Any]:
    kind, source = classify(str(turn.get("text") or ""), first)
    return {
        "kind": kind,
        "source": source,
        "start": iso_to_epoch(turn.get("ts")),
        "end": None,
        "end_source": "",
        "outcome": "no agent turn recorded",
        "ok": None,
        "changed_files": None,
        "reason": "",
        "run_id": "",
        "turn_index": number,
    }


def _ended(run: dict[str, Any], turn: dict[str, Any], end: float, agent_dir: Path) -> None:
    reason, ok, files = str(turn.get("reason") or ""), turn.get("ok"), turn.get("changed_files")
    run.update(
        end=end,
        end_source="conversation agent turn ts",
        outcome=str(turn.get("outcome") or ""),
        ok=ok if isinstance(ok, bool) else None,
        changed_files=len(files) if isinstance(files, list) else 0,
        reason=re.sub(r"\s+", " ", reason)[:140],
        run_id=str(turn.get("run_id") or ""),
        _reason_full=reason,
    )
    times = transcript_times(agent_dir, run["run_id"])
    if times:
        run["transcript"] = {key: times[key] for key in ("file", "created", "modified", "size")}


def _unended(runs: list[dict[str, Any]], index: list | None, now: float) -> None:
    """A run with no agent turn ends at its transcript's last write, else at the next run's start, or is running."""
    for number, run in enumerate(runs):
        if run["end"] is not None:
            continue
        last = number == len(runs) - 1
        start = run["start"]
        following = None if last else runs[number + 1]["start"]
        match = next((row for row in index or () if start is not None and abs(row[0] - start) <= 3.0), None)
        if match is not None:
            run["transcript"] = {"file": match[3], "created": match[0], "modified": match[1], "size": match[2]}
            if last and now - match[1] <= RUNNING_QUIET_S:
                run.update(end_source="its transcript was still being written", outcome="running")
            else:
                run.update(
                    end=match[1],
                    end_source="transcript file last write (no agent turn was recorded)",
                    outcome="cut without a recorded turn (server restart or stop)",
                )
        elif following is not None:
            run.update(
                end=following,
                end_source="bounded by the next user turn (upper bound)",
                outcome="ended without a recorded turn (server restart or stop)",
            )
        elif last and start is not None and now - start <= RUNNING_QUIET_S:
            run.update(end_source="started within the quiet window", outcome="running")
        else:
            run["end_source"] = "not recorded"


def build_runs(turns: list[dict[str, Any]], agent_dir: Path, now: float, index: list | None = None) -> list[dict]:
    """Every Build run of a conversation: a user turn starts one, an agent turn with a readable time ends it."""
    runs: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    users = 0
    for number, turn in enumerate(turns if isinstance(turns, list) else []):
        if not isinstance(turn, dict):
            continue
        role = turn.get("role")
        if role == "user":
            if pending is not None:  # a run that never recorded its own turn
                runs.append(pending)
            pending = _new_run(turn, number, users == 0)
            users += 1
        elif role == "agent" and pending is not None:
            end = iso_to_epoch(turn.get("ts"))
            if end is not None:
                _ended(pending, turn, end, agent_dir)
                runs.append(pending)
                pending = None
    if pending is not None:
        runs.append(pending)
    _unended(runs, index, now)
    for run in runs:
        if run["start"] is not None and run["end"] is not None:
            run["duration_s"] = run["end"] - run["start"]
        elif run["outcome"] == "running" and run["start"] is not None:
            run["duration_s"] = now - run["start"]
        else:
            run["duration_s"] = None
        run["failure_class"] = failure_class(run, run.pop("_reason_full", ""))
    return runs


def _repair(rep: dict[str, Any]) -> dict[str, Any]:
    return {
        "round": rep.get("round"),
        "why": rep.get("why"),
        "cause": repair_cause(rep),
        "at": iso_to_epoch(rep.get("at")),
        "sid": str(rep.get("sid") or ""),
    }


def _hand_in(found: dict[str, Any], outbox: dict[str, dict], lookup: Callable[[str], dict | None]) -> dict[str, Any]:
    sid = str(found.get("sid") or "")
    record = _dict(outbox.get(sid))
    verdict, pending = _dict(record.get("verdict")), _dict(record.get("pending_times"))
    status = verdict.get("status")
    entry = {
        "sid": sid,
        "where": found.get("where"),
        "submitted_at": iso_to_epoch(found.get("submitted_at")),
        "dir_mtime": found.get("dir_mtime"),
        "pending_created": pending.get("created"),
        "pending_modified": pending.get("modified"),
        "verdict_status": status if isinstance(status, str) else None,
        "verdict_ts": iso_to_epoch(verdict.get("ts")),
        "card_code": str(_dict(verdict.get("card")).get("pairing_code") or ""),
        "commit_sha": str(verdict.get("commit_sha") or ""),
    }
    entry["commit"] = lookup(entry["commit_sha"]) if entry["commit_sha"] else None
    return entry


def _hand_ins_of(execution: str, hand_ins: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """One project's submissions, oldest first: by the execution id they record, or by their ``self-<id>`` name."""
    if not execution:
        return []
    own = re.compile(rf"self-{re.escape(execution)}(-\w+)?$")
    mine = [
        found
        for found in hand_ins.values()
        if isinstance(found, dict)
        and (found.get("execution_id") == execution or own.match(str(found.get("sid") or "")))
    ]
    return sorted(mine, key=lambda found: _epoch(found.get("submitted_at")))


def build_project(
    conversation: dict[str, Any],
    hand_ins: dict[str, dict[str, Any]],
    outbox: dict[str, dict[str, Any]],
    second_looks: dict[str, list[dict[str, Any]]],
    agent_dir: Path,
    now: float,
    index: list | None,
    commit_lookup: Callable[[str], dict | None],
) -> dict[str, Any]:
    """One project's row: launch, runs, repair rounds, second looks and hand-ins, before any phase is split."""
    cid = str(conversation.get("id") or "")
    project = _dict(conversation.get("thomas_project"))
    execution = str(project.get("execution_id") or "")
    launch = iso_to_epoch(conversation.get("created_at")) or cid_epoch(cid)
    row: dict[str, Any] = {
        "conversation_id": cid,
        "execution_id": execution,
        "pipeline": "ratchet" if execution.startswith("ratchet-") or project.get("ratchet") else "thomas_project",
        "title": str(conversation.get("title") or ""),
        "launch": {"epoch": launch, "source": "conversation created_at"} if launch is not None else None,
        "runs": build_runs(conversation.get("turns"), agent_dir, now, index),
        "repairs": [_repair(rep) for rep in _dicts(project.get("repairs"))],
        "settled_at": iso_to_epoch(project.get("settled_at")),
        "second_looks": [dict(session) for session in _dicts(second_looks.get(execution))],
        "hand_ins": [_hand_in(found, outbox, commit_lookup) for found in _hand_ins_of(execution, hand_ins)],
        "_launch_epoch": launch,
    }
    row["state"] = project_state(conversation, row["hand_ins"], now=now, runs=row["runs"])
    return row


__all__ = [
    "AUTO_REPAIR_CAUSES",
    "FAILURE_CLASSES",
    "KIND_RULES",
    "MANUAL_RESTART",
    "PROJECT_QUIET_S",
    "RUNNING_QUIET_S",
    "build_project",
    "build_runs",
    "classify",
    "failure_class",
    "project_state",
    "repair_cause",
]
