"""A conversation too large to read cannot crash a finished project's hand-in, and is not read whole to begin with.

On 2026-11-04 a finished Thomas project's hand-in died with MemoryError in ``hand_in_hold.still_current`` (called
from ``autopilot_hold_tick.hold_if_unfinished`` after ``_settle_thomas_project``): it loaded the whole 9 MB
conversation, 8.6 MB of it the transcripts of earlier runs. The change was stranded with no word on screen.
Only temporary conversations; nothing here starts a check, a run or a card.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.hand_in_hold_support import book, make_project
from thomas.core import atomic_json
from thomas.forge.anvil import forge_code_store
from thomas.server import autopilot_hold_tick, hand_in_hold
from thomas.server.routes import evolve_agent_autopilot as route

TAIL = 200_000  # autopilot_park._TAIL_CHARS: the most of a transcript any decision reads


def _file(work: Path, cid: str) -> Path:
    return work / ".thomas" / "evolve" / "agent" / "conversations" / f"{cid}.json"


def test_a_memory_error_reading_the_conversation_holds_the_change_for_its_next_try(tmp_path, monkeypatch):
    real_still_current, real_conversation_of = hand_in_hold.still_current, hand_in_hold.conversation_of
    project = make_project(tmp_path, monkeypatch)
    work, catalog, cid = project
    booked = book(project)
    assert booked["state"] == "checking"
    monkeypatch.setattr(hand_in_hold, "still_current", real_still_current)  # the real read, as on 2026-11-04
    monkeypatch.setattr(hand_in_hold, "conversation_of", real_conversation_of)
    big = _file(work, cid)
    real_read = atomic_json.read_text_with_retry

    def read_text_with_retry(path: Path) -> str:
        if Path(path) == big:
            raise MemoryError
        return real_read(path)

    monkeypatch.setattr(atomic_json, "read_text_with_retry", read_text_with_retry)

    autopilot_hold_tick.hold_if_unfinished(work, catalog, cid, booked["gen"])  # raised MemoryError before

    held = hand_in_hold.row(catalog, cid)
    assert held is not None and held["gen"] == booked["gen"]
    assert held["state"] == "held"  # waiting for its next try, not dropped and not "checking" for ever
    assert "MemoryError" in held["why"] and "could not be read" in held["why"]
    assert held["next_at"] > 0 and held["strikes"] == 0
    shown = hand_in_hold.phase(work, catalog, cid)
    assert shown is not None and shown[0] == "paused"
    assert "could not be read" in shown[1] and "Tries again by himself" in shown[1]


def test_earlier_transcripts_are_read_only_as_far_as_any_decision_reads(tmp_path, monkeypatch):
    work = tmp_path / "green"
    work.mkdir()
    made = forge_code_store.new_conversation(work, title="Big", thomas_project={"execution_id": "green-1"})
    cid = str(made["id"])
    for number in range(3):
        forge_code_store.append_user_turn(work, cid, f"round {number}")
        forge_code_store.append_agent_turn(
            work, cid, model="test", transcript=f"{number}" + "x" * (TAIL + 50_000) + "END", changed_files=["a.py"],
            returncode=0, ok=True, noop=False, reason="done", outcome="completed",
        )  # fmt: skip
    whole = json.loads(_file(work, cid).read_text(encoding="utf-8"))

    read = hand_in_hold.conversation_of(work, tmp_path, cid)  # the hand-in path's read

    agents = [turn for turn in read["turns"] if turn.get("role") == "agent"]
    full = [turn for turn in whole["turns"] if turn.get("role") == "agent"]
    for kept, original in zip(agents[:-1], full[:-1], strict=True):
        assert len(kept["transcript"]) == TAIL
        assert kept["transcript"] == original["transcript"][-TAIL:]
    assert agents[-1] == full[-1]  # the last turn is whole: the hand-in's turn hash is unchanged
    assert hand_in_hold.generation(read) == hand_in_hold.generation(whole)
    assert route.decide(read) == route.decide({**whole, "settings": read["settings"]})


@pytest.mark.parametrize("content", [b"{", b"\xff\xfe"])
def test_a_conversation_that_cannot_be_parsed_is_unreadable_not_gone(tmp_path, content):
    work = tmp_path / "green"
    path = _file(work, "fc_bad")
    path.parent.mkdir(parents=True)
    path.write_bytes(content)
    with pytest.raises(hand_in_hold.ConversationUnreadable):
        hand_in_hold.conversation_of(work, tmp_path, "fc_bad")
    path.unlink()
    assert hand_in_hold.conversation_of(work, tmp_path, "fc_bad") is None
