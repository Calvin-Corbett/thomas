"""How the inactivity sweep releases a dead agent's claim, and how it says so.

Two honesty problems measured 2026-10-03 on a copy of the real board:

* `claim.release` is refused by the presence gate ("presence gate requires
  override") for a dead agent, yet the claim row was gone anyway because
  `move_task_to_up_for_grabs` removes it. The cycle reported a failure for a
  claim that had been released, and nothing recorded that the gate was passed.
  Now the release is retried under an explicit, reasoned override (the gate
  writes its own audit entry) and the override is reported in the payload.
* A cycle that failed half way left the agent unflagged, so the next cycle
  pinged again and opened a second issue. `already_flagged` lets the sweep
  skip the ping and the issue when the agent was flagged after this claim began.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

PRESENCE_REFUSAL = "presence gate requires override"


def release_dead_claim(claim_module: Any, workboard_path: Path, *, agent: str, reason: str) -> dict[str, object]:
    """Release `agent`'s claim; return what happened without hiding the override."""

    common = {"agent": agent, "allow_dirty": True, "dirty_reason": reason, "require_done_state": False}
    ok, message = claim_module.release(workboard_path, **common)
    result: dict[str, object] = {"agent": agent, "ok": bool(ok), "message": str(message), "override": None}
    if ok or not str(message).lower().startswith(PRESENCE_REFUSAL):
        return result
    ok2, message2 = claim_module.release(
        workboard_path, **common, allow_presence_override=True, presence_override_reason=reason
    )
    gone = bool(ok2) or "no active claim" in str(message2).lower()
    result.update(
        ok=gone,
        message=str(message2),
        override={
            "agent": agent,
            "reason": reason,
            "refused_with": str(message),
            "claim_already_removed_by_task_move": bool(not ok2 and gone),
        },
    )
    return result


def already_flagged(
    inactive_rows: dict[str, dict[str, str]], agent_key: str, claimed_at: datetime | None, parse_iso: Any
) -> bool:
    """True when the Inactive Agents section flagged this agent after the claim began."""

    row = inactive_rows.get(agent_key)
    if not row or str(row.get("state", "")).strip().lower() != "inactive":
        return False
    detected = parse_iso(str(row.get("detected_at", "")))
    if detected is None or claimed_at is None:
        return True
    return bool(detected >= claimed_at)
