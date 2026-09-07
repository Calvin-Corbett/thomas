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
        {
            "label": "Booked today",
            "component": "div",
            "uiId": "work.dash.metric.1",
            "specKind": "metric",
            "specId": "1",
        },
    ]


def test_a_theme_token_for_a_stock_key_is_a_theme_change_and_an_unknown_key_is_explained(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("THOMAS_OVERLAY_DIR", str(tmp_path / "overlay"))
    reply = json.dumps(
        {
            "layout": [],
            "dashboard": [],
            "unsupported": [],
            "theme": {
                "tokens": {
                    "--c-accent": "#2ecc71",
                    "--c-nope": "#000000",
                    "--c-bg": "url(x)",
                    "--font-head": '"Playfair Display", serif',
                },
                "identity": {"name": "Otto", "bogus": "x", "tagline": "x", "title": ""},
            },
        }
    )
    plan = _run(reply, monkeypatch=monkeypatch, instruction="make the accent green everywhere and call yourself Otto")
    assert plan["theme"]["theme"] == "nebula"
    assert plan["theme"]["tokens"] == {"--c-accent": "#2ecc71", "--font-head": '"Playfair Display", serif'}, (
        "double-quoted font stacks are values, not markup"
    )
    assert plan["theme"]["identity"] == {"name": "Otto"}
    reasons = {row["address"]: row["reason"] for row in plan["theme"]["rejected"]}
    assert "not a design token" in reasons["--c-nope"] and "style guard" in reasons["--c-bg"]
    assert (
        "not a surface" in reasons["identity:bogus"]
        and "reserved" in reasons["identity:tagline"]
        and "1-80" in reasons["identity:title"]
    )
    assert not (tmp_path / "overlay").exists(), "the server never writes the overlay from a redesign"


def test_a_theme_value_that_matches_what_is_in_effect_is_not_a_change(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from thomas.server.overlay import stock_tokens

    monkeypatch.setenv("THOMAS_OVERLAY_DIR", str(tmp_path / "overlay"))
    stock_accent = stock_tokens.load_stock()["nebula"]["--c-accent"]
    reply = json.dumps(
        {"layout": [], "dashboard": [], "unsupported": [], "theme": {"tokens": {"--c-accent": stock_accent.upper()}}}
    )
    plan = _run(reply, monkeypatch=monkeypatch)
    assert plan["theme"]["tokens"] == {}
    assert "already in effect" in plan["theme"]["rejected"][0]["reason"]


def test_the_prompt_lists_the_active_themes_tokens_and_honours_the_theme_sent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("THOMAS_OVERLAY_DIR", str(tmp_path / "overlay"))
    fake = _install(monkeypatch, json.dumps({"layout": [], "dashboard": [], "unsupported": []}))
    payload = {"instruction": "warmer", "targets": _targets(), "theme": "sandstone"}
    plan, error = asyncio.run(redesign.redesign_from_selection(ROOT, "", payload, job_context=None))
    assert error == "" and plan["theme"]["theme"] == "sandstone"
    assert "DESIGN TOKENS (theme sandstone" in fake.prompts[0] and "--c-accent=" in fake.prompts[0]
    assert '"theme": {"tokens"' in fake.prompts[0]


def test_the_in_effect_baseline_follows_an_overlay_themes_parent(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from thomas.server.overlay import manifest as m
    from thomas.server.overlay import render, stock_tokens

    monkeypatch.setenv("THOMAS_OVERLAY_DIR", str(tmp_path / "overlay"))
    stock = stock_tokens.load_stock()
    m.append(
        [
            {
                "op": "set",
                "kind": "theme",
                "address": "theme:paper",
                "value": {"label": "Paper", "derives_from": "light", "color_scheme": "light"},
            },
            {"op": "set", "kind": "token", "address": "token:light:--c-bg", "value": "#fefefe"},
            {"op": "set", "kind": "token", "address": "token:paper:--c-accent", "value": "#123456"},
        ],
        {"actor": "test", "instruction": "seed", "targets": []},
        {"thomas_version": "0", "git": None, "web_build": None, "tokens_sha1": "0" * 40},
        path=tmp_path / "overlay" / "manifest.json",
        stock=stock,
    )
    render.invalidate()
    name, values = redesign._tokens_in_effect("paper")
    assert name == "paper"
    assert values["--c-bg"] == "#fefefe", "the parent's overlay record is in effect"
    assert values["--c-accent"] == "#123456", "the theme's own record wins"
    assert values["--c-text"] == stock["light"]["--c-text"], "unrecorded keys come from the stock parent, not nebula"
    assert redesign._tokens_in_effect("light")[1]["--c-bg"] == "#fefefe"


def test_the_code_brief_tells_thomas_to_change_his_own_source_and_keeps_the_overlay_as_the_browser_override() -> None:
    """Since 2026-09-06 (the owner: Redesign is "edit this thing however I say" and
    "thomas must be able to change every single thing about him and it work") the
    brief is a directive to change the stock files under thomas/server/web/; the
    overlay stays what it is, a per-browser override, not the persistence story."""
    brief = redesign.code_thread_prompt("make the sidebar darker", _targets(), "chat")
    assert "Change Thomas's own UI" in brief and "thomas/server/web/" in brief
    assert "make the sidebar darker" in brief
    assert "Verify it in the browser" in brief
    assert "already applies on every tab and every reload" not in brief


def _run(
    reply: str,
    *,
    targets: list[dict[str, Any]] | None = None,
    job: dict[str, Any] | None = None,
    monkeypatch: pytest.MonkeyPatch | None = None,
    instruction: str = "make these clearer",
) -> dict[str, Any]:
    assert monkeypatch is not None
    _install(monkeypatch, reply)
    payload = {"instruction": instruction, "targets": targets if targets is not None else _targets()}
    context = {"job": job, "workflows": []} if job is not None else None
    plan, error = asyncio.run(redesign.redesign_from_selection(ROOT, "", payload, job_context=context))
    assert error == "", error
    assert plan is not None
    return plan


def test_a_real_content_edit_counts_as_one_change(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = json.dumps(
        {
            "layout": [],
            "dashboard": [{"target": 0, "op": "update", "patch": {"value": "5", "tone": "bad"}}],
            "unsupported": [{"target": 1, "reason": "nothing was asked about this one"}],
        }
    )
    plan = _run(reply, job={"dashboard": _dashboard()}, monkeypatch=monkeypatch)

    assert plan["dashboard"]["changed"] == 1
    assert plan["dashboard"]["dashboard"]["metrics"][0]["value"] == "5"
    assert [row["target_index"] for row in plan["unsupported"]] == [1]


def test_a_patch_that_matches_what_was_already_there_is_not_a_change(monkeypatch: pytest.MonkeyPatch) -> None:
    # The exact failure mode of the old button: re-derive the same design and
    # present it as work done.
    reply = json.dumps(
        {
            "layout": [],
            "dashboard": [{"target": 0, "op": "update", "patch": {"value": "2", "tone": "neutral"}}],
            "unsupported": [],
        }
    )
    plan = _run(reply, job={"dashboard": _dashboard()}, monkeypatch=monkeypatch)

    assert plan["dashboard"]["changed"] == 0
    assert plan["dashboard"]["applied"] == []
    reasons = [row["reason"] for row in plan["unsupported"]]
    assert any("already there" in reason for reason in reasons), reasons


def test_schema_normalisation_alone_never_counts_as_a_change(monkeypatch: pytest.MonkeyPatch) -> None:
    # A stored spec missing optional fields gets them filled in by validation.
    # That is not something the user asked for and must not be scored.
    sparse = {"tabs": [{"id": "overview", "label": "Overview"}], "metrics": [{"label": "Late loads", "value": "2"}]}
    reply = json.dumps(
        {
            "layout": [],
            "dashboard": [{"target": 0, "op": "update", "patch": {"value": "2"}}],
            "unsupported": [],
        }
    )
    plan = _run(reply, job={"dashboard": sparse}, monkeypatch=monkeypatch)

    assert plan["dashboard"]["changed"] == 0


def test_content_edits_without_an_open_job_are_explained_not_dropped(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = json.dumps(
        {
            "layout": [],
            "dashboard": [{"target": 0, "op": "update", "patch": {"value": "5"}}],
            "unsupported": [],
        }
    )
    plan = _run(reply, monkeypatch=monkeypatch)  # no job context

    assert plan["dashboard"]["changed"] == 0
    assert len(plan["unsupported"]) == 1
    assert "open job" in plan["unsupported"][0]["reason"]


def test_a_layout_edit_on_an_unaddressable_element_is_explained(monkeypatch: pytest.MonkeyPatch) -> None:
    targets = [{"label": "Some text", "component": "span", "uiId": "", "specKind": "", "specId": ""}]
    reply = json.dumps(
        {
            "layout": [{"target": 0, "style": {"color": "#ff0000"}}],
            "dashboard": [],
            "unsupported": [],
        }
    )
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
    reply = json.dumps(
        {
            "layout": [
                {
                    "target": 0,
                    "style": {
                        "color": "#8b8cff",
                        "background": "url(https://evil.example/x.png)",
                        "fontSize": "18px; position: fixed",
                        "position": "fixed",
                    },
                }
            ],
            "dashboard": [],
            "unsupported": [],
        }
    )
    plan = _run(reply, monkeypatch=monkeypatch)

    assert plan["layout"][0]["style"] == {"color": "#8b8cff"}


def test_invented_target_indexes_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = json.dumps(
        {
            "layout": [{"target": 99, "style": {"color": "red"}}],
            "dashboard": [{"target": -1, "op": "update", "patch": {"value": "9"}}],
            "unsupported": [{"target": 42, "reason": "made up"}],
        }
    )
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

    plan, error = asyncio.run(
        redesign.redesign_from_selection(ROOT, "", {"instruction": "", "targets": _targets()}, job_context=None)
    )
    assert plan is None and error == "no instruction was given"

    plan, error = asyncio.run(
        redesign.redesign_from_selection(ROOT, "", {"instruction": "hi", "targets": []}, job_context=None)
    )
    assert plan is None and error == "nothing was selected"
    assert fake.prompts == []


def test_the_prompt_tells_the_model_which_channel_each_target_supports(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, json.dumps({"layout": [], "dashboard": [], "unsupported": []}))
    asyncio.run(
        redesign.redesign_from_selection(
            ROOT,
            "",
            {
                "instruction": "make it blue",
                "targets": [
                    {"label": "Tile", "uiId": "work.dash.metric.0", "specKind": "metric", "specId": "0"},
                    {"label": "Loose text", "uiId": "", "specKind": "", "specId": ""},
                ],
            },
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
    targets = [
        {
            "label": "One line of text",
            "component": "p",
            "uiId": "",
            "ownerUiId": "work.job.rail",
            "specKind": "",
            "specId": "",
        }
    ]
    reply = json.dumps({"layout": [{"target": 0, "style": {"color": "#ff0000"}}], "dashboard": [], "unsupported": []})
    fake = _install(monkeypatch, reply)
    plan, error = asyncio.run(
        redesign.redesign_from_selection(
            ROOT, "", {"instruction": "make this red", "targets": targets}, job_context=None
        )
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
