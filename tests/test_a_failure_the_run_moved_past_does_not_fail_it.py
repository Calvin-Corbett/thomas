"""A run that moved past a tool failure is not a failed run.

A run that changes no files is a failure when a tool call in it reported failure: that is the sign of an edit that
did not happen. It was read as ANY failure, anywhere in the run. On 2026-09-27 four Thomas projects had finished
their work in earlier runs and spent a run confirming it; each was filed as crashed and never handed in, because a
search found nothing, a probe exited 1, or ``check.run`` refused an option ("Nothing was run") before every later
check passed. The project fixing this could not hand its own fix in for the same reason.

The rule now: a failed look changes nothing and never counts; a failed file edit (or an unnamed call, which could be
one) stands until a later file edit succeeds; any other failed call stands until a later write-capable call
succeeds. The transcript verdict and the in-process dispatcher apply the same rule.
"""

from __future__ import annotations

from pathlib import Path

from tests.test_dispatch_agent_loop_readonly_answers import _dispatch, _transcript, repo  # noqa: F401 -- fixture
from thomas.agent.tool_failures import ToolFailures
from thomas.forge.anvil.forge_event_stream import FORGE_EVENT_KEY
from thomas.server.routes.evolve_agent_run_status import _confirmed_conversation_reply

DONE = {FORGE_EVENT_KEY: "final", "text": "DONE: the focused tests passed and the staged change is intact."}


def _result(name: str, *, access: str = "write", failed: bool = False, text: str = "") -> dict:
    event = {FORGE_EVENT_KEY: "tool_result", "name": name, "access": access, "text": text or name}
    if failed:
        event["is_error"] = True
    return event


REFUSED_THEN_CHECKED = [
    _result("check.run", failed=True, text="check.run refused: git diff path '--cached' refused. Nothing was run."),
    _result("check.run"),
    _result("shell.exec", access="read", text="git diff --cached --check"),
    DONE,
]
EDIT_FAILED_THEN_SHELL = [
    _result("fs.write_file", failed=True, text="denied"),
    _result("shell.exec", text="python -m pytest tests/test_x.py"),
    {FORGE_EVENT_KEY: "final", "text": "I updated the file."},
]


def _unresolved(events: list[dict]) -> bool:
    failures = ToolFailures()
    for event in events:
        failures.observe(event)
    return failures.unresolved


def test_a_failed_look_never_counts() -> None:
    assert _unresolved([_result("shell.exec", access="read", failed=True, text="git grep: no match")]) is False
    assert _unresolved([_result("code.search", access="", failed=True)]) is False


def test_a_failed_check_is_cleared_by_a_later_one_that_ran() -> None:
    assert _unresolved(REFUSED_THEN_CHECKED) is False


def test_a_failed_file_edit_needs_a_later_file_edit() -> None:
    assert _unresolved(EDIT_FAILED_THEN_SHELL) is True
    assert _unresolved([_result("fs.write_file", failed=True), _result("fs.write_file")]) is False


def test_an_unnamed_failure_stays_strict() -> None:
    unnamed = {FORGE_EVENT_KEY: "tool_result", "text": "boom", "is_error": True}
    assert _unresolved([unnamed, _result("shell.exec")]) is True


def test_both_verdict_sites_agree(repo: Path) -> None:  # noqa: F811
    confirmed = _dispatch(repo, REFUSED_THEN_CHECKED)
    assert confirmed.ok is True, confirmed.reason
    assert _confirmed_conversation_reply(_transcript(*REFUSED_THEN_CHECKED)) is True

    failed = _dispatch(repo, EDIT_FAILED_THEN_SHELL)
    assert failed.ok is False, failed.reason
    assert _confirmed_conversation_reply(_transcript(*EDIT_FAILED_THEN_SHELL)) is False
