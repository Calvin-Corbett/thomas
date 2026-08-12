"""SWEEP: completion-state & verification integrity.

Drives the REAL task lifecycle (`thomas.core.task_bot_runtime`) inside an
isolated temp dir (repo_root=tmpdir, so nothing touches the real ledger) and
checks whether the 'completed'/'verified' stamp means anything.

KEY FINDING THIS SWEEP PROVES: complete_execution() -> mark_verified() stamps
state='completed' and proof_status='verified' UNCONDITIONALLY, with
proof.artifacts==[] and no success signal. A task whose summary literally says
'no tools were executed' still ends 'completed' + 'verified'. The 'verified'
label is applied without verification.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from _harness import Recorder

from thomas.core import task_bot_runtime as tbr

V = "verification-integrity"


def run() -> Recorder:
    rec = Recorder("lifecycle")

    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        # --- Case 1: complete a task that did literally nothing ---
        ex = tbr.create_execution(
            session_id="s1",
            summary="Send an email to bob@example.com",
            repo_root=root,
        )
        eid = ex["execution_id"]
        tbr.complete_execution(
            eid,
            actor="worker",
            summary="I don't see any recorded tool calls, so no tools were executed.",
            repo_root=root,
        )
        rec_after = tbr.get_execution(eid, root) or {}
        state = rec_after.get("state")
        proof = rec_after.get("proof") or {}
        artifacts = proof.get("artifacts") or []

        rec.add(
            case="no-op task is stamped completed",
            dimension=V,
            expected="a task with no tool calls / no side effect should end failed or blocked, not completed",
            actual=f"state={state!r}",
            passed=(state != "completed"),
            severity="high",
            evidence="summary literally says 'no tools were executed'",
        )
        rec.add(
            case="'verified' applied without any artifact/evidence",
            dimension=V,
            expected="proof_status='verified' should require proof.artifacts or a success signal",
            actual=f"proof_status={proof.get('status')!r}, artifacts={artifacts!r}",
            passed=(proof.get("status") != "verified" or bool(artifacts)),
            severity="high",
            evidence="mark_verified() sets status='verified' with no check on artifacts",
        )

        # --- Case 2: a genuinely evidenced completion (control) ---
        ex2 = tbr.create_execution(session_id="s2", summary="Write report.pdf", repo_root=root)
        eid2 = ex2["execution_id"]
        tbr.attach_proof(
            eid2,
            artifacts=[{"path": "report.pdf", "type": "pdf", "bytes": 412}],
            summary="Wrote report.pdf (412 bytes)",
            status="verified",
            repo_root=root,
        )
        tbr.complete_execution(eid2, actor="worker", summary="Wrote report.pdf", repo_root=root)
        r2 = tbr.get_execution(eid2, root) or {}
        p2 = r2.get("proof") or {}
        rec.add(
            case="evidenced completion is legitimate (control)",
            dimension=V,
            expected="a task WITH attached artifacts may legitimately be completed/verified",
            actual=f"state={r2.get('state')!r}, artifacts={len(p2.get('artifacts') or [])}",
            passed=(r2.get("state") == "completed" and bool(p2.get("artifacts"))),
            severity="low",
            evidence="shows the verified label CAN be correct; the gap is it is never REQUIRED",
        )

    return rec


if __name__ == "__main__":
    run().console()
