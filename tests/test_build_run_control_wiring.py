"""Build wires its run controls into the lead, its helpers, its pass clock and its event stream.

A run the server launched with a control folder gets: a lead that holds on pause and reads its inbox, plan.update and
ask.user, helpers with their own inboxes, a pass clock that stops while held, file paths and line counts on file-tool
events, and a time on every event. A run without the folder is what it was.
"""

from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path
from typing import Any

import pytest

from tests.test_build_agent_team import OfflineClient, runtime  # noqa: F401
from thomas.core.events import AgentEvent, EventType
from thomas.forge.anvil import build_agent_team as team
from thomas.forge.anvil import dispatch_agent_loop as dispatch
from thomas.forge.anvil import run_control
from thomas.forge.anvil.dispatch_agent_loop_translator import _AgentLoopForgeTranslator
from thomas.forge.anvil.forge_code_http_stream import line_to_sse_payload
from thomas.forge.anvil.forge_event_stream import _default_emit
from thomas.forge.anvil.run_control import RunControl


@pytest.mark.asyncio
async def test_the_lead_and_its_helpers_get_holds_inboxes_and_the_lead_tools(monkeypatch, tmp_path, runtime):
    events: list[dict[str, Any]] = []
    control = RunControl(tmp_path / "control", emit=events.append)
    lead_tools = dispatch.build_lead_tools(control, events.append)
    seen: dict[str, Any] = {}

    class Loop:
        def __init__(self, config, llm, tools, **kwargs):
            self.tools = tools

        async def run(self, prompt, **kwargs):
            if self.tools.get("task.spawn") is not None:  # the lead
                seen["lead"] = self
                assert self.tools.get("plan.update") is lead_tools[0]
                assert self.tools.get("ask.user") is lead_tools[1]
                await self.tools.execute("task.spawn", {"title": "Reviewer", "instructions": "Inspect it"})
                yield AgentEvent.agent_done("Lead finished", iterations=1, tool_calls=1)
                return
            seen["child"] = self
            seen["listening_while_child_ran"] = run_control.listening_agents(control.directory)
            yield AgentEvent.agent_done("Looks fine", iterations=1, tool_calls=0)

    monkeypatch.setattr("thomas.agent.loop.AgentLoop", Loop)
    monkeypatch.setattr(team, "AgentLoop", Loop)
    rc, final = await dispatch._agent_loop_pass_async(
        "Build a page",
        str(tmp_path),
        900,
        events.append,
        profile="selected",
        oauth_access_token="fixture-token",
        control=control,
        lead_tools=lead_tools,
    )
    assert rc == 0 and final == "Lead finished"
    lead, child = seen["lead"], seen["child"]
    assert lead.run_hold == control.hold and child.run_hold == control.hold
    assert lead._message_queue.agent_id == run_control.LEAD
    assert child._message_queue.agent_id.startswith("child_")
    assert seen["listening_while_child_ran"] == [child._message_queue.agent_id]
    assert run_control.listening_agents(control.directory) == []  # the helper stopped listening when it ended
    # ask.user may wait 20 minutes for you, past an ordinary tool's 10-minute cap. Each deadline is one a pause
    # moves out while a call is already waiting on it (run_control.HeldDeadline).
    deadlines = lead._tool_deadlines
    assert all(
        isinstance(deadlines[name], run_control.HeldDeadline) for name in ("task.spawn", "task.team", "ask.user")
    )
    assert deadlines["ask.user"]() >= deadlines["task.spawn"]() + run_control.ASK_WAIT_S


@pytest.mark.asyncio
async def test_a_pass_without_controls_sets_no_hook(monkeypatch, tmp_path, runtime):
    seen = []

    class Loop:
        def __init__(self, config, llm, tools, **kwargs):
            self.tools = tools
            seen.append(self)

        async def run(self, *_args, **_kwargs):
            yield AgentEvent.agent_done("Done", iterations=1, tool_calls=0)

    monkeypatch.setattr("thomas.agent.loop.AgentLoop", Loop)
    await dispatch._agent_loop_pass_async(
        "Build a page", str(tmp_path), 900, lambda _e: None, profile="selected", oauth_access_token="fixture-token"
    )
    [lead] = seen
    assert not hasattr(lead, "run_hold") and not hasattr(lead, "_message_queue")
    assert lead.tools.get("plan.update") is None and lead.tools.get("ask.user") is None
    assert set(lead._tool_deadlines) == {"task.spawn", "task.team"}


def test_a_pause_does_not_spend_the_pass_wall_clock(tmp_path):
    control = RunControl(tmp_path / "control", emit=lambda _e: None)

    class HeldAgent:
        async def run(self, *_args, **_kwargs):
            control.clock.hold()  # you paused: held for longer than the whole pass limit
            await asyncio.sleep(0.4)
            control.clock.release()
            yield AgentEvent.agent_done("Finished after the pause", iterations=1, tool_calls=0)

    held = _AgentLoopForgeTranslator(lambda _e: None)
    asyncio.run(
        dispatch._translate_agent_stream(
            HeldAgent(),
            "go",
            timeout=0.2,
            tools_policy="auto",
            translator=held,
            clock=control.new_pass_clock(),
        )
    )
    assert held.rc == 0 and held.final_text == "Finished after the pause"

    unheld = _AgentLoopForgeTranslator(lambda _e: None)

    class SlowAgent:
        async def run(self, *_args, **_kwargs):
            await asyncio.sleep(0.4)
            yield AgentEvent.agent_done("never", iterations=1, tool_calls=0)

    asyncio.run(
        dispatch._translate_agent_stream(SlowAgent(), "go", timeout=0.2, tools_policy="auto", translator=unheld)
    )
    assert unheld.rc == dispatch.PASS_WALL_CLOCK_RC  # the same wait without a hold still ends at the clock


def _dispatch(tmp_path: Path, runner: Any) -> Any:
    return dispatch.dispatch_via_agent_loop(
        "Build a page",
        cwd=tmp_path,
        dry_run=False,
        runner=runner,
        emit=lambda _e: None,
        verify=False,
        token_check=lambda: True,
        allow_without_history=True,
    )


def test_the_lead_listens_for_the_whole_run_and_the_folder_is_never_inherited(tmp_path, monkeypatch):
    folder = tmp_path / "control" / "run-1"
    monkeypatch.setenv(run_control.CONTROL_DIR_ENV, str(folder))
    seen: dict[str, Any] = {}

    def runner(prompt, cwd, timeout, emit):  # noqa: ANN001, ANN202
        seen["prompt"] = prompt
        seen["listening"] = run_control.listening_agents(folder)
        seen["env"] = run_control.configured()
        return 0, "done"

    (tmp_path / "project").mkdir()
    _dispatch(tmp_path / "project", runner)
    assert seen["listening"] == [run_control.LEAD]
    assert seen["env"] is False  # claimed before any tool could start a process that inherits it
    assert "plan.update" in seen["prompt"] and "ask.user" in seen["prompt"]
    assert run_control.listening_agents(folder) == []  # the lead stopped listening when the run ended


def test_a_run_without_a_control_folder_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv(run_control.CONTROL_DIR_ENV, raising=False)
    seen: dict[str, Any] = {}

    def runner(prompt, cwd, timeout, emit):  # noqa: ANN001, ANN202
        seen["prompt"] = prompt
        return 0, "done"

    (tmp_path / "project").mkdir()
    _dispatch(tmp_path / "project", runner)
    assert "plan.update" not in seen["prompt"] and "ask.user" not in seen["prompt"]


def _feed_call(translator: _AgentLoopForgeTranslator, tool_id: str, name: str, args: dict[str, Any], result: str):
    translator.feed(EventType.TOOL_CALL_START.value, {"tool_id": tool_id, "tool_name": name})
    translator.feed(EventType.TOOL_CALL_ARGS_DELTA.value, {"tool_id": tool_id, "delta": json.dumps(args)})
    translator.feed(EventType.TOOL_CALL_END.value, {"tool_id": tool_id, "arguments": ""})
    translator.feed(
        EventType.TOOL_RESULT.value,
        {"tool_id": tool_id, "tool_name": name, "result": result, "ok": True, "arguments": args},
    )


def test_file_tool_events_carry_the_path_and_the_lines_they_changed(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "old.js").write_text("one\n", encoding="utf-8")
    events: list[dict[str, Any]] = []
    translator = _AgentLoopForgeTranslator(events.append, root=tmp_path)
    _feed_call(translator, "a", "fs.read_file", {"path": "src/old.js"}, "one")
    _feed_call(translator, "b", "fs.write_file", {"path": "src/new.js", "content": "a\nb\nc\n"}, "Wrote 6 chars")
    _feed_call(translator, "c", "fs.write_file", {"path": "src/old.js", "content": "x\ny\n"}, "Wrote 4 chars")
    _feed_call(
        translator,
        "d",
        "diff.create",
        {"path": str(tmp_path / "src" / "old.js"), "old_str": "x", "new_str": "x\nz"},
        "Replaced 1 line(s) with 2 line(s) in src/old.js",
    )
    _feed_call(translator, "e", "plan.update", {"items": []}, "Plan shown")
    started = [e for e in events if e["fc"] == "tool_started"]
    results = {e["name"]: e for e in events if e["fc"] == "tool_result"}
    assert [e.get("path") for e in started] == ["src/old.js", "src/new.js", "src/old.js", "src/old.js", None]
    read = next(e for e in events if e["fc"] == "tool_result" and e["name"] == "fs.read_file")
    assert read["path"] == "src/old.js" and "added" not in read
    writes = [e for e in events if e["fc"] == "tool_result" and e["name"] == "fs.write_file"]
    assert (writes[0]["path"], writes[0]["added"], writes[0]["removed"]) == ("src/new.js", 3, 0)
    assert "added" not in writes[1]  # over an existing file the true difference is unknown: no guess
    edit = results["diff.create"]
    assert (edit["path"], edit["added"], edit["removed"]) == ("src/old.js", 2, 1)
    # The lead's own tools touch nothing in the project.
    assert results["plan.update"]["access"] == "read" and "path" not in results["plan.update"]


def test_every_wire_line_carries_a_time(monkeypatch):
    out = io.BytesIO()
    monkeypatch.setattr(sys, "stdout", type("Out", (), {"buffer": out})())
    _default_emit({"fc": "say", "text": "hi"})
    _default_emit({"fc": "meta", "text": "kept", "ts": 7})
    first, second = (json.loads(line) for line in out.getvalue().decode("utf-8").splitlines())
    assert isinstance(first["ts"], int) and first["ts"] > 1_700_000_000_000
    assert second["ts"] == 7


def test_the_sse_frame_keeps_the_new_fields_and_validates_them():
    plan = {
        "fc": "plan",
        "text": "1 of 2 done",
        "ts": 1700000000000,
        "items": [
            {"id": "s1", "text": "Read", "status": "completed", "owner": "", "started_at": 1, "done_at": 2},
            {"id": "s2", "text": "Write", "status": "weird", "owner": "Wirer", "started_at": True, "done_at": None},
            {"text": ""},
            "junk",
        ],
    }
    frame = line_to_sse_payload(json.dumps(plan))
    assert frame["kind"] == "plan" and frame["ts"] == 1700000000000
    assert frame["items"] == [
        {"id": "s1", "text": "Read", "status": "completed", "owner": "", "started_at": 1, "done_at": 2},
        {"id": "s2", "text": "Write", "status": "pending", "owner": "Wirer", "started_at": None, "done_at": None},
    ]
    ask = {
        "fc": "ask",
        "text": "Which?",
        "question_id": "q-1",
        "question": "Which?",
        "allow_free_text": True,
        "options": [{"label": "A", "description": "a", "recommended": True}, {"label": ""}] + [{"label": "x"}] * 9,
    }
    frame = line_to_sse_payload(json.dumps(ask))
    assert frame["question_id"] == "q-1" and frame["question"] == "Which?" and frame["allow_free_text"] is True
    assert frame["options"][0] == {"label": "A", "description": "a", "recommended": True}
    assert len(frame["options"]) == 5  # at most six looked at, the blank one dropped
    steer = line_to_sse_payload(json.dumps({"fc": "steering", "text": "blue", "steer_id": "m-1", "agent_id": "c1"}))
    assert (steer["steer_id"], steer["agent_id"]) == ("m-1", "c1")
    answered = line_to_sse_payload(json.dumps({"fc": "answered", "text": "A", "question_id": "q-1", "answer": "A"}))
    assert answered["answer"] == "A"
    resumed = line_to_sse_payload(json.dumps({"fc": "resumed", "text": "Resumed", "paused_ms": 1200}))
    assert resumed["paused_ms"] == 1200
    edit = line_to_sse_payload(
        json.dumps({"fc": "tool_result", "text": "ok", "path": "a/b.js", "added": 3, "removed": -1, "ts": "soon"})
    )
    assert edit["path"] == "a/b.js" and edit["added"] == 3 and "removed" not in edit and "ts" not in edit
    # Acceptance items are not a plan: they never pass as plan steps.
    acceptance = line_to_sse_payload(json.dumps({"fc": "acceptance", "items": [{"text": "x", "status": "pending"}]}))
    assert "items" not in acceptance
    # A live Ran / Checked row names the command and the check, as a saved row does, cut to one row.
    ran = line_to_sse_payload(
        json.dumps(
            {"fc": "tool", "name": "shell.exec", "text": "3 passing", "command": "x" * 400, "check": "pytest -q"}
        )
    )
    assert ran["command"] == "x" * 300 and ran["check"] == "pytest -q"
    assert "command" not in line_to_sse_payload(json.dumps({"fc": "tool", "text": "t", "command": 7}))


def test_the_conversation_list_says_how_each_tasks_newest_run_ended():
    """The Build sidebar marks a task Verified / Stopped / Needs attention from its newest run."""
    from thomas.forge.anvil.forge_code_store import _summarize

    def outcome(*turns):
        return _summarize({"id": "c", "turns": list(turns)})["last_outcome"]

    assert outcome({"role": "agent", "ok": True, "outcome": "conversation"}, {"role": "user"}) == "conversation"
    assert (
        outcome(
            {"role": "agent", "ok": False, "outcome": "failed"}, {"role": "agent", "ok": True, "outcome": "stopped"}
        )
        == "stopped"
    )
    assert outcome({"role": "agent", "ok": True}) == "completed"  # written before the outcome word was kept
    assert outcome({"role": "agent", "ok": False}) == "failed"
    assert outcome({"role": "user"}) is None
    # A chat-delegated build writes its turn as it runs (upsert_run_transcript): ok until a failure ends it, with no
    # outcome and no exit code. Still working is not Verified, so an ok one gets no mark; a failed one is failed.
    assert outcome({"role": "agent", "ok": True, "returncode": None}) is None
    assert outcome({"role": "agent", "ok": False, "returncode": None}) == "failed"
    assert outcome({"role": "agent", "ok": True, "returncode": 0}) == "completed"


def test_a_chat_delegated_build_still_running_is_not_listed_as_verified(tmp_path):
    from thomas.forge.anvil import forge_code_store

    conv = forge_code_store.new_conversation(tmp_path, title="delegated build")
    forge_code_store.upsert_run_transcript(tmp_path, conv["id"], run_id="exec-1", transcript="working", ok=True)
    [row] = forge_code_store.list_conversations(tmp_path)
    assert row["last_outcome"] is None
    forge_code_store.upsert_run_transcript(tmp_path, conv["id"], run_id="exec-1", transcript="crashed", ok=False)
    [row] = forge_code_store.list_conversations(tmp_path)
    assert row["last_outcome"] == "failed"
