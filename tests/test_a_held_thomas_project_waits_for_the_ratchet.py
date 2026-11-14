"""A Thomas project the ratchet started is never settled by Autopilot: the ratchet proves it, then settles it.

Autopilot settles a Thomas project on its own done check, with its own summary
(evolve_agent_autopilot.py, ``_thomas_project_should_settle``). A ratchet repair
must be proven again first, and its summary must name the candidate, so its
settle is held.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from thomas.forge.anvil import forge_code_projects, forge_code_store
from thomas.server import green_checkout, green_handoff, thomas_project, thomas_project_held
from thomas.server.routes import evolve_agent_autopilot as ap


def _turn(**overrides: Any) -> dict[str, Any]:
    turn = dict(
        model="claude-cli",
        transcript="log tail",
        changed_files=["a.py"],
        returncode=0,
        ok=True,
        noop=False,
        reason="1 file(s) changed",
        outcome="completed",
    )
    turn.update(overrides)
    return turn


def _conversation(root: Path, project: dict[str, Any]) -> str:
    conv = forge_code_store.new_conversation(root, title="land a candidate", thomas_project=project)
    forge_code_store.append_agent_turn(root, conv["id"], **_turn())
    return str(conv["id"])


def test_autopilot_never_settles_a_project_whose_settle_is_held(tmp_path: Path) -> None:
    root = tmp_path / "green-work"
    held = forge_code_store.load_conversation(root, _conversation(root, {"execution_id": "r-1", "hold_settle": True}))
    plain = forge_code_store.load_conversation(root, _conversation(root, {"execution_id": "thomas-abc"}))
    for conv in (held, plain):
        conv["settings"] = {"requested": {"autonomy_level": ap.AUTOPILOT}}
    done = ap.Decision("done", "Autopilot judged it done at the medium bar")

    assert ap._thomas_project_should_settle(done, held) is False
    assert ap._thomas_project_should_settle(done, plain) is True


def test_a_held_project_says_how_it_ended(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, catalog = tmp_path / "green-work", tmp_path / "catalog"
    cid = _conversation(root, {"execution_id": "r-1", "hold_settle": True})
    requested = {"settings": {"requested": {"autonomy_level": 3}}}
    monkeypatch.setattr(forge_code_projects, "conversation_metadata", lambda _root, _cid: requested)

    ended = thomas_project_held.held_outcome(root, catalog, cid)

    assert ended is not None
    assert (ended["ok"], ended["outcome"], ended["reason"], ended["autonomy_level"]) == (
        True,
        "completed",
        "1 file(s) changed",
        3,
    )
    assert "log tail" in ended["transcript_tail"]
    assert thomas_project_held.held_outcome(root, catalog, "missing") is None


def test_the_ratchet_settles_with_its_own_summary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def fake_settle(
        execution_id: str, *, promote: bool, summary: str, chat: str, checked: str, patch: str | None
    ) -> Path:
        calls.append((execution_id, summary, checked, patch))
        return tmp_path / "inbox" / f"self-{execution_id}"

    monkeypatch.setattr(green_handoff, "settle", fake_settle)
    monkeypatch.setattr(green_checkout, "find_green", lambda _execution_id: None)
    root, catalog = tmp_path / "green-work", tmp_path / "catalog"
    cid = _conversation(root, {"execution_id": "r-1", "hold_settle": True})

    submission = thomas_project.settle_if_finished(root, catalog, cid, summary="ratchet: land fix/x (abc)")

    assert submission is not None
    assert len(calls) == 1
    assert calls[0][:2] == ("r-1", "ratchet: land fix/x (abc)")
    assert "nothing to apply" in calls[0][2]
    assert calls[0][3] is None


def test_a_held_project_that_will_not_land_keeps_its_conversation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forgotten = []
    monkeypatch.setattr(forge_code_projects, "forget_conversation", lambda _root, cid: forgotten.append(cid))
    root, catalog = tmp_path / "green-work", tmp_path / "catalog"
    cid = _conversation(root, {"execution_id": "r-1", "hold_settle": True})

    thomas_project_held.retire_held(root, catalog, cid)

    assert forge_code_store.load_conversation(catalog, cid)["turns"]
    assert forgotten == [cid]
    assert thomas_project_held.project_catalog_root() == thomas_project._catalog_root()
