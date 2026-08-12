"""The redesign endpoint must never overstate what it changed.

The button this replaces posted an empty body and re-rolled the whole
dashboard, so "it did nothing" and "it succeeded" were indistinguishable from
the outside. These tests pin the opposite behaviour: every selected target
ends up either genuinely changed or explained, counts come from diffing the
spec after application, and a patch that matches what was already there is
reported as untouched rather than as a win.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from thomas.server.routes import ui_redesign_runtime as redesign

ROOT = Path(__file__).resolve().parents[1]


class _FakeLLM:
    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.prompts: list[str] = []

    async def chat(self, messages: list[dict[str, str]]) -> dict[str, str]:
        self.prompts.append(messages[0]["content"])
        return {"text": self.reply}


def _install(monkeypatch: pytest.MonkeyPatch, reply: str) -> _FakeLLM:
    fake = _FakeLLM(reply)
    monkeypatch.setattr(redesign, "_build_llm", lambda root, profile: fake)
    return fake


def _dashboard() -> dict[str, Any]:
    return {
        "headline": "Keep every load moving",
        "tabs": [{"id": "overview", "label": "Overview"}],
        "metrics": [
            {"label": "Late loads", "value": "2", "hint": "", "tone": "neutral", "tab": "overview"},
            {"label": "Booked today", "value": "7", "hint": "", "tone": "good", "tab": "overview"},
        ],
        "widgets": [],
        "sheets": [],
        "sections": [],
        "actions": [],
        "inboxes": [],
    }


def _targets() -> list[dict[str, Any]]:
    return [
        {"label": "Late loads", "component": "div", "uiId": "work.dash.metric.0", "specKind": "metric", "specId": "0"},
        {"label": "Booked today", "component": "div", "uiId": "work.dash.metric.1", "specKind": "metric", "specId": "1"},
    ]


def _run(reply: str, *, targets: list[dict[str, Any]] | None = None, job: dict[str, Any] | None = None,
         monkeypatch: pytest.MonkeyPatch | None = None, instruction: str = "make these clearer") -> dict[str, Any]:
    assert monkeypatch is not None
    _install(monkeypatch, reply)
    payload = {"instruction": instruction, "targets": targets if targets is not None else _targets()}
    context = {"job": job, "workflows": []} if job is not None else None
    plan, error = asyncio.run(redesign.redesign_from_selection(ROOT, "", payload, job_context=context))
    assert error == "", error
    assert plan is not None
    return plan


def test_a_real_content_edit_counts_as_one_change(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = json.dumps({
        "layout": [],
        "dashboard": [{"target": 0, "op": "update", "patch": {"value": "5", "tone": "bad"}}],
        "unsupported": [{"target": 1, "reason": "nothing was asked about this one"}],
    })
    plan = _run(reply, job={"dashboard": _dashboard()}, monkeypatch=monkeypatch)

    assert plan["dashboard"]["changed"] == 1
    assert plan["dashboard"]["dashboard"]["metrics"][0]["value"] == "5"
    assert [row["target_index"] for row in plan["unsupported"]] == [1]


def test_a_patch_that_matches_what_was_already_there_is_not_a_change(monkeypatch: pytest.MonkeyPatch) -> None:
    # The exact failure mode of the old button: re-derive the same design and
    # present it as work done.
    reply = json.dumps({
        "layout": [],
        "dashboard": [{"target": 0, "op": "update", "patch": {"value": "2", "tone": "neutral"}}],
        "unsupported": [],
    })
    plan = _run(reply, job={"dashboard": _dashboard()}, monkeypatch=monkeypatch)

    assert plan["dashboard"]["changed"] == 0
    assert plan["dashboard"]["applied"] == []
    reasons = [row["reason"] for row in plan["unsupported"]]
    assert any("already there" in reason for reason in reasons), reasons


def test_schema_normalisation_alone_never_counts_as_a_change(monkeypatch: pytest.MonkeyPatch) -> None:
    # A stored spec missing optional fields gets them filled in by validation.
    # That is not something the user asked for and must not be scored.
    sparse = {"tabs": [{"id": "overview", "label": "Overview"}], "metrics": [{"label": "Late loads", "value": "2"}]}
    reply = json.dumps({
        "layout": [],
        "dashboard": [{"target": 0, "op": "update", "patch": {"value": "2"}}],
        "unsupported": [],
    })
    plan = _run(reply, job={"dashboard": sparse}, monkeypatch=monkeypatch)

    assert plan["dashboard"]["changed"] == 0


def test_content_edits_without_an_open_job_are_explained_not_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = json.dumps({
        "layout": [],
        "dashboard": [{"target": 0, "op": "update", "patch": {"value": "5"}}],
        "unsupported": [],
    })
    plan = _run(reply, monkeypatch=monkeypatch)  # no job context

    assert plan["dashboard"]["changed"] == 0
    assert len(plan["unsupported"]) == 1
    assert "open job" in plan["unsupported"][0]["reason"]


def test_a_layout_edit_on_an_unaddressable_element_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    targets = [{"label": "Some text", "component": "span", "uiId": "", "specKind": "", "specId": ""}]
    reply = json.dumps({
        "layout": [{"target": 0, "style": {"color": "#ff0000"}}],
        "dashboard": [],
        "unsupported": [],
    })
    plan = _run(reply, targets=targets, monkeypatch=monkeypatch)

    assert plan["layout"] == []
    assert len(plan["unsupported"]) == 1
    assert "stable identity" in plan["unsupported"][0]["reason"]
    assert plan["unsupported"][0]["label"] == "Some text"


def test_a_layout_entry_carrying_no_actual_edit_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = json.dumps({"layout": [{"target": 0}], "dashboard": [], "unsupported": []})
    plan = _run(reply, monkeypatch=monkeypatch)

    assert plan["layout"] == []
    assert "not something a style or size edit can express" in plan["unsupported"][0]["reason"]


def test_unsafe_style_values_are_dropped_not_forwarded(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = json.dumps({
        "layout": [{"target": 0, "style": {
            "color": "#8b8cff",
            "background": "url(https://evil.example/x.png)",
            "fontSize": "18px; position: fixed",
            "position": "fixed",
        }}],
        "dashboard": [],
        "unsupported": [],
    })
    plan = _run(reply, monkeypatch=monkeypatch)

    assert plan["layout"][0]["style"] == {"color": "#8b8cff"}


def test_invented_target_indexes_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = json.dumps({
        "layout": [{"target": 99, "style": {"color": "red"}}],
        "dashboard": [{"target": -1, "op": "update", "patch": {"value": "9"}}],
        "unsupported": [{"target": 42, "reason": "made up"}],
    })
    plan = _run(reply, job={"dashboard": _dashboard()}, monkeypatch=monkeypatch)

    assert plan["layout"] == []
    assert plan["dashboard"]["changed"] == 0
    assert plan["unsupported"] == []


def test_unreadable_model_output_is_an_error_not_a_silent_success(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, "I have redesigned your dashboard!")
    plan, error = asyncio.run(
        redesign.redesign_from_selection(
            ROOT, "", {"instruction": "make it blue", "targets": _targets()}, job_context=None
        )
    )
    assert plan is None
    assert error == "model did not return a valid edit plan"


def test_an_empty_selection_or_instruction_never_reaches_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, "{}")

    plan, error = asyncio.run(redesign.redesign_from_selection(ROOT, "", {"instruction": "", "targets": _targets()}, job_context=None))
    assert plan is None and error == "no instruction was given"

    plan, error = asyncio.run(redesign.redesign_from_selection(ROOT, "", {"instruction": "hi", "targets": []}, job_context=None))
    assert plan is None and error == "nothing was selected"
    assert fake.prompts == []


def test_the_prompt_tells_the_model_which_channel_each_target_supports(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, json.dumps({"layout": [], "dashboard": [], "unsupported": []}))
    asyncio.run(
        redesign.redesign_from_selection(
            ROOT,
            "",
            {"instruction": "make it blue", "targets": [
                {"label": "Tile", "uiId": "work.dash.metric.0", "specKind": "metric", "specId": "0"},
                {"label": "Loose text", "uiId": "", "specKind": "", "specId": ""},
            ]},
            job_context=None,
        )
    )
    prompt = fake.prompts[0]
    assert "layout-addressable" in prompt
    assert "spec-addressable (metric 0)" in prompt
    assert "NOT addressable" in prompt
    assert "Never invent an index" in prompt


def test_a_style_never_lands_on_a_bigger_box_than_was_pointed_at(monkeypatch: pytest.MonkeyPatch) -> None:
    # A target that only sits INSIDE an addressable region carries no uiId of
    # its own. Borrowing the container's id would turn "make this line red"
    # into "make the whole sidebar red".
    targets = [{"label": "One line of text", "component": "p", "uiId": "", "ownerUiId": "work.job.rail",
                "specKind": "", "specId": ""}]
    reply = json.dumps({"layout": [{"target": 0, "style": {"color": "#ff0000"}}], "dashboard": [], "unsupported": []})
    fake = _install(monkeypatch, reply)
    plan, error = asyncio.run(
        redesign.redesign_from_selection(ROOT, "", {"instruction": "make this red", "targets": targets}, job_context=None)
    )

    assert error == ""
    assert plan["layout"] == []
    assert "stable identity" in plan["unsupported"][0]["reason"]
    # The model is told the container is a different thing, so it cannot
    # reasonably decide to restyle it instead.
    assert "which is NOT the same thing" in fake.prompts[0]


def test_removing_an_entry_is_a_real_change(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = json.dumps({"layout": [], "dashboard": [{"target": 1, "op": "remove"}], "unsupported": []})
    plan = _run(reply, job={"dashboard": _dashboard()}, monkeypatch=monkeypatch, instruction="get rid of this tile")

    assert plan["dashboard"]["changed"] == 1
    labels = [row["label"] for row in plan["dashboard"]["dashboard"]["metrics"]]
    assert labels == ["Late loads"]
