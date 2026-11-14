"""A finished Thomas project whose hand-in never happened is tried again at start, through the normal held hand-in.

On 2026-11-04 a finished project's hand-in crashed before it booked a hold row: "hand in again" refused it ("only a
handed-in change goes in again"), a reply in its chat starts nothing, and the next start did not look at it, so the
change stayed in its green. Now the park loop's first hold tick books it ``held`` and due now, and the try goes through
``_settle_thomas_project`` with the turn it booked, as any held change does. Only temporary greens and catalogs:
the settle itself is replaced, so no check, card or git runs here.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from thomas.forge.anvil import forge_code_store
from thomas.server import (
    autopilot_hold_tick,
    autopilot_restart,
    capacity_ledger,
    green_checkout,
    hand_in_hold,
    self_change_status,
    thomas_project,
)
from thomas.server.app_keys import APP_LOCAL_PORT
from thomas.server.routes import evolve_agent_autopilot as route


@pytest.fixture
def greens(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    root, catalog = tmp_path / "greens", tmp_path / "catalog"
    (root / "work").mkdir(parents=True)
    catalog.mkdir()
    monkeypatch.setattr(green_checkout, "green_root", lambda: root)
    monkeypatch.setenv(capacity_ledger.ROOT_ENV, str(tmp_path / "ledger"))
    monkeypatch.setattr(autopilot_hold_tick, "_previous_listener_gone", lambda _port: False)
    monkeypatch.setattr(autopilot_hold_tick, "_space_available", lambda _root: True)
    monkeypatch.setattr(autopilot_restart, "_runners_of", lambda _cid: ([], []))
    monkeypatch.setattr(self_change_status, "being_handed_in", lambda _cid: False)
    return root, catalog


def _finished(root: Path, name: str, *, changed: list[str], outcome: str = "completed") -> tuple[Path, str]:
    work = root / "work" / name
    made = forge_code_store.new_conversation(work, title="Fix it", thomas_project={"execution_id": name})
    cid = str(made["id"])
    forge_code_store.append_user_turn(work, cid, "Fix it")
    forge_code_store.append_agent_turn(
        work, cid, model="test", transcript="", changed_files=changed, returncode=0, ok=True, noop=False,
        reason="done", outcome=outcome,
    )  # fmt: skip
    return work, cid


def _start(catalog: Path, monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The park loop's first hold tick at server start; returns the settle tries it made."""
    tries: list[dict[str, Any]] = []

    async def settle(root: Path, catalog_root: Path, cid: str, *, app: Any = None, gen: Any = None) -> None:
        tries.append({"root": Path(root), "cid": cid, "gen": gen, "row": hand_in_hold.row(catalog_root, cid)})
        hand_in_hold.drop(catalog_root, cid, gen)  # as a hand-in that went out

    monkeypatch.setattr(route, "_settle_thomas_project", settle)

    async def boot() -> None:
        await autopilot_hold_tick.run({APP_LOCAL_PORT: 8899}, catalog, startup=True)
        while autopilot_hold_tick._TASKS:
            await asyncio.gather(*list(autopilot_hold_tick._TASKS), return_exceptions=True)

    asyncio.run(boot())
    return tries


def test_a_finished_project_with_no_hold_row_is_handed_in_at_start(greens, monkeypatch):
    root, catalog = greens
    work, cid = _finished(root, "e1", changed=["thomas/fix.py"])
    assert hand_in_hold.row(catalog, cid) is None and not thomas_project.settled_record(catalog, cid)

    tries = _start(catalog, monkeypatch)

    assert [(t["root"], t["cid"]) for t in tries] == [(work, cid)]
    conversation = hand_in_hold.conversation_of(work, catalog, cid)
    assert tries[0]["gen"] == hand_in_hold.generation(conversation)  # the turn it was booked for, so checks guard it
    assert tries[0]["row"]["state"] == "checking" and tries[0]["row"]["tries"] == 1


def test_only_finished_unsettled_projects_with_changes_are_booked(greens, monkeypatch):
    root, catalog = greens
    _finished(root, "e1", changed=[])  # nothing changed: nothing to hand in
    _finished(root, "e2", changed=["a.py"], outcome="stopped")  # you stopped it
    work, cid = _finished(root, "e3", changed=["b.py"])
    thomas_project.request_stop(work, cid)  # stopped from Chat's card
    try:
        assert _start(catalog, monkeypatch) == []
    finally:
        thomas_project._STOPPED.pop(cid, None)
    assert hand_in_hold.rows(catalog) == []


def test_a_held_row_is_left_to_its_own_retry(greens, monkeypatch):
    root, catalog = greens
    work, cid = _finished(root, "e1", changed=["thomas/fix.py"])
    booked = hand_in_hold.book(work, catalog, cid, port=8899, boot="old")
    held = {**booked, "state": "held", "next_at": hand_in_hold.clock() + 3600}
    assert hand_in_hold.change(catalog, cid, booked["gen"], held, expected=booked)

    assert _start(catalog, monkeypatch) == []  # not due yet: the scan never books a second row over it
    assert hand_in_hold.row(catalog, cid) == held
