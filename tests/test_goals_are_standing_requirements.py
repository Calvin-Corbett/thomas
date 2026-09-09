"""A goal is a standing requirement: every turn in the project is held to it (2026-09-05).

You asked for goals ("you can make goals") next to the requests that come
and go. The acceptance contract already holds each turn to the items it
derives from that turn's words; a goal is the item that does not go away
until someone closes it. Goals live with the project (``.thomas/goals.json``),
Thomas can add, list and close them with a tool, and the contract's learned
items carry every open goal as a judged requirement on every turn.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from thomas.core import acceptance_contract as ac
from thomas.core import goal_book
from thomas.core.acceptance_learning import load_learned
from thomas.tools.goals import GoalAddTool, GoalDoneTool, GoalListTool


def _run(tool, args):
    return asyncio.run(tool.execute(args))


def test_goals_persist_with_the_project(tmp_path: Path) -> None:
    first = goal_book.add_goal(tmp_path, "Every race must end on a results screen with six finishers.")
    second = goal_book.add_goal(tmp_path, "No external fonts or CDN scripts.")
    assert [g["id"] for g in goal_book.open_goals(tmp_path)] == [first["id"], second["id"]]
    stored = json.loads((tmp_path / ".thomas" / "goals.json").read_text(encoding="utf-8"))
    assert [g["text"] for g in stored["goals"]] == [first["text"], second["text"]]

    assert goal_book.close_goal(tmp_path, first["id"], note="verified in generation 7") is True
    assert [g["id"] for g in goal_book.open_goals(tmp_path)] == [second["id"]]
    assert goal_book.close_goal(tmp_path, "g-nope") is False
    closed = [g for g in goal_book.list_goals(tmp_path, include_done=True) if g["done"]]
    assert closed and closed[0]["note"] == "verified in generation 7"


def test_open_goals_are_judged_requirements_on_every_turn(tmp_path: Path) -> None:
    goal_book.add_goal(tmp_path, "Every race must end on a results screen with six finishers.")
    done = goal_book.add_goal(tmp_path, "Old goal, already closed.")
    goal_book.close_goal(tmp_path, done["id"])

    items = ac.build_contract("Add a pause menu.", tmp_path, learned=load_learned(tmp_path))
    goals = [it for it in items if it.source == "goal"]
    assert len(goals) == 1, [it.description for it in items]
    assert goals[0].kind == ac.KIND_REQUIREMENT and not goals[0].machine
    assert goals[0].item_id.startswith("goal:")
    assert "Every race must end on a results screen" in goals[0].description
    assert "Standing goal" in goals[0].description


def test_the_tools_add_list_and_close(tmp_path: Path) -> None:
    added = _run(GoalAddTool(tmp_path), {"text": "Keep the build under 30 KB of JavaScript."})
    assert added.ok, added.error
    listed = _run(GoalListTool(tmp_path), {})
    assert listed.ok and "30 KB" in str(listed.data)
    goal_id = goal_book.open_goals(tmp_path)[0]["id"]
    closed = _run(GoalDoneTool(tmp_path), {"id": goal_id, "note": "measured 24 KB"})
    assert closed.ok, closed.error
    assert goal_book.open_goals(tmp_path) == []
    again = _run(GoalDoneTool(tmp_path), {"id": goal_id})
    assert not again.ok


def test_empty_and_duplicate_goals_are_refused(tmp_path: Path) -> None:
    assert not _run(GoalAddTool(tmp_path), {"text": "   "}).ok
    assert _run(GoalAddTool(tmp_path), {"text": "Ship it green."}).ok
    assert not _run(GoalAddTool(tmp_path), {"text": "ship it green."}).ok  # same goal, different case
    assert len(goal_book.open_goals(tmp_path)) == 1


# Generation 8 (2026-09-05, run-T72TxzcTQohwX9T8): Thomas read "[open]" as "unmet",
# closed both goals to satisfy the hold, then re-added them as g3/g4 when it saw
# that a standing goal must stay open. The words were the bug: a goal that holds
# is *standing*, not *done*, and restating a retired goal reopens it.


def test_restating_a_retired_goal_reopens_it_instead_of_minting_a_duplicate(tmp_path: Path) -> None:
    first = goal_book.add_goal(tmp_path, "The game must never load anything from the internet.")
    assert goal_book.close_goal(tmp_path, first["id"], note="no longer wanted") is True
    again = goal_book.add_goal(tmp_path, "the game must never load anything from the internet.")
    assert again["id"] == first["id"]
    assert again["done"] is False and again["note"] == "" and again["closed_at"] is None
    assert [g["id"] for g in goal_book.list_goals(tmp_path, include_done=True)] == [first["id"]]


def test_the_words_say_standing_so_a_goal_that_holds_is_not_closed(tmp_path: Path) -> None:
    kept = goal_book.add_goal(tmp_path, "Every race must end on a results screen.")
    gone = goal_book.add_goal(tmp_path, "Old goal, retired.")
    goal_book.close_goal(tmp_path, gone["id"], note="dropped by request")

    listed = str(_run(GoalListTool(tmp_path), {"include_done": True}).data)
    assert f"{kept['id']} [standing]" in listed and f"{gone['id']} [retired]" in listed
    assert "[open]" not in listed and "[done]" not in listed

    row = goal_book.contract_rows(tmp_path)[0]
    assert row["description"].startswith("Standing goal")
    assert "stays open" in row["description"] and "this turn" in row["description"]

    assert "retire" in GoalDoneTool.description.lower()
    assert "not because it holds" in GoalDoneTool.description.lower()
    assert "stays open" in GoalAddTool.description.lower()


def test_the_goal_tools_are_classified_for_chat() -> None:
    """Registered server-wide since the goals batch but never classified, so the
    core-surface policy test was red and Chat withheld them at any reduced
    access level. Adding and retiring a goal writes the project's goal book;
    listing only reads it."""
    from thomas.server import chat_tool_policy_model as policy

    assert {"goal.add", "goal.done"} <= policy._WRITE_TOOLS
    assert "goal.list" in policy._SAFE_READ_TOOLS
