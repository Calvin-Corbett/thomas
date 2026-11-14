"""The Build agent is a task manager: solo for small work, agents for bigger.

The spec: "That Build agent is itself a task manager: solo for small work,
spawns agents for bigger work" and "Every spawned agent must appear in the Build
activity panel." Before this the worker had no spawn capability at all -- no
tool, no child path -- so the second half could not even be attempted.

The Activity panel renders the Build session's transcript, so "appears in the
panel" means exactly one thing: the child's steps are written into that
transcript, attributed to the child. That is what these tests pin.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from thomas.forge.anvil import forge_code_projects as fcp
from thomas.forge.anvil import forge_code_store
from thomas.server.agent_spawn_tool import SpawnAgentTool
from thomas.server.chat_delegation_build_session import open_build_session
from thomas.server.chat_delegation_build_transcript import remember_build_session


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


@pytest.fixture()
def session(catalog_root: Path) -> dict:
    opened = open_build_session(
        specialist_id="coding",
        targets_live_repo=False,
        title="Build a site with several pages",
        catalog_root=catalog_root,
    )
    assert opened is not None
    remember_build_session("exec-parent", opened["project_root"], opened["conversation_id"])
    return opened


def _transcript(session: dict) -> list[dict]:
    conversation = forge_code_store.load_conversation(session["project_root"], session["conversation_id"])
    turns = [t for t in (conversation or {}).get("turns", []) if t.get("role") == "agent"]
    if not turns:
        return []
    out = []
    for raw in turns[-1]["transcript"].splitlines():
        line = raw.strip()
        if line.startswith("{"):
            out.append(json.loads(line))
    return out


async def _child_that_writes_a_file(_title: str, _instructions: str):
    yield {"type": "tool_start", "name": "fs.write_file"}
    yield {"type": "tool_output", "name": "fs.write_file", "text": "ok"}
    yield {"type": "text", "text": "Wrote about.html"}


@pytest.mark.asyncio
async def test_a_spawned_agent_appears_in_the_build_activity_panel(session: dict) -> None:
    """The spec's own words. The panel reads the transcript, so it has to be there."""
    tool = SpawnAgentTool(execution_id="exec-parent", run_child=_child_that_writes_a_file)

    await tool.execute({"title": "about page", "instructions": "Write about.html"})

    events = _transcript(session)
    announced = [e for e in events if e.get("fc") == "meta" and "about page" in str(e.get("text", ""))]
    assert announced, "a spawned agent left no trace in the session you watch it through"


@pytest.mark.asyncio
async def test_the_childs_steps_are_attributed_to_the_child(session: dict) -> None:
    """Two agents working at once are unreadable if their steps are not labelled."""
    tool = SpawnAgentTool(execution_id="exec-parent", run_child=_child_that_writes_a_file)

    await tool.execute({"title": "about page", "instructions": "Write about.html"})

    tool_events = [e for e in _transcript(session) if e.get("fc") == "tool"]
    assert tool_events, "the child's tool calls never reached the panel"
    assert any("about page" in str(e.get("name", "")) for e in tool_events), (
        "the child's steps are in the panel but look like the parent's"
    )


@pytest.mark.asyncio
async def test_the_parent_gets_the_childs_answer_back(session: dict) -> None:
    """Spawning is delegation, not fire-and-forget: the lead has to use the result."""
    tool = SpawnAgentTool(execution_id="exec-parent", run_child=_child_that_writes_a_file)

    result = await tool.execute({"title": "about page", "instructions": "Write about.html"})

    assert result.ok
    assert "about.html" in str(result.data)


@pytest.mark.asyncio
async def test_a_child_that_fails_does_not_take_the_lead_down(session: dict) -> None:
    """Rule 0 again. One failed helper is a result to report, not a dead run."""

    async def _child_that_breaks(_title: str, _instructions: str):
        yield {"type": "tool_start", "name": "fs.write_file"}
        raise RuntimeError("child exploded")

    tool = SpawnAgentTool(execution_id="exec-parent", run_child=_child_that_breaks)

    result = await tool.execute({"title": "about page", "instructions": "Write about.html"})

    assert result.ok is False
    assert "child exploded" in str(result.error)
    # and the lead still has a session that records what happened
    assert any(e.get("fc") == "error" for e in _transcript(session))


@pytest.mark.asyncio
async def test_spawning_without_a_build_session_still_does_the_work() -> None:
    """A task with no session to watch must still be able to delegate."""
    tool = SpawnAgentTool(execution_id="exec-nosession", run_child=_child_that_writes_a_file)

    result = await tool.execute({"title": "about page", "instructions": "Write about.html"})

    assert result.ok
    assert "about.html" in str(result.data)


@pytest.mark.asyncio
async def test_a_brief_is_required(session: dict) -> None:
    """A spawn with no instructions is a bug in the caller, not a silent no-op."""
    tool = SpawnAgentTool(execution_id="exec-parent", run_child=_child_that_writes_a_file)

    result = await tool.execute({"title": "about page", "instructions": "   "})

    assert result.ok is False
    assert "instructions" in str(result.error).casefold()
