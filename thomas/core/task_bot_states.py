"""The states a task-bot execution may occupy, and the moves allowed between them.

Pure vocabulary: no clock, no disk. This module only answers "is this a real
state?" and "is that move legal?". Everything that reads or writes an execution
record on disk lives in ``task_bot_runtime``.
"""

from __future__ import annotations

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


def _validate_transition(current: str, new_state: str, *, allow_same: bool) -> None:
    if new_state not in VALID_STATES:
        raise ValueError(f"invalid runtime state `{new_state}`")
    if allow_same and current == new_state:
        return
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new_state != current and new_state not in allowed:
        raise ValueError(f"invalid runtime transition `{current}` -> `{new_state}`")
