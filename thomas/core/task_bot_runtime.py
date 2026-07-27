from __future__ import annotations

import json
import re
import secrets
import time
from contextlib import suppress
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
STATE_DIRNAME = "task_bots"
SUMMARY_FILENAME = "executions-summary.json"
DEFAULT_STALE_MINUTES = 5.0
# "cancelled" is its own ending. Stopping a run on purpose is not a failure,
# and filing it as one made every deliberate Stop look identical to a crash
# in the task list -- with a failed proof beside it.
TERMINAL_STATES = {"failed", "completed", "abandoned", "cancelled"}
VALID_STATES = {
    "requested",
    "classified",
    "queued",
    "claimed",
    "executing",
    "blocked",
    "awaiting_proof",
    "verified",
    "failed",
    "completed",
    "abandoned",
    "cancelled",
}
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "requested": {"classified", "queued", "failed", "abandoned", "cancelled"},
    "classified": {"queued", "failed", "abandoned", "cancelled"},
    "queued": {"claimed", "blocked", "failed", "abandoned", "cancelled"},
    "claimed": {"executing", "blocked", "failed", "abandoned", "cancelled"},
    "executing": {"blocked", "awaiting_proof", "failed", "abandoned", "cancelled"},
    "blocked": {"queued", "claimed", "executing", "failed", "abandoned", "cancelled"},
    "awaiting_proof": {"verified", "failed", "blocked", "abandoned", "cancelled"},
    "verified": {"completed", "failed", "abandoned", "cancelled"},
    "failed": set(),
    "completed": set(),
    "abandoned": set(),
    "cancelled": set(),
}


@dataclass(frozen=True)
class RuntimeTransition:
    state: str
    summary: str
    proof_status: str
    blocker: str
    actor: str
    occurred_at: str


def coordination_dir(repo_root: str | Path | None = None) -> Path:
    root = (Path(repo_root).expanduser() if repo_root is not None else ROOT).resolve()
    return root / "runtime" / "coordination"


def runtime_dir(repo_root: str | Path | None = None) -> Path:
    return coordination_dir(repo_root) / STATE_DIRNAME


def summary_path(repo_root: str | Path | None = None) -> Path:
    return runtime_dir(repo_root) / SUMMARY_FILENAME


def execution_path(execution_id: str, repo_root: str | Path | None = None) -> Path:
    return runtime_dir(repo_root) / f"{str(execution_id or '').strip()}.json"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _from_iso(value: str | None) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    last_error: Exception | None = None
    for attempt in range(6):
        tmp = path.with_suffix(f"{path.suffix}.{secrets.token_hex(4)}.tmp")
        try:
            tmp.write_text(serialized, encoding="utf-8")
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            with suppress(Exception):
                tmp.unlink(missing_ok=True)
            time.sleep(0.02 * (attempt + 1))
        except Exception:
            with suppress(Exception):
                tmp.unlink(missing_ok=True)
            raise
    if last_error is not None:
        raise last_error


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _normalize_state(value: str | None, *, default: str = "requested") -> str:
    state = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "review": "awaiting_proof",
        "done": "completed",
        "in_progress": "executing",
        "active": "executing",
    }
    state = aliases.get(state, state)
    return state if state in VALID_STATES else default


def _normalize_proof_status(value: str | None) -> str:
    raw = str(value or "").strip().lower().replace("-", "_")
    aliases = {
        "none": "missing",
        "pending": "pending",
        "awaiting": "pending",
        "missing": "missing",
        "verified": "verified",
        "attached": "attached",
        "failed": "failed",
    }
    return aliases.get(raw, raw or "missing")


def _transition_entry(
    *,
    state: str,
    summary: str,
    proof_status: str,
    blocker: str,
    actor: str,
    occurred_at: str,
) -> dict[str, str]:
    row = RuntimeTransition(
        state=state,
        summary=str(summary or "").strip(),
        proof_status=_normalize_proof_status(proof_status),
        blocker=str(blocker or "").strip(),
        actor=str(actor or "").strip(),
        occurred_at=occurred_at,
    )
    return {
        "state": row.state,
        "summary": row.summary,
        "proof_status": row.proof_status,
        "blocker": row.blocker,
        "actor": row.actor,
        "occurred_at": row.occurred_at,
    }


def _empty_proof() -> dict[str, Any]:
    return {
        "status": "missing",
        "artifacts": [],
        "verified_at": "",
        "updated_at": "",
        "summary": "",
    }


def _new_record(
    *,
    execution_id: str,
    task_id: str,
    session_id: str,
    summary: str,
    intent: str,
    scope: list[str],
    visibility: str,
    parent_execution_id: str,
    bot_id: str,
    backend_type: str,
    actor: str,
    created_at: str,
    runtime_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "execution_id": execution_id,
        "task_id": task_id,
        "parent_execution_id": parent_execution_id,
        "conversation_id": session_id,
        "thread_id": session_id,
        "summary": str(summary or "").strip(),
        "execution_intent": str(intent or "").strip() or "task",
        "visibility": str(visibility or "").strip() or "background",
        "backend_type": str(backend_type or "").strip() or "task_manager",
        "runtime_profile": dict(runtime_profile or {}),
        "bot_id": str(bot_id or "").strip(),
        "scope": list(scope),
        "claimed_owner": "",
        "state": "requested",
        "progress_summary": str(summary or "").strip(),
        "proof_status": "missing",
        "blocker": "",
        "created_at": created_at,
        "updated_at": created_at,
        "last_heartbeat_at": created_at,
        "completed_at": "",
        "failed_at": "",
        "abandoned_at": "",
        # In-flight steerability: a follow-up message can queue new instructions for
        # a RUNNING background task (the worker drains them between steps), or request
        # cancellation. Previously a dispatched task could not be edited or stopped.
        "pending_instructions": [],
        "cancel_requested": False,
        "proof": _empty_proof(),
        "transitions": [
            _transition_entry(
                state="requested",
                summary=str(summary or "").strip(),
                proof_status="missing",
                blocker="",
                actor=actor,
                occurred_at=created_at,
            )
        ],
    }


def _summary_row(record: dict[str, Any], *, stale_after_minutes: float) -> dict[str, Any]:
    now = _now()
    state = str(record.get("state") or "")
    # Liveness = the freshest sign of life. Heartbeat is best, but tasks that were
    # never claimed (stuck in queued/requested) have NO heartbeat — fall back to
    # updated_at then created_at so an orphaned task that no agent ever picked up
    # still ages into "stale" instead of lingering as "active" forever. This is the
    # "no agent has been there for a while" detection.
    liveness = (
        _from_iso(str(record.get("last_heartbeat_at") or ""))
        or _from_iso(str(record.get("updated_at") or ""))
        or _from_iso(str(record.get("created_at") or ""))
    )
    stale = False
    if state not in TERMINAL_STATES and liveness is not None and float(stale_after_minutes) > 0:
        stale = now - liveness > timedelta(minutes=float(stale_after_minutes))
    return {
        "execution_id": str(record.get("execution_id") or ""),
        "task_id": str(record.get("task_id") or ""),
        "parent_execution_id": str(record.get("parent_execution_id") or ""),
        "conversation_id": str(record.get("conversation_id") or ""),
        "bot_id": str(record.get("bot_id") or ""),
        "visibility": str(record.get("visibility") or ""),
        "backend_type": str(record.get("backend_type") or "task_manager"),
        "state": str(record.get("state") or ""),
        "claimed_owner": str(record.get("claimed_owner") or ""),
        "scope": list(record.get("scope") or []),
        "progress_summary": str(record.get("progress_summary") or ""),
        "proof_status": str(record.get("proof_status") or ""),
        "blocker": str(record.get("blocker") or ""),
        "reported_to_chat_at": str(record.get("reported_to_chat_at") or ""),
        "created_at": str(record.get("created_at") or ""),
        "updated_at": str(record.get("updated_at") or ""),
        "last_heartbeat_at": str(record.get("last_heartbeat_at") or ""),
        "completed_at": str(record.get("completed_at") or ""),
        "runtime_profile": dict(record.get("runtime_profile") or {}),
        "stale": bool(stale),
    }


def _write_summary(
    repo_root: str | Path | None = None, *, stale_after_minutes: float = DEFAULT_STALE_MINUTES
) -> dict[str, Any]:
    root = runtime_dir(repo_root)
    rows: list[dict[str, Any]] = []
    if root.exists():
        for path in sorted(root.glob("*.json")):
            if path.name == SUMMARY_FILENAME:
                continue
            payload = _read_json(path, None)
            if not isinstance(payload, dict):
                continue
            rows.append(_summary_row(payload, stale_after_minutes=stale_after_minutes))
    rows.sort(key=lambda item: (str(item.get("updated_at") or ""), str(item.get("execution_id") or "")), reverse=True)
    summary = {
        "generated_at": _to_iso(_now()),
        "execution_count": len(rows),
        "active_count": sum(
            1 for row in rows if str(row.get("state") or "") not in TERMINAL_STATES and not bool(row.get("stale"))
        ),
        "stale_count": sum(1 for row in rows if bool(row.get("stale"))),
        "blocked_count": sum(1 for row in rows if str(row.get("state") or "") == "blocked"),
        "awaiting_proof_count": sum(1 for row in rows if str(row.get("state") or "") == "awaiting_proof"),
        "executions": rows,
    }
    _write_json(summary_path(repo_root), summary)
    return summary


def read_summary(
    repo_root: str | Path | None = None, *, refresh: bool = True, stale_after_minutes: float = DEFAULT_STALE_MINUTES
) -> dict[str, Any]:
    if refresh:
        return _write_summary(repo_root, stale_after_minutes=stale_after_minutes)
    payload = _read_json(summary_path(repo_root), {})
    return payload if isinstance(payload, dict) else {}


def list_executions(
    repo_root: str | Path | None = None, *, refresh: bool = True, stale_after_minutes: float = DEFAULT_STALE_MINUTES
) -> list[dict[str, Any]]:
    payload = read_summary(repo_root, refresh=refresh, stale_after_minutes=stale_after_minutes)
    rows = payload.get("executions")
    return list(rows) if isinstance(rows, list) else []


def get_execution(execution_id: str, repo_root: str | Path | None = None) -> dict[str, Any] | None:
    payload = _read_json(execution_path(execution_id, repo_root), None)
    return payload if isinstance(payload, dict) else None


def find_by_task_id(task_id: str, repo_root: str | Path | None = None) -> dict[str, Any] | None:
    task_key = str(task_id or "").strip()
    if not task_key:
        return None
    for row in list_executions(repo_root, refresh=True):
        if str(row.get("task_id") or "").strip() != task_key:
            continue
        full = get_execution(str(row.get("execution_id") or ""), repo_root)
        if full is not None:
            return full
    return None


def create_execution(
    *,
    session_id: str,
    summary: str,
    task_id: str = "",
    intent: str = "task",
    scope: list[str] | None = None,
    visibility: str = "background",
    parent_execution_id: str = "",
    bot_id: str = "",
    backend_type: str = "task_manager",
    runtime_profile: dict[str, Any] | None = None,
    actor: str = "task-manager",
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    execution_id = f"exec-{secrets.token_hex(6)}"
    created_at = _to_iso(_now())
    payload = _new_record(
        execution_id=execution_id,
        task_id=str(task_id or "").strip(),
        session_id=str(session_id or "").strip(),
        summary=str(summary or "").strip(),
        intent=intent,
        scope=[str(item).strip() for item in list(scope or []) if str(item).strip()],
        visibility=visibility,
        parent_execution_id=str(parent_execution_id or "").strip(),
        bot_id=bot_id,
        backend_type=backend_type,
        actor=str(actor or "").strip(),
        created_at=created_at,
        runtime_profile=runtime_profile,
    )
    _write_json(execution_path(execution_id, repo_root), payload)
    _write_summary(repo_root)
    return payload


def _validate_transition(current: str, new_state: str, *, allow_same: bool) -> None:
    if new_state not in VALID_STATES:
        raise ValueError(f"invalid runtime state `{new_state}`")
    if allow_same and current == new_state:
        return
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new_state != current and new_state not in allowed:
        raise ValueError(f"invalid runtime transition `{current}` -> `{new_state}`")


# The worker's structured stop protocol -- the GIVE_UP marker and its
# what_failed / what_was_tried / why_blocked fields -- is control traffic
# between the agent and the engine. It reached the chat thread verbatim, so
# someone who asked for a one-page 401k guide for their employees was told
# "why_blocked: The workspace does not contain scripts/forge/gates/
# monolith_guard.py, and the available tools provide file operations only".
# The human sentence in front of it is kept; the protocol is not shown.
# Matched by SHAPE, not by the words alone. The protocol emits either the bare
# marker on its own line or a labelled "field:" -- so a summary that merely
# mentions one of these words keeps its sentence. Matching the bare token
# anywhere turned "Added a give_up flag to the retry loop" into "Added a".
_WORKER_PROTOCOL_RE = re.compile(
    r"^[ \t]*GIVE_UP\b[ \t]*:?[ \t]*$"  # the bare marker, alone on its line
    r"|\bGIVE_UP[ \t]*:"  # or labelled, which is unambiguous anywhere
    r"|\b(?:what_failed|what_was_tried|why_blocked)[ \t]*:",
    re.IGNORECASE | re.MULTILINE,
)


def _user_facing_summary(text: str) -> str:
    """The part of a worker summary that is addressed to a person."""
    match = _WORKER_PROTOCOL_RE.search(text)
    if match is None:
        return text
    return text[: match.start()].strip(" .;:-\n\t")


def update_execution(
    execution_id: str,
    *,
    state: str | None = None,
    task_id: str | None = None,
    claimed_owner: str | None = None,
    scope: list[str] | None = None,
    progress_summary: str | None = None,
    blocker: str | None = None,
    proof_status: str | None = None,
    salvaged_artifacts: list[str] | None = None,
    reported_to_chat_at: str | None = None,
    bot_id: str | None = None,
    backend_type: str | None = None,
    runtime_profile: dict[str, Any] | None = None,
    visibility: str | None = None,
    heartbeat: bool = False,
    actor: str = "",
    repo_root: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    payload = get_execution(execution_id, repo_root)
    if payload is None:
        raise FileNotFoundError(f"execution `{execution_id}` not found")

    now_iso = _to_iso(_now())
    current_state = _normalize_state(str(payload.get("state") or ""), default="requested")
    next_state = _normalize_state(state, default=current_state) if state is not None else current_state
    if force:
        if next_state not in VALID_STATES:
            raise ValueError(f"invalid runtime state `{next_state}`")
    else:
        _validate_transition(current_state, next_state, allow_same=True)

    if task_id is not None:
        payload["task_id"] = str(task_id or "").strip()
    if claimed_owner is not None:
        payload["claimed_owner"] = str(claimed_owner or "").strip()
    if scope is not None:
        payload["scope"] = [str(item).strip() for item in scope if str(item).strip()]
    if progress_summary is not None:
        raw_summary = str(progress_summary or "").strip()
        shown = _user_facing_summary(raw_summary)
        # Keep the whole thing when there is no human sentence to show, rather
        # than replacing a diagnosis with silence; and keep the original beside
        # it either way so nothing is lost for debugging.
        payload["progress_summary"] = shown or raw_summary
        if shown and shown != raw_summary:
            payload["progress_detail"] = raw_summary
    if salvaged_artifacts is not None:
        # Files that exist in the workspace of a run that did NOT succeed.
        # Deliberately not written as proof: a proof means "this is the verified
        # answer", and these are only "this is what was on disk when it stopped".
        # Kept in their own field so a failed run can show its work without any
        # path that reads proof mistaking it for a completed deliverable.
        payload["salvaged_artifacts"] = [
            str(item).strip() for item in salvaged_artifacts if str(item or "").strip()
        ]
    if blocker is not None:
        payload["blocker"] = str(blocker or "").strip()
    if reported_to_chat_at is not None:
        # Durable "this completion was already announced in chat" marker, so a
        # finished task is not re-announced after a server restart (replaces the
        # old process-local in-memory dedup set in the orchestrator brain).
        payload["reported_to_chat_at"] = str(reported_to_chat_at or "").strip()
    if bot_id is not None:
        payload["bot_id"] = str(bot_id or "").strip()
    if backend_type is not None:
        payload["backend_type"] = str(backend_type or "").strip() or "task_manager"
    if runtime_profile is not None:
        payload["runtime_profile"] = dict(runtime_profile)
    if visibility is not None:
        payload["visibility"] = str(visibility or "").strip() or "background"

    normalized_proof_status = _normalize_proof_status(
        proof_status if proof_status is not None else str(payload.get("proof_status") or "missing")
    )
    payload["state"] = next_state
    payload["proof_status"] = normalized_proof_status
    payload["updated_at"] = now_iso
    transitioned = next_state != current_state
    # A pure "mark reported" write (only reported_to_chat_at; no state/progress/heartbeat/
    # transition) is chat-side bookkeeping, NOT worker liveness — it must not refresh the
    # staleness clock on a finished/verified row. EVERY other non-terminal update — including
    # the worker's own progress writes (progress_summary set, no state) — IS a sign of life
    # and refreshes the heartbeat, so an actively-building worker never goes falsely stale
    # and vanishes from Mission Control.
    pure_reported_write = (
        reported_to_chat_at is not None
        and state is None
        and progress_summary is None
        and not heartbeat
        and not transitioned
    )
    if (heartbeat or next_state not in TERMINAL_STATES) and not pure_reported_write:
        payload["last_heartbeat_at"] = now_iso
    # Stamp terminal timestamps only on an ACTUAL transition into that state — never on a
    # post-completion metadata write (which would falsify completed_at / frozen-elapsed).
    if next_state == "completed" and transitioned:
        payload["completed_at"] = now_iso
    if next_state == "failed" and transitioned:
        payload["failed_at"] = now_iso
    if next_state == "abandoned" and transitioned:
        payload["abandoned_at"] = now_iso

    transitions = list(payload.get("transitions") or [])
    last = transitions[-1] if transitions else {}
    last_state = str(last.get("state") or "")
    last_summary = str(last.get("summary") or "")
    last_proof = str(last.get("proof_status") or "")
    last_blocker = str(last.get("blocker") or "")
    current_summary = str(payload.get("progress_summary") or "")
    current_blocker = str(payload.get("blocker") or "")
    actor_clean = str(actor or claimed_owner or payload.get("claimed_owner") or "").strip()
    if (
        next_state != last_state
        or current_summary != last_summary
        or normalized_proof_status != last_proof
        or current_blocker != last_blocker
        or heartbeat
    ):
        transitions.append(
            _transition_entry(
                state=next_state,
                summary=current_summary,
                proof_status=normalized_proof_status,
                blocker=current_blocker,
                actor=actor_clean,
                occurred_at=now_iso,
            )
        )
    payload["transitions"] = transitions[-50:]
    _write_json(execution_path(execution_id, repo_root), payload)
    _write_summary(repo_root)
    return payload


def sync_task_state(
    *,
    task_id: str,
    workboard_status: str,
    actor: str = "",
    summary: str = "",
    blocker: str = "",
    claimed_owner: str | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any] | None:
    payload = find_by_task_id(task_id, repo_root)
    if payload is None:
        return None
    mapped = {
        "queued": "queued",
        "claimed": "claimed",
        "in_progress": "executing",
        "review": "awaiting_proof",
        "done": "completed" if str(payload.get("proof_status") or "") == "verified" else "verified",
        "blocked": "blocked",
    }.get(str(workboard_status or "").strip().lower())
    if not mapped:
        return payload
    proof_status = None
    if mapped == "awaiting_proof" and str(payload.get("proof_status") or "") in {"", "missing"}:
        proof_status = "pending"
    if mapped in {"verified", "completed"} and str(payload.get("proof_status") or "") in {"", "missing", "pending"}:
        proof_status = "attached"
    return update_execution(
        str(payload.get("execution_id") or ""),
        state=mapped,
        claimed_owner=claimed_owner,
        progress_summary=summary or str(payload.get("progress_summary") or task_id),
        blocker=blocker if mapped == "blocked" else "",
        proof_status=proof_status,
        heartbeat=True,
        actor=actor,
        repo_root=repo_root,
        force=True,
    )


def attach_proof(
    execution_id: str,
    *,
    artifacts: list[dict[str, Any]] | None = None,
    summary: str = "",
    status: str = "attached",
    actor: str = "",
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    payload = get_execution(execution_id, repo_root)
    if payload is None:
        raise FileNotFoundError(f"execution `{execution_id}` not found")
    proof = deepcopy(payload.get("proof") or _empty_proof())
    proof["artifacts"] = list(artifacts or [])
    proof["summary"] = str(summary or "").strip()
    proof["status"] = _normalize_proof_status(status)
    proof["updated_at"] = _to_iso(_now())
    payload["proof"] = proof
    _write_json(execution_path(execution_id, repo_root), payload)
    return update_execution(
        execution_id,
        proof_status=str(proof.get("status") or "attached"),
        progress_summary=summary or str(payload.get("progress_summary") or ""),
        heartbeat=True,
        actor=actor,
        repo_root=repo_root,
        force=True,
    )


def mark_verified(
    execution_id: str,
    *,
    actor: str = "",
    summary: str = "",
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    payload = get_execution(execution_id, repo_root)
    if payload is None:
        raise FileNotFoundError(f"execution `{execution_id}` not found")
    proof = deepcopy(payload.get("proof") or _empty_proof())
    proof["status"] = "verified"
    proof["verified_at"] = _to_iso(_now())
    proof["updated_at"] = proof["verified_at"]
    if summary:
        proof["summary"] = str(summary).strip()
    payload["proof"] = proof
    _write_json(execution_path(execution_id, repo_root), payload)
    return update_execution(
        execution_id,
        state="verified",
        blocker="",
        proof_status="verified",
        progress_summary=summary or str(payload.get("progress_summary") or ""),
        heartbeat=True,
        actor=actor,
        repo_root=repo_root,
        force=True,
    )


def complete_execution(
    execution_id: str,
    *,
    actor: str = "",
    summary: str = "",
    repo_root: str | Path | None = None,
    verified_success: bool = False,
) -> dict[str, Any]:
    """Mark an execution completed — but ONLY when there is evidence.

    A completion claim must be backed by EITHER a produced artifact
    (``proof.artifacts`` non-empty, attached via ``attach_proof``) OR an explicit
    confirmed success signal (``verified_success=True`` — e.g. the worker observed a
    real tool succeed). Without evidence the task is marked ``failed`` instead of
    being stamped completed/verified. This closes the "verified without verification"
    hole: a no-op run, or one whose summary says "no tools were executed", can no
    longer surface to the user as a green completion.
    """
    payload = get_execution(execution_id, repo_root)
    if payload is None:
        raise FileNotFoundError(f"execution `{execution_id}` not found")
    # A run the user ended stays ended. Completion writes with force=True, which
    # bypasses the transition table, so a worker that kept going and reached its
    # own finish line used to overwrite the stop: the screen showed "Stopped by
    # you." and then, seconds later, "Created deliverable.txt". Whatever the
    # worker managed to produce is still on the record via salvaged artifacts --
    # this only refuses to relabel the ending.
    if _normalize_state(str(payload.get("state") or "")) in {"cancelled", "abandoned"}:
        return payload
    proof = payload.get("proof") or {}
    has_artifacts = bool(proof.get("artifacts"))
    if not (has_artifacts or verified_success):
        return update_execution(
            execution_id,
            state="failed",
            proof_status="failed",
            progress_summary=(
                summary or "No verifiable result: nothing was produced and no tool success was confirmed."
            ),
            blocker="no_evidence",
            heartbeat=False,
            actor=actor,
            repo_root=repo_root,
            force=True,
        )
    current_state = _normalize_state(str(payload.get("state") or "requested"))
    if current_state not in {"verified", "completed"}:
        payload = mark_verified(
            execution_id,
            actor=actor,
            summary=summary or str(payload.get("progress_summary") or ""),
            repo_root=repo_root,
        )
    return update_execution(
        execution_id,
        state="completed",
        blocker="",
        proof_status="verified",
        progress_summary=summary or str(payload.get("progress_summary") or ""),
        heartbeat=False,
        actor=actor,
        repo_root=repo_root,
        force=True,
    )


def fail_execution(
    execution_id: str,
    *,
    actor: str = "",
    summary: str = "",
    blocker: str = "",
    proof_status: str | None = None,
    salvaged_artifacts: list[str] | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Record a terminal failure, optionally keeping what the run had produced.

    A run that stops without succeeding often leaves real work behind -- a
    finished PDF sitting in its workspace while the user is told nothing was
    produced. ``salvaged_artifacts`` keeps that evidence on the record instead
    of discarding it, without claiming the run succeeded.
    """
    return update_execution(
        execution_id,
        state="failed",
        progress_summary=summary,
        blocker=blocker,
        proof_status=proof_status or "failed",
        salvaged_artifacts=salvaged_artifacts,
        heartbeat=False,
        actor=actor,
        repo_root=repo_root,
        force=True,
    )


# ── In-flight steerability ────────────────────────────────────────────────────
# A dispatched background task is not frozen: the user can send a follow-up that
# revises its goal, or cancel it. The chat layer calls steer_execution / request_cancel;
# the worker drains take_pending_instructions and checks is_cancel_requested between
# steps. This is the "just send a message to the task manager" capability that was
# missing — steering a RUNNING task, not only the synchronous chat turn.


def steer_execution(
    execution_id: str,
    instruction: str,
    *,
    actor: str = "",
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Queue an additional instruction for a running execution (the worker picks it
    up between steps). Refuses once the task is terminal."""
    payload = get_execution(execution_id, repo_root)
    if payload is None:
        raise FileNotFoundError(f"execution `{execution_id}` not found")
    text = str(instruction or "").strip()
    if not text:
        return payload
    if _normalize_state(str(payload.get("state") or "")) in TERMINAL_STATES:
        raise ValueError(f"execution `{execution_id}` is already terminal; cannot steer it")
    pending = list(payload.get("pending_instructions") or [])
    pending.append(text)
    payload["pending_instructions"] = pending
    _write_json(execution_path(execution_id, repo_root), payload)
    return update_execution(
        execution_id,
        progress_summary=f"New instruction from user: {text[:160]}",
        heartbeat=True,
        actor=actor or "user",
        repo_root=repo_root,
        force=True,
    )


def take_pending_instructions(execution_id: str, *, repo_root: str | Path | None = None) -> list[str]:
    """Return and CLEAR the queued follow-up instructions (worker-side consume)."""
    payload = get_execution(execution_id, repo_root)
    if payload is None:
        return []
    pending = [str(p) for p in (payload.get("pending_instructions") or []) if str(p).strip()]
    if pending:
        payload["pending_instructions"] = []
        _write_json(execution_path(execution_id, repo_root), payload)
    return pending


def request_cancel(
    execution_id: str,
    *,
    actor: str = "",
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Mark that the user asked to cancel a running execution. The worker checks
    is_cancel_requested between steps and stops; if already terminal this is a no-op."""
    payload = get_execution(execution_id, repo_root)
    if payload is None:
        raise FileNotFoundError(f"execution `{execution_id}` not found")
    if _normalize_state(str(payload.get("state") or "")) in TERMINAL_STATES:
        return payload
    payload["cancel_requested"] = True
    _write_json(execution_path(execution_id, repo_root), payload)
    return update_execution(
        execution_id,
        progress_summary="Cancellation requested by user.",
        heartbeat=True,
        actor=actor or "user",
        repo_root=repo_root,
        force=True,
    )


def delete_session_executions(
    session_id: str,
    *,
    repo_root: str | Path | None = None,
) -> int:
    """Remove every execution record belonging to one conversation.

    Deleting a chat cleared the conversation and purged memory, and reported a
    clean sweep -- but never touched these records, which keep the task's
    request text, its progress lines and the paths of what it produced, and
    stay served at the same address. The chat was gone; the data behind it was
    not. Returns the number of records removed.
    """
    sid = str(session_id or "").strip()
    if not sid:
        return 0
    removed = 0
    directory = runtime_dir(repo_root)
    if not directory.is_dir():
        return 0
    for path in list(directory.glob("exec-*.json")):
        record = _read_json(path, None)
        if not isinstance(record, dict):
            continue
        if str(record.get("conversation_id") or "") != sid and str(record.get("thread_id") or "") != sid:
            continue
        try:
            path.unlink()
            removed += 1
        except OSError:  # pragma: no cover - a locked file must not fail the delete
            log_path = path
            with suppress(Exception):
                log_path.write_text("", encoding="utf-8")
    if removed:
        with suppress(Exception):
            list_executions(repo_root, refresh=True)
    return removed


def cancel_execution(
    execution_id: str,
    *,
    actor: str = "",
    summary: str = "",
    salvaged_artifacts: list[str] | None = None,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """End a run because the user stopped it. Not a failure.

    Every Stop used to be recorded with fail_execution(blocker="cancelled"),
    which put the run in `failed` with a failed proof -- so a deliberate stop was
    indistinguishable from a crash in the task list, and 75 of 238 stored Code
    turns read as failed builds.

    Work the run had already finished is kept, because stopping something
    halfway through does not make the files it wrote disappear.
    """
    return update_execution(
        execution_id,
        state="cancelled",
        progress_summary=summary or "Stopped by you.",
        blocker="cancelled",
        proof_status="cancelled",
        salvaged_artifacts=salvaged_artifacts,
        actor=actor or "user",
        repo_root=repo_root,
        force=True,
    )


def is_cancel_requested(execution_id: str, *, repo_root: str | Path | None = None) -> bool:
    payload = get_execution(execution_id, repo_root)
    return bool(payload and payload.get("cancel_requested"))


def mark_abandoned(
    execution_id: str,
    *,
    actor: str = "",
    summary: str = "",
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    return update_execution(
        execution_id,
        state="abandoned",
        progress_summary=summary,
        heartbeat=False,
        actor=actor,
        repo_root=repo_root,
        force=True,
    )
