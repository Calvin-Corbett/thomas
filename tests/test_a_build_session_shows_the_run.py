"""A Build session has to show the run, not just exist.

The session now opens and Build lists it, but opening it showed nothing: the
worker's steps live in `task_bot_runtime` and the Activity panel renders from a
conversation turn's transcript, which nothing was writing. "You can open and
watch it" was half true -- you could open it.

The panel parses the transcript as one forge event per line,
``{"fc": <kind>, ...}`` (see `forge_event_stream`). The chat worker speaks a
different vocabulary -- `progress`, `text`, `tool_start`, `tool_output`,
`error`, `done`. This is the translation between them, and the tee that records
it while the run streams.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_projects as fcp
from thomas.forge.anvil import forge_code_store
from thomas.server.chat_delegation_build_session import open_build_session
from thomas.server.chat_delegation_build_transcript import (
    forge_line,
    remember_build_session,
    tee_to_build_session,
)


@pytest.fixture(autouse=True)
def _thomas_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "thomas-home"
    monkeypatch.setattr(fcp, "thomas_owned_root", lambda: home)
    return home


@pytest.fixture()
def catalog_root(tmp_path: Path) -> Path:
    root = tmp_path / "catalog"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _kind(line: str) -> str:
    return json.loads(line)["fc"]


# --- translation -------------------------------------------------------------


def test_a_tool_call_becomes_a_tool_event_with_its_name() -> None:
    line = forge_line({"type": "tool_start", "name": "fs.write_file"})
    assert line is not None
    payload = json.loads(line)
    assert payload["fc"] == "tool"
    assert payload["name"] == "fs.write_file"


def test_a_failed_tool_result_keeps_its_error_flag() -> None:
    """The panel styles an error result differently; losing the flag hides it."""
    line = forge_line({"type": "tool_output", "name": "browser.open", "text": "boom", "is_error": True})
    payload = json.loads(line)
    assert payload["fc"] == "tool_result"
    assert payload["is_error"] is True


def test_agent_prose_becomes_a_say_and_engine_status_becomes_meta() -> None:
    """`text` is the agent talking; `progress` is the engine reporting itself.

    Collapsing them would put engine chatter in the narrative panel.
    """
    assert _kind(forge_line({"type": "text", "text": "Writing index.html"})) == "say"
    assert _kind(forge_line({"type": "progress", "text": "Worker is running."})) == "meta"


def test_an_error_event_survives_as_an_error() -> None:
    assert _kind(forge_line({"type": "error", "error": "worker failed"})) == "error"


def test_events_with_nothing_to_show_are_dropped() -> None:
    """`done` and `model_runtime` are bookkeeping, not something to render."""
    assert forge_line({"type": "done"}) is None
    assert forge_line({"type": "model_runtime", "runtime": {}}) is None
    assert forge_line({"type": "text", "text": "   "}) is None


# --- the tee -----------------------------------------------------------------


async def _fake_events(_app, **_kwargs):
    yield {"type": "progress", "text": "Worker is running."}
    yield {"type": "text", "text": "Writing index.html"}
    yield {"type": "tool_start", "name": "fs.write_file"}
    yield {"type": "tool_output", "name": "fs.write_file", "text": "ok"}
    yield {"type": "done"}


@pytest.mark.asyncio
async def test_the_run_lands_in_the_session_you_were_told_to_watch(catalog_root: Path) -> None:
    session = open_build_session(
        specialist_id="coding",
        targets_live_repo=False,
        title="Build a countdown timer page",
        catalog_root=catalog_root,
    )
    assert session is not None
    remember_build_session("exec-watch", session["project_root"], session["conversation_id"])

    seen = [event async for event in tee_to_build_session(_fake_events)({}, execution_id="exec-watch")]

    # The stream is passed through untouched; teeing must not eat events.
    assert [e["type"] for e in seen] == ["progress", "text", "tool_start", "tool_output", "done"]

    conversation = forge_code_store.load_conversation(session["project_root"], session["conversation_id"])
    turns = [t for t in (conversation or {}).get("turns", []) if t.get("role") == "agent"]
    assert turns, "the run produced no agent turn, so Build has nothing to show"
    kinds = [_kind(line) for line in turns[-1]["transcript"].splitlines() if line.strip()]
    assert kinds == ["meta", "say", "tool", "tool_result"]


@pytest.mark.asyncio
async def test_a_run_with_no_build_session_streams_normally() -> None:
    """A document task has no session. The tee must be invisible, not fatal."""
    seen = [event async for event in tee_to_build_session(_fake_events)({}, execution_id="exec-unknown")]
    assert [e["type"] for e in seen] == ["progress", "text", "tool_start", "tool_output", "done"]


@pytest.mark.asyncio
async def test_a_broken_recorder_never_breaks_the_run(catalog_root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Rule 0. Losing the window into a run must not lose the run."""
    session = open_build_session(
        specialist_id="coding",
        targets_live_repo=False,
        title="Build a countdown timer page",
        catalog_root=catalog_root,
    )
    assert session is not None
    remember_build_session("exec-broken", session["project_root"], session["conversation_id"])

    def _boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(forge_code_store, "upsert_run_transcript", _boom)

    seen = [event async for event in tee_to_build_session(_fake_events)({}, execution_id="exec-broken")]
    assert [e["type"] for e in seen] == ["progress", "text", "tool_start", "tool_output", "done"]


# --- watching it happen, not reading it afterwards ---------------------------


def test_the_same_run_updates_one_turn_instead_of_stacking_them(catalog_root: Path) -> None:
    """Live progress means rewriting the run's turn, not appending a new one.

    Recording only at the end is what "you can open it" meant instead of "you can
    watch it": a run that takes twelve minutes shows an empty pane for twelve
    minutes. Writing as it goes is the point, and it has to land on ONE turn.
    """
    session = open_build_session(
        specialist_id="coding",
        targets_live_repo=False,
        title="Build a countdown timer page",
        catalog_root=catalog_root,
    )
    assert session is not None
    root, cid = session["project_root"], session["conversation_id"]

    forge_code_store.upsert_run_transcript(root, cid, run_id="exec-live", transcript='{"fc":"say"}', ok=True)
    forge_code_store.upsert_run_transcript(
        root, cid, run_id="exec-live", transcript='{"fc":"say"}\n{"fc":"tool","name":"fs.write_file"}', ok=True
    )

    conversation = forge_code_store.load_conversation(root, cid)
    turns = [t for t in (conversation or {}).get("turns", []) if t.get("role") == "agent"]
    assert len(turns) == 1, "a run in progress must not stack a turn per update"
    assert len(turns[0]["transcript"].splitlines()) == 2


@pytest.mark.asyncio
async def test_the_session_fills_in_while_the_run_is_still_going(catalog_root: Path) -> None:
    """The decisive one: a turn exists BEFORE the stream ends."""
    session = open_build_session(
        specialist_id="coding",
        targets_live_repo=False,
        title="Build a countdown timer page",
        catalog_root=catalog_root,
    )
    assert session is not None
    remember_build_session("exec-mid", session["project_root"], session["conversation_id"])

    mid_run_turns = -1

    async def _slow_events(_app, **_kwargs):
        nonlocal mid_run_turns
        yield {"type": "text", "text": "Writing greeting.html"}
        yield {"type": "tool_start", "name": "fs.write_file"}
        conversation = forge_code_store.load_conversation(session["project_root"], session["conversation_id"])
        mid_run_turns = len([t for t in (conversation or {}).get("turns", []) if t.get("role") == "agent"])
        yield {"type": "done"}

    async for _ in tee_to_build_session(_slow_events)({}, execution_id="exec-mid"):
        pass

    assert mid_run_turns == 1, "nothing was visible in the session until the run had already ended"
