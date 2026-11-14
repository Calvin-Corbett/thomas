"""Shared helpers for the tests of a change whose check, or second look, could not run.

Used by tests/test_a_change_that_could_not_be_checked_waits.py (the record and the settle that books it),
tests/test_a_held_hand_in_is_tried_again.py (the retries and a restart) and
tests/test_the_chat_card_says_what_a_held_change_waits_for.py (the words). Only temporary on-disk conversations
and hold records: whether a turn is current is controlled here, so these tests exercise the waiting room, not git,
a test subprocess, a card publisher or any network service.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from thomas.forge.anvil import forge_code_store
from thomas.server import autopilot_hold_tick, hand_in_hold
from thomas.server.app_keys import APP_LOCAL_PORT

Project = tuple[Path, Path, str]


def make_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Project:
    """A green work folder holding one finished turn, and a separate catalog folder (each test file's fixture)."""
    work, catalog = tmp_path / "green", tmp_path / "catalog"
    work.mkdir()
    catalog.mkdir()
    made = forge_code_store.new_conversation(work, title="Make this change", thomas_project={"execution_id": "green-1"})
    cid = str(made["id"])
    forge_code_store.append_user_turn(work, cid, "Make this change")
    forge_code_store.append_agent_turn(
        work, cid, model="test", transcript="", changed_files=["example.py"], returncode=0, ok=True, noop=False,
        reason="one file changed", outcome="completed",
    )  # fmt: skip
    # An eligible finished turn without a real Build runner: the turn comparison itself stays the real one.
    monkeypatch.setattr(
        hand_in_hold,
        "conversation_of",
        lambda root, _catalog, conversation_id: forge_code_store.load_conversation(root, conversation_id),
    )

    def current(root: Path, _catalog: Path, conversation_id: str, gen: list[Any] | None = None, *, app: Any = None):
        conversation = forge_code_store.load_conversation(root, conversation_id)
        return bool(conversation and (gen is None or gen == hand_in_hold.generation(conversation)))

    monkeypatch.setattr(hand_in_hold, "still_current", current)
    return work, catalog, cid


def book(project: Project, **kwargs: Any) -> dict[str, Any]:
    work, catalog, cid = project
    row = hand_in_hold.book(work, catalog, cid, port=8899, boot="server-1", chat="chat-1", **kwargs)
    assert row is not None
    return row


def row(project: Project) -> dict[str, Any] | None:
    return hand_in_hold.row(project[1], project[2])


def due(project: Project) -> None:
    catalog, cid = project[1:]
    found = row(project)
    assert found is not None
    assert hand_in_hold.change(catalog, cid, found["gen"], {**found, "next_at": 0}, expected=found)


def tick(project: Project, *, port: int = 8899, boot: str = "server-2") -> list[str]:
    return asyncio.run(autopilot_hold_tick.tick({APP_LOCAL_PORT: port}, project[1], boot=boot))
