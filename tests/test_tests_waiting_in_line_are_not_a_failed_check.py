"""A check.run answer that its tests are still queued or running is not shown, or counted, as a failed check.

Review of the line of test runs, 2026-11-13: the answer has no exit code and no verdict, so the Build stream marked
it "Check verdict unavailable" with a cross, added one to the issues once for every eight minutes of waiting, and
ToolFailures counted it as a failed call that a run which changed no file had never moved past.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from thomas.agent.tool_failures import ToolFailures
from thomas.forge.anvil import dispatch_agent_loop_translator as translator
from thomas.tools import check_run

CARDS = (Path(__file__).resolve().parents[1] / "thomas" / "server" / "web" / "js" / "unified_code_cards.js").read_text(
    encoding="utf-8"
)


def _answer(status: str) -> dict[str, Any]:
    """What the agent loop hands the stream for a check.run call whose tests have no verdict yet."""
    answer = check_run._not_yet(check_run._Job(status=status, ahead=3), ["python", "-m", "pytest", "tests/test_x.py"])
    text = json.dumps(answer.data)
    return {"tool_name": "check.run", "ok": answer.ok, "result": text[:4000], "result_text": text}


@pytest.mark.parametrize("status", ["queued", "running"])
def test_the_stream_says_the_tests_are_waiting_not_that_a_check_failed(status: str) -> None:
    shown = translator._tool_result_display(_answer(status))
    assert shown["is_error"] is False and shown["waiting"] == status
    assert "neither a pass nor a failure" in shown["text"] and "Check verdict unavailable" not in shown["text"]
    assert "passed" not in shown and "exit_code" not in shown, "it carries no verdict to show as a tick"


def test_a_receipt_with_no_verdict_that_is_not_a_waiting_answer_is_still_unavailable() -> None:
    garbled = {"tool_name": "check.run", "ok": True, "result": "{}", "result_text": "{}"}
    shown = translator._tool_result_display(garbled)
    assert shown["is_error"] is True and shown["text"].startswith("Check verdict unavailable")


def _events(*, earlier_failure: bool) -> list[dict[str, Any]]:
    failed = [{"fc": "tool", "name": "shell.exec"}, {"fc": "tool_result", "name": "shell.exec", "is_error": True}]
    waiting = [
        {"fc": "tool", "name": "check.run"},
        {"fc": "tool_result", "name": "check.run", **translator._tool_result_display(_answer("queued"))},
    ]
    return [*(failed if earlier_failure else []), *waiting]


def test_waiting_tests_are_not_a_failed_call() -> None:
    seen = ToolFailures()
    for event in _events(earlier_failure=False):
        seen.observe(event)
    assert seen.unresolved is False


def test_waiting_tests_do_not_clear_a_failure_that_came_before_them() -> None:
    seen = ToolFailures()
    for event in _events(earlier_failure=True):
        seen.observe(event)
    assert seen.unresolved is True, "only a write that succeeded moves a run past a failed call"


def test_the_card_of_a_waiting_check_shows_neither_a_tick_nor_a_cross() -> None:
    assert "ev.waiting ? '…' : (options.failed ? '✕' : '✓')" in CARDS
