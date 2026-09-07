"""A repeated identical tool failure disables that call; it does not kill the run.

TB-4.0 run 3 (2026-09-04): git.status failed three times in a non-git folder
and eng.lint three times on a missing ``python``; both times the loop aborted
a 128+ iteration run with "Tool loop stability issue". Frontier harnesses
(LangChain LoopDetection, Claude Code) refuse the repeated call and tell the
model why, and the run goes on. The abort stays only as a backstop for a model
that keeps hammering an already-disabled call.
"""

from __future__ import annotations

from thomas.agent.tool_failure_guard import ToolFailureGuard


def test_third_identical_failure_disables_that_call_and_says_so() -> None:
    guard = ToolFailureGuard(limit=3)
    args = {"path": "/app/x.py"}
    err = "FileNotFoundError: [Errno 2] No such file or directory: 'python'"

    assert guard.record_failure("eng.lint", args, err) is None
    assert guard.record_failure("eng.lint", args, err) is None
    note = guard.record_failure("eng.lint", args, err)

    assert note is not None
    assert "eng.lint" in note
    assert "3" in note
    assert "disabled" in note


def test_a_disabled_call_is_refused_before_it_runs_but_other_args_still_run() -> None:
    guard = ToolFailureGuard(limit=3)
    for _ in range(3):
        guard.record_failure("git.status", {}, "fatal: not a git repository")

    refusal = guard.check_before_call("git.status", {})
    assert refusal is not None
    assert "git.status" in refusal
    assert "disabled" in refusal
    assert guard.check_before_call("git.status", {"short": True}) is None
    assert guard.check_before_call("fs.list_dir", {}) is None


def test_abort_only_after_the_model_keeps_hammering_a_disabled_call() -> None:
    guard = ToolFailureGuard(limit=3, hammer_limit=3)
    for _ in range(3):
        guard.record_failure("git.status", {}, "fatal: not a git repository")
    assert guard.should_abort() is False

    guard.check_before_call("git.status", {})
    guard.check_before_call("git.status", {})
    assert guard.should_abort() is False
    guard.check_before_call("git.status", {})
    assert guard.should_abort() is True
    assert "git.status" in guard.abort_reason()


def test_different_failures_from_the_same_tool_do_not_pool() -> None:
    guard = ToolFailureGuard(limit=3)
    assert guard.record_failure("shell.exec", {"command": "a"}, "Exit code 1") is None
    assert guard.record_failure("shell.exec", {"command": "b"}, "Exit code 1") is None
    assert guard.record_failure("shell.exec", {"command": "c"}, "Exit code 1") is None
    assert guard.check_before_call("shell.exec", {"command": "a"}) is None
