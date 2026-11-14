"""Build must show the check's verdict, not just whether its process ran."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from thomas.core.events import EventType
from thomas.forge.anvil.dispatch_agent_loop_translator import _AgentLoopForgeTranslator
from thomas.tools.check_run import CheckRunTool


def _translate(content: str, *, ok: bool = True, name: str = "check.run", feedback: str = "") -> dict:
    events: list[dict] = []
    translator = _AgentLoopForgeTranslator(events.append)
    translator.feed(
        EventType.TOOL_RESULT.value,
        {
            "tool_id": "check-1",
            "tool_name": name,
            "ok": ok,
            "result": content[:4000],
            "result_text": content + feedback,
        },
    )
    assert len(events) == 1
    assert events[0]["fc"] == "tool_result"
    return events[0]


@pytest.mark.parametrize(
    ("filename", "source", "passed"),
    [
        ("index.html", "<!doctype html><html><body>Lantern</body></html>\n", False),
        ("app.py", "VALUE = 1\n", True),
    ],
)
def test_real_ruff_verdict_reaches_build(tmp_path: Path, filename: str, source: str, passed: bool) -> None:
    (tmp_path / filename).write_text(source, encoding="utf-8")
    result = asyncio.run(CheckRunTool(tmp_path).safe_execute({"check": "ruff_check", "args": [filename]}))
    assert result.ok, result.error  # A red check still executed successfully.
    assert result.data["passed"] is passed
    if not passed:
        assert "invalid-syntax" in result.data["output"]
    event = _translate(result.to_content())
    assert event["is_error"] is not passed
    assert event["passed"] is passed
    assert event["exit_code"] == result.data["exit_code"]


def test_full_receipt_survives_preview_truncation_and_feedback() -> None:
    content = json.dumps({"check": "pytest", "output": "x" * 6000, "exit_code": 1, "passed": False})
    event = _translate(content, feedback="\n\nVerification: inspect the failed assertion.")
    assert event["is_error"] is True
    assert event["passed"] is False
    assert event["exit_code"] == 1
    assert len(event["text"]) <= 500


@pytest.mark.parametrize(
    "receipt",
    [
        "truncated {",
        "[]",
        "null",
        "{}",
        '{"passed":true,"exit_code":1}',
        '{"passed":false,"exit_code":0}',
        '{"passed":"false","exit_code":1}',
        '{"passed":true,"exit_code":false}',
    ],
)
def test_missing_or_inconsistent_verdict_never_claims_a_pass(receipt: str) -> None:
    event = _translate(receipt)
    assert event["is_error"] is True
    assert event["text"].startswith("Check verdict unavailable.")
    assert "passed" not in event


def test_refused_check_retains_its_actual_error() -> None:
    event = _translate('{"ok":false,"error":"check refused"}', ok=False)
    assert event["is_error"] is True
    assert "check refused" in event["text"]
    assert "unavailable" not in event["text"]


@pytest.mark.parametrize("ok", [False, True])
def test_other_tool_success_is_not_inferred_from_result_text(ok: bool) -> None:
    content = '{"exit_code":1,"passed":false}'
    event = _translate(content, name="fs.read_file", ok=ok)
    assert event["is_error"] is not ok
    assert event["text"] == content
    assert "passed" not in event
