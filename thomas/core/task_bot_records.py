"""The shape of a stored execution record, and the normalizers for its fields.

Building a fresh record, building one transition entry, and deciding which part
of a worker's summary is fit for a person to read are all pure: every timestamp
arrives as an argument, nothing here reads a clock or touches disk. The reading
and writing of these records lives in ``task_bot_runtime``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from thomas.core.task_bot_states import _normalize_proof_status


@dataclass(frozen=True)
class RuntimeTransition:
    state: str
    summary: str
    proof_status: str
    blocker: str
    actor: str
    occurred_at: str


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
