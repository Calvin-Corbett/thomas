"""A run that produced nothing does not get to describe itself as a success.

`complete_execution` demotes an evidence-free "done" to failed(no_evidence) -- the
hole-closer for "verified without verification". It wrote the reason for that
demotion as a *fallback*:

    progress_summary=(summary or "No verifiable result: nothing was produced ...")

which made the reason unreachable. The only caller that reaches this branch builds
its summary with `_build_result_summary`, and that function has no empty return
path; its last line is "The worker returned no output." So the right-hand side had
never once been shown, and what a person actually read on a failed, evidence-free
run was the worker's own prose -- in this branch, a claim of success under dispute
by definition.

The first test below is the one that would have caught it: it pins the fact that
made the fallback dead, rather than only checking the behaviour that fact broke.
"""

from __future__ import annotations

from thomas.core import task_bot_runtime
from thomas.core.task_bot_runtime import _no_evidence_summary
from thomas.server.chat_delegation_deliverable import _build_result_summary

VERDICT = "No verifiable result"
CLAIM = "I created the report and verified the output."


def test_the_summary_that_reaches_this_branch_is_never_empty() -> None:
    """Why `summary or <reason>` was dead code, pinned as a fact.

    If this ever starts returning an empty string the `or` spelling becomes
    reachable again -- and someone reading it would reasonably think it works.
    """

    assert _build_result_summary([], [])
    assert _build_result_summary([CLAIM], [])
    assert _build_result_summary([], ["shell"])
    assert _build_result_summary([], [], created_files=[])


def test_the_verdict_leads_and_the_worker_claim_is_attributed() -> None:
    combined = _no_evidence_summary(CLAIM)

    assert combined.startswith(VERDICT), "the reader meets the claim before the verdict"
    assert CLAIM in combined, "the worker's text was thrown away instead of attributed"
    assert "The worker reported:" in combined, "the claim is presented as fact, not as a claim"


def test_no_worker_text_still_reads_as_a_verdict() -> None:
    assert _no_evidence_summary("").startswith(VERDICT)
    assert _no_evidence_summary("   ").startswith(VERDICT)
    # And it does not say the same sentence twice.
    once = _no_evidence_summary(
        "No verifiable result: nothing was produced and no tool success was confirmed."
    )
    assert once.count(VERDICT) == 1


def _executing(root, summary: str = "Long background job") -> str:
    execution = task_bot_runtime.create_execution(
        session_id="sess-no-evidence",
        summary=summary,
        task_id="task-no-evidence",
        actor="task-manager-agent",
        repo_root=root,
    )
    execution_id = str(execution["execution_id"])
    for state in ("classified", "queued", "claimed", "executing"):
        task_bot_runtime.update_execution(
            execution_id,
            state=state,
            progress_summary=f"now {state}",
            actor="worker-1",
            repo_root=root,
        )
    return execution_id


def test_an_evidence_free_run_does_not_keep_the_claim_as_its_summary(tmp_path) -> None:
    """End to end: the record a person reads must not assert what was not shown."""

    execution_id = _executing(tmp_path)
    task_bot_runtime.complete_execution(
        execution_id,
        actor="worker-1",
        summary=CLAIM,
        repo_root=tmp_path,
        verified_success=False,
    )
    record = task_bot_runtime.get_execution(execution_id, tmp_path) or {}
    stored = str(record.get("progress_summary") or "")

    assert str(record.get("state")) == "failed"
    assert str(record.get("blocker")) == "no_evidence"
    assert stored.startswith(VERDICT), f"a failed run narrated its own success: {stored!r}"
    assert CLAIM in stored, "the worker's account was discarded rather than attributed"


def test_a_run_that_showed_something_keeps_its_own_summary(tmp_path) -> None:
    """The control. Without this, the assertions above would also pass if the
    verdict were bolted onto every run, which would be a different lie."""

    execution_id = _executing(tmp_path)
    task_bot_runtime.complete_execution(
        execution_id,
        actor="worker-1",
        summary="Created report.csv.",
        repo_root=tmp_path,
        verified_success=True,
    )
    record = task_bot_runtime.get_execution(execution_id, tmp_path) or {}
    stored = str(record.get("progress_summary") or "")

    assert str(record.get("state")) != "failed"
    assert VERDICT not in stored, "a run with confirmed success was told it had no result"
    assert "Created report.csv." in stored
