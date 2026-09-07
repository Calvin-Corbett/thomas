"""The run report's rubric reads the acceptance contract (2026-09-06).

Driving Build with a kanban board: the transcript said "acceptance contract
met: every item checked and satisfied (judge: 2 call(s))", and the results
card directly under it said "your specific ask was not separately verified"
with the rubric evidence "the goal was not written as a checklist, so no
individual requirement was extracted or checked on its own". Both came from
the same run. The contract had extracted the items and the judge had checked
them; the report was built from the forge events alone and no event carried
the settlement, so the rubric fell back to its prose-goal wording and stated
something false about the run's own work.

Two halves: the dispatcher's translator emits the settlement as a structured
``acceptance`` event, and the rubric builds one row per contract item from it.
"""

from __future__ import annotations

import json
from typing import Any

from thomas.forge.anvil.dispatch_agent_loop import _AgentLoopForgeTranslator
from thomas.forge.anvil.run_report import build_run_report

_SETTLEMENT: dict[str, Any] = {
    "active": True,
    "verdict": {"met": False, "unmet": ["r2"], "unchecked": ["r3"]},
    "evaluator": {"available": True, "calls": 2, "findings": [], "checks_run": []},
    "items": [
        {
            "item_id": "r1",
            "kind": "requirement",
            "description": "Drag cards between columns with the mouse",
            "checked": True,
            "satisfied": True,
            "detail": "playtest 090320 moved a card from To do to Doing",
        },
        {
            "item_id": "r2",
            "kind": "requirement",
            "description": "A dark/light toggle in the header that also persists",
            "checked": True,
            "satisfied": False,
            "detail": "theme reset to light after reload",
        },
        {
            "item_id": "r3",
            "kind": "requirement",
            "description": "Delete a card with a small x on it",
            "checked": False,
            "satisfied": False,
            "detail": "",
        },
        {
            "item_id": "compiles",
            "kind": "machine",
            "description": "changed sources parse",
            "checked": True,
            "satisfied": True,
            "detail": "index.html parses",
        },
    ],
}

GOAL = "Build a kanban board as a single index.html. Drag cards between columns with the mouse. A dark/light toggle in the header that also persists."


def _transcript(*events: dict[str, Any]) -> str:
    return "\n".join(json.dumps(e) for e in events)


def test_the_translator_emits_the_settlement_as_an_event() -> None:
    out: list[dict[str, Any]] = []
    translator = _AgentLoopForgeTranslator(out.append)
    translator.feed("agent_done", {"text": "Done.", "token_report": {"acceptance_contract": _SETTLEMENT}})
    events = [e for e in out if e.get("fc") == "acceptance"]
    assert len(events) == 1, [e.get("fc") for e in out]
    event = events[0]
    assert event["verdict"]["met"] is False and event["verdict"]["unmet"] == ["r2"]
    ids = [row["item_id"] for row in event["items"]]
    assert ids == ["r1", "r2", "r3", "compiles"]
    assert event["items"][0]["satisfied"] is True and event["items"][1]["satisfied"] is False


def test_the_rubric_has_one_row_per_contract_item_and_no_prose_fallback() -> None:
    transcript = _transcript(
        {"fc": "tool", "name": "Write", "text": "index.html"},
        {"fc": "tool_result", "text": "ok", "is_error": False},
        {"fc": "meta", "text": "acceptance contract not met: r2 unmet; 1 unchecked (judge: 2 call(s))"},
        {"fc": "acceptance", "verdict": _SETTLEMENT["verdict"], "items": _SETTLEMENT["items"]},
        {"fc": "final", "text": "Built the board."},
    )
    report = build_run_report(
        goal=GOAL,
        transcript=transcript,
        changed_files=["index.html"],
        returncode=0,
        ok=True,
        outcome="completed",
        reason="1 file(s) changed",
    )
    rows = {row["criterion"]: row for row in report["rubric_mapping"]}
    assert "the specific requirements stated in this goal" not in rows, list(rows)
    assert rows["Drag cards between columns with the mouse"]["status"] == "met"
    assert "090320" in rows["Drag cards between columns with the mouse"]["evidence"]
    assert rows["A dark/light toggle in the header that also persists"]["status"] == "not_met"
    assert "reload" in rows["A dark/light toggle in the header that also persists"]["evidence"]
    assert rows["Delete a card with a small x on it"]["status"] == "unverified"
    # Machine items are the engine's business and already appear as validations.
    assert "changed sources parse" not in rows
    # The run row stays first and still grades the run, not the goal.
    assert report["rubric_mapping"][0]["criterion"] == "the run finished without error"


def test_without_a_settlement_the_prose_fallback_still_says_nothing_was_extracted() -> None:
    transcript = _transcript({"fc": "final", "text": "Built the board."})
    report = build_run_report(
        goal=GOAL,
        transcript=transcript,
        changed_files=["index.html"],
        returncode=0,
        ok=True,
        outcome="completed",
        reason="1 file(s) changed",
    )
    criteria = [row["criterion"] for row in report["rubric_mapping"]]
    assert "the specific requirements stated in this goal" in criteria
