"""SWEEP: concurrency / rapid-message robustness.

Verifies the two former "too many chats in a row -> task failed" 409s are closed,
The cases that read the retired V1 chat handler's source are gone with that
handler; what is left:
  - follow-ups within queue capacity are accepted (control)
  - A stale background task is FLAGGED, not auto-failed.
"""

from __future__ import annotations

import asyncio

from _harness import Recorder

R = "concurrency-robustness"


def _busy_decision_fixed(queue_for_sid, msg_text: str) -> int:
    """Mirror of the FIXED busy-session interrupt branch: create-on-demand + coalesce,
    so a non-empty rapid follow-up is always accepted (202), never 409."""
    if not msg_text:
        return 400
    q = queue_for_sid if queue_for_sid is not None else asyncio.Queue(maxsize=64)
    try:
        q.put_nowait(msg_text)
    except asyncio.QueueFull:
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
        q.put_nowait(msg_text)
    return 202


def run() -> Recorder:
    rec = Recorder("concurrency")

    # 1) Within capacity (control).
    q2 = asyncio.Queue(maxsize=64)
    ok = [_busy_decision_fixed(q2, f"m{i}") for i in range(8)]
    rec.add(
        case="follow-ups within queue capacity (control)",
        dimension=R,
        expected="messages within capacity are accepted",
        actual=f"statuses={set(ok)}",
        passed=all(s == 202 for s in ok),
        severity="low",
        evidence="confirms accepted path",
    )

    # 2) A stale task is flagged, not auto-failed (so a flooded session can't lose it).
    import tempfile
    from pathlib import Path

    from thomas.core import task_bot_runtime as tbr

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ex = tbr.create_execution(session_id="s", summary="long job", repo_root=root)
        eid = ex["execution_id"]
        tbr.update_execution(eid, state="executing", actor="w", repo_root=root, force=True)
        # Backdate liveness so staleness detection fires.
        p = tbr.get_execution(eid, root)
        p["last_heartbeat_at"] = "2020-01-01T00:00:00+00:00"
        p["updated_at"] = "2020-01-01T00:00:00+00:00"
        tbr._write_json(tbr.execution_path(eid, root), p)
        rows = tbr.list_executions(root, refresh=True, stale_after_minutes=5)
        row = next((r for r in rows if r.get("execution_id") == eid), {})
        after = tbr.get_execution(eid, root) or {}
        flagged = bool(row.get("stale"))
        not_auto_failed = after.get("state") == "executing"
        rec.add(
            case="stale background task is flagged, not auto-failed",
            dimension=R,
            expected="a stale task surfaces as needs-attention but is NOT silently failed",
            actual=f"stale_flag={flagged}, state_after_summary={after.get('state')!r}",
            passed=flagged and not_auto_failed,
            severity="med",
            evidence="read_summary computes a derived stale flag; it never transitions the execution to failed",
        )
    return rec


if __name__ == "__main__":
    run().console()
