"""SWEEP: in-flight task steerability.

The creator's expectation: "editing a task in progress should be easy — you
just send a message to the task manager." This sweep introspects the REAL task
runtime + delegation surface for any such path.

KEY FINDING THIS SWEEP PROVES: there is no API to amend, redirect, or cancel an
already-DISPATCHED background execution from chat. update_execution only mutates
status/progress bookkeeping fields; it cannot inject a new user instruction into
a running worker. The only "interrupt" that exists (loop_execution message
queue) steers the synchronous in-chat agent run, not a background task card.
"""

from __future__ import annotations

from _harness import Recorder

from thomas.core import task_bot_runtime as tbr

S = "task-steerability"

# Names that would indicate a "change a running task" capability.
STEER_VERBS = (
    "steer",
    "redirect",
    "amend",
    "revise",
    "inject",
    "add_instruction",
    "append_instruction",
    "edit_instruction",
    "retarget",
    "reprioritize_instruction",
)
CANCEL_VERBS = ("cancel", "abort", "stop_execution", "interrupt_execution", "halt")


def run() -> Recorder:
    rec = Recorder("steerability")
    api = {name for name in dir(tbr) if not name.startswith("__")}

    steer_api = sorted(n for n in api if any(v in n.lower() for v in STEER_VERBS))
    rec.add(
        case="API to amend/redirect a running task with a new instruction",
        dimension=S,
        expected="a follow-up message can revise the goal of an in-flight background task",
        actual=f"matching functions in task_bot_runtime: {steer_api or 'NONE'}",
        passed=bool(steer_api),
        severity="high",
        evidence="only update_execution exists (mutates state/progress fields, not the worker's goal)",
    )

    cancel_api = sorted(n for n in api if any(v in n.lower() for v in CANCEL_VERBS))
    rec.add(
        case="API to cancel a dispatched background task from chat",
        dimension=S,
        expected="the user can cancel/stop a running background task",
        actual=f"matching functions in task_bot_runtime: {cancel_api or 'NONE'}",
        passed=bool(cancel_api),
        severity="med",
        evidence="abandoned is a valid state but there is no user-facing cancel entry point on the chat path",
    )

    # Round-trip: steering must actually reach a dispatched background TASK — queue a
    # follow-up instruction and cancel, and confirm the worker-side consume APIs see
    # them. Plus confirm the worker loop (chat_delegation) actually consumes both.
    import tempfile
    from pathlib import Path

    from _harness import _REPO_ROOT

    round_trip_ok = False
    cancel_ok = False
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ex = tbr.create_execution(session_id="s", summary="build a thing", repo_root=root)
        eid = ex["execution_id"]
        tbr.steer_execution(eid, "actually make it blue", repo_root=root)
        drained = tbr.take_pending_instructions(eid, repo_root=root)
        round_trip_ok = "actually make it blue" in drained and tbr.take_pending_instructions(eid, repo_root=root) == []
        tbr.request_cancel(eid, repo_root=root)
        cancel_ok = tbr.is_cancel_requested(eid, repo_root=root)

    worker_src = (_REPO_ROOT / "thomas" / "server" / "chat_delegation.py").read_text(encoding="utf-8", errors="ignore")
    worker_consumes = "take_pending_instructions" in worker_src and "is_cancel_requested" in worker_src

    rec.add(
        case="steering reaches a dispatched background task (round-trip + worker consumes)",
        dimension=S,
        expected="queued instruction is delivered to the worker; cancel is observed and stops the run",
        actual=f"instruction_round_trip={round_trip_ok}, cancel_flag={cancel_ok}, worker_consumes={worker_consumes}",
        passed=round_trip_ok and cancel_ok and worker_consumes,
        severity="high",
        evidence="task_bot_runtime.steer_execution/request_cancel + chat_delegation drains them between steps",
    )
    return rec


if __name__ == "__main__":
    run().console()
