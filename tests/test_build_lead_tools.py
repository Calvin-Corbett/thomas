"""The Build lead's plan.update and ask.user (thomas/forge/anvil/build_lead_tools.py).

plan.update is the Steps card: every call is one ``plan`` event whose steps carry when each started and finished.
ask.user is the one way the lead stops to ask you something, with options and the one it recommends.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from thomas.forge.anvil import build_lead_tools, run_control
from thomas.forge.anvil.build_lead_tools import AskUserTool, PlanUpdateTool
from thomas.forge.anvil.run_control import RunControl


def _plan(tool: PlanUpdateTool, *steps: tuple[str, str], owner: str = "") -> Any:
    items = [{"text": text, "status": status, "owner": owner} for text, status in steps]
    return asyncio.run(tool.execute({"items": items}))


def test_a_plan_stamps_when_each_step_starts_and_finishes(monkeypatch) -> None:
    clock = iter([1000, 2000, 5000, 9000])
    monkeypatch.setattr(build_lead_tools, "now_ms", lambda: next(clock))
    events: list[dict[str, Any]] = []
    tool = PlanUpdateTool(events.append)

    first = _plan(tool, ("Read the page", "in_progress"), ("Write the styles", "pending"), ("Check it", "pending"))
    assert first.ok and "0 of 3 done" in first.data
    _plan(tool, ("Read the page", "completed"), ("Write the styles", "in_progress"), ("Check it", "pending"))
    _plan(tool, ("Read the page", "completed"), ("Write the styles", "completed"), ("Check it", "completed"))
    _plan(tool, ("Read the page", "completed"), ("Write the styles", "completed"), ("Check it", "completed"))

    assert [e["fc"] for e in events] == ["plan"] * 4
    assert [e["text"] for e in events] == ["0 of 3 done", "1 of 3 done", "3 of 3 done", "3 of 3 done"]
    read, styles, check = events[-1]["items"]
    assert (read["id"], styles["id"], check["id"]) == ("s1", "s2", "s3")  # a step keeps its id across updates
    assert (read["started_at"], read["done_at"]) == (1000, 2000)
    assert (styles["started_at"], styles["done_at"]) == (2000, 5000)
    # Straight from pending to done: no start time is invented, and the finish time stays the first one.
    assert (check["started_at"], check["done_at"]) == (None, 5000)
    assert events[0]["items"][1] == {
        "id": "s2",
        "text": "Write the styles",
        "status": "pending",
        "owner": "",
        "started_at": None,
        "done_at": None,
    }


def test_a_reworded_step_is_a_new_step_and_owner_names_the_helper() -> None:
    events: list[dict[str, Any]] = []
    tool = PlanUpdateTool(events.append)
    _plan(tool, ("Build the board", "in_progress"))
    _plan(tool, ("Build the game board", "in_progress"), owner="Wirer")
    [item] = events[-1]["items"]
    assert item["id"] == "s2" and item["owner"] == "Wirer"


@pytest.mark.parametrize(
    "args",
    [{}, {"items": []}, {"items": [{"text": "", "status": "pending"}]}, {"items": [{"text": "x", "status": "maybe"}]}],
)
def test_a_malformed_plan_is_refused_and_shows_nothing(args: dict[str, Any]) -> None:
    events: list[dict[str, Any]] = []
    result = asyncio.run(PlanUpdateTool(events.append).execute(args))
    assert not result.ok and events == []


def test_a_plan_holds_at_most_thirty_steps() -> None:
    items = [{"text": f"step {i}", "status": "pending"} for i in range(31)]
    assert not asyncio.run(PlanUpdateTool(lambda _e: None).execute({"items": items})).ok


class _FakeControl:
    def __init__(self, answer: str | None) -> None:
        self.answer = answer
        self.asked: dict[str, Any] = {}

    async def ask(self, question, options, *, allow_free_text, default=""):  # noqa: ANN001, ANN201
        self.asked = {"question": question, "options": options, "allow_free_text": allow_free_text, "default": default}
        return "q-1", self.answer


def _ask(control: Any, **args: Any) -> Any:
    return asyncio.run(AskUserTool(control).execute(args))


def test_ask_marks_the_recommended_option_and_returns_your_choice() -> None:
    control = _FakeControl("light")
    result = _ask(
        control,
        question="  Which   theme? ",
        options=[{"label": "Dark", "description": "Night"}, {"label": "Light"}],
        recommended="dark",
        allow_free_text=True,
    )
    assert result.ok and result.data == "The person chose: light"
    assert control.asked["question"] == "Which theme?"
    assert control.asked["options"] == [
        {"label": "Dark", "description": "Night", "recommended": True},
        {"label": "Light", "description": "", "recommended": False},
    ]
    assert control.asked["default"] == "Dark" and control.asked["allow_free_text"] is True


def test_ask_passes_on_free_text_and_says_when_no_answer_came() -> None:
    options = [{"label": "A"}, {"label": "B"}]
    free = _ask(_FakeControl("something else entirely"), question="Q?", options=options)
    assert free.data == "The person answered in their own words: something else entirely"
    silent = _ask(_FakeControl(None), question="Q?", options=options, recommended="B")
    assert silent.ok and silent.data.startswith("No answer in 20 minutes: go with the recommended option")
    unpicked = _ask(_FakeControl(None), question="Q?", options=options)
    assert "the option you judge best" in unpicked.data


@pytest.mark.parametrize(
    "args",
    [
        {"question": "", "options": [{"label": "A"}, {"label": "B"}]},
        {"question": "Q?", "options": [{"label": "A"}]},
        {"question": "Q?", "options": [{"label": str(i)} for i in range(5)]},
        {"question": "Q?", "options": [{"label": "A"}, {"label": "a"}]},
        {"question": "Q?", "options": [{"label": "A"}, {"description": "no label"}]},
    ],
)
def test_ask_refuses_a_question_that_is_not_a_real_choice(args: dict[str, Any]) -> None:
    control = _FakeControl("A")
    assert not _ask(control, **args).ok and control.asked == {}


def test_ask_end_to_end_through_the_control_folder(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(run_control, "HOLD_POLL_S", 0.02)
    events: list[dict[str, Any]] = []
    control = RunControl(tmp_path / "run", emit=events.append)
    [plan_tool, ask_tool] = build_lead_tools.lead_tools(control, events.append)
    assert (plan_tool.name, ask_tool.name) == ("plan.update", "ask.user")

    async def scenario() -> Any:
        asking = asyncio.create_task(
            ask_tool.execute({"question": "Ship it?", "options": [{"label": "Yes"}, {"label": "Not yet"}]})
        )
        await asyncio.sleep(0.06)
        [question] = run_control.question_rows(control.directory, running=True)
        run_control.submit_answer(control.directory, question["question_id"], "Not yet", running=True)
        return await asyncio.wait_for(asking, 1)

    result = asyncio.run(scenario())
    assert result.data == "The person chose: Not yet"
    assert [e["fc"] for e in events] == ["ask", "answered"]


def test_every_build_lead_prompt_says_to_reply_first_and_never_announce_an_empty_folder() -> None:
    from thomas.forge.anvil.bridge_prompts import compose_headless_prompt

    for tools in (False, True):
        prompt = compose_headless_prompt("build me pong", lead_tools_available=tools)
        assert "Reply first" in prompt
        assert "before any tool call" in prompt
        assert "or that it is empty or fresh" in prompt
        assert "acknowledge it in one short sentence first" in prompt
        assert "how to use it" in prompt


def test_the_lead_prompt_asks_for_progress_updates_on_long_jobs() -> None:
    from thomas.forge.anvil.bridge_prompts import compose_headless_prompt

    prompt = compose_headless_prompt("build me pong", lead_tools_available=True)
    assert "roughly how long it will take or the main stages" in prompt
    assert "Say in one short sentence when a stage finishes" in prompt
    assert "you will say when it is done" in prompt
    assert "never go silent for several tool calls" in prompt


def test_the_lead_prompt_is_light_and_a_greeting_gets_a_plain_reply() -> None:
    from thomas.forge.anvil.bridge_prompts import compose_headless_prompt

    prompt = compose_headless_prompt("hi")
    assert prompt.startswith("You are Thomas, a capable, direct builder")
    assert "A greeting, a question or small talk gets a short, plain reply: no tools, no plan" in prompt
    assert len(prompt) < 3300
