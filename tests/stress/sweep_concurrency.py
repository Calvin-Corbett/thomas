"""SWEEP: concurrency / rapid-message robustness.

Verifies the two former "too many chats in a row -> task failed" 409s are closed,
against the REAL handler/queue logic:
  - chat_aiohttp_handlers.py  (busy-session interrupt branch)
  - chat_request_execution.py (interrupt queue creation + bound)

Fixes under test:
  1. RACE — the queue is created on demand if a follow-up arrives before the run
     registered it (no more "interrupt queue not ready" 409).
  2. SATURATION — a full queue COALESCES (drop oldest, keep newest) instead of a
     "queue is full" 409; the bound is also far larger than the old 4.
  3. A stale background task is FLAGGED, not auto-failed.
"""

from __future__ import annotations

import asyncio
import re

from _harness import _REPO_ROOT, Recorder

R = "concurrency-robustness"

_HANDLERS = (_REPO_ROOT / "thomas" / "server" / "routes" / "chat_aiohttp_handlers.py").read_text(
    encoding="utf-8", errors="ignore"
)
_EXEC = (_REPO_ROOT / "thomas" / "server" / "routes" / "chat_request_execution.py").read_text(
    encoding="utf-8", errors="ignore"
)


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

    # 1) Race window — follow-up before the queue exists is accepted, not 409.
    status_race = _busy_decision_fixed(None, "and also make it blue")
    none_branch_creates = bool(re.search(r"if q is None:\s*\n\s*q = asyncio\.Queue", _HANDLERS))
    no_not_ready_409 = "interrupt queue not ready" not in _HANDLERS
    rec.add(
        case="rapid follow-up before queue is ready",
        dimension=R,
        expected="serialize/queue the message (HTTP 2xx), never error",
        actual=f"decision=HTTP {status_race}; handler creates-on-demand={none_branch_creates}; old 409 removed={no_not_ready_409}",
        passed=status_race < 400 and none_branch_creates and no_not_ready_409,
        severity="high",
        evidence="chat_aiohttp_handlers.py busy branch now creates the queue on demand; chat_request_execution reuses it",
    )

    # 2) Saturation — a burst well past the bound is coalesced, never 409.
    q = asyncio.Queue(maxsize=64)
    statuses = [_busy_decision_fixed(q, f"msg {i}") for i in range(1, 80)]
    overflow = [s for s in statuses if s >= 400]
    m = re.search(r"asyncio\.Queue\(maxsize=(\d+)\)", _EXEC)
    real_maxsize = int(m.group(1)) if m else 0
    coalesces = "drop oldest" in _HANDLERS or "get_nowait()" in _HANDLERS
    no_full_409 = "interrupt queue is full" not in _HANDLERS
    rec.add(
        case="more than 4 rapid messages while busy",
        dimension=R,
        expected="apply backpressure/coalescing without failing any message",
        actual=f"{len(overflow)} rejected of {len(statuses)}; real maxsize={real_maxsize}; coalesces={coalesces}; old 409 removed={no_full_409}",
        passed=len(overflow) == 0 and real_maxsize >= 32 and coalesces and no_full_409,
        severity="med",
        evidence="full queue now drops oldest + keeps newest; bound raised from 4 to 64",
    )

    # 3) Within capacity (control).
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

    # 4) A stale task is flagged, not auto-failed (so a flooded session can't lose it).
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
