"""A retired ratchet repair names its ending in the project listing."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.forge.anvil import forge_code_store
from thomas.server import green_handoff, self_change_status, thomas_project_held
from thomas.server.ratchet.candidates import Candidate
from thomas.server.ratchet.ledger import Ledger
from thomas.server.ratchet.repair import Repairer, RepairHooks
from thomas.server.routes import self_project_routes as routes


def _conversation(root: Path, cid: str, stamp: str, *, held: bool = True) -> None:
    forge_code_store.write_conversation(
        root,
        {
            "id": cid,
            "title": cid,
            "updated_at": stamp,
            "thomas_project": {"execution_id": f"ratchet-{cid}", "hold_settle": held, "ratchet": {"sha": cid}},
            "turns": [],
        },
    )


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    catalog, root, ratchet = (tmp_path / name for name in ("catalog", "green", "ratchet"))
    monkeypatch.setenv("THOMAS_RATCHET_ROOT", str(ratchet))
    monkeypatch.setattr(green_handoff, "sibling_changes", lambda _id: {})
    monkeypatch.setattr(routes, "_in_greens", lambda warnings=None: [])
    return SimpleNamespace(catalog=catalog, root=root, ledger=Ledger(), monkeypatch=monkeypatch)


def _attempt(root: Path, cid: str) -> SimpleNamespace:
    candidate = Candidate(cid, (f"refs/heads/{cid}",), 0, (), 0)
    return SimpleNamespace(candidate=candidate, dev_sha="dev-tip", green=SimpleNamespace(work=root, execution_id=cid))


def test_report_and_carried_repair_record_their_ending(world: SimpleNamespace) -> None:
    reported, carried = "reported-repair", "carried-repair"
    for cid in (reported, carried):
        _conversation(world.root, cid, cid)
    submission = world.catalog / "self-carried-repair"
    world.monkeypatch.setattr(
        self_change_status,
        "read_hand_in_state",
        lambda sid: {"status": "landed", "detail": "landed"} if sid == submission.name else None,
    )
    world.monkeypatch.setattr(self_change_status, "refusal_text", lambda verdict: verdict["detail"])
    hooks = RepairHooks(
        start=lambda *a, **kw: None,
        phase=lambda *a: ("ended", ""),
        outcome=lambda *a: None,
        settle_held=lambda *a, **kw: None,
        retire=thomas_project_held.retire_held,
        stop=lambda *a: None,
        catalog_root=lambda: world.catalog,
        settings=lambda: {},
    )
    repairer = Repairer(None, 0, hooks)
    ctx = SimpleNamespace(ledger=world.ledger, hooks=SimpleNamespace(settle=lambda *a, **kw: submission))
    reason = "after the repair: the proof could not run on dev itself"
    assert (
        repairer._report(
            ctx,
            _attempt(world.root, reported),
            world.catalog,
            reported,
            "dev-tip",
            reason,
            {"conversation_id": reported},
        )
        == "reported"
    )
    carried_attempt = _attempt(world.root, carried)
    assert (
        repairer._settle_carried(ctx, carried_attempt, carried_attempt, world.catalog, carried, "carried proof", "")
        == submission
    )
    rows = {row["conversation_id"]: row for row in routes.list_projects(world.catalog)}
    assert rows[reported]["state"] == "reported"
    assert rows[reported]["detail"] == reason
    assert rows[carried]["state"] == "landed"
    assert rows[carried]["submission"] == submission.name
    assert rows[carried]["last_verdict"]["status"] == "landed"
    for cid, outcome in ((reported, "reported"), (carried, "carried")):
        project = forge_code_store.load_conversation(world.catalog, cid)["thomas_project"]
        assert project["retirement"]["outcome"] == outcome
        assert project["retirement"]["at"]
        assert "settled_at" not in project
    assert (
        forge_code_store.load_conversation(world.catalog, reported)["thomas_project"]["retirement"]["reason"] == reason
    )
    assert (
        forge_code_store.load_conversation(world.catalog, carried)["thomas_project"]["retirement"]["submission"]
        == submission.name
    )


def test_legacy_report_uses_the_last_event_for_its_conversation(world: SimpleNamespace) -> None:
    cid = "old-repair"
    _conversation(world.catalog, cid, "2026-10-01")
    world.ledger.record(dev_sha="old", state="reported", reason="old proof", conversation_id=cid)
    world.ledger.record(dev_sha="new", state="reported", reason="another repair", conversation_id="other")
    world.ledger.record(dev_sha="new", state="reported", reason="last proof failed", conversation_id=cid)

    [row] = routes.list_projects(world.catalog)
    assert (row["state"], row["detail"]) == ("reported", "last proof failed")
    assert "retirement" not in forge_code_store.load_conversation(world.catalog, cid)["thomas_project"]


def test_a_copy_without_an_ending_or_matching_event_is_still_handing_in(world: SimpleNamespace) -> None:
    _conversation(world.catalog, "unknown", "2026-10-01")
    world.ledger.record(dev_sha="old", state="reported", reason="not this repair", conversation_id="other")

    [row] = routes.list_projects(world.catalog)
    assert (row["state"], row["detail"]) == ("handing in", "being handed to your approval card")


def test_only_twenty_catalog_rows_are_built_and_the_ledger_is_read_once(world: SimpleNamespace) -> None:
    for n in range(30):
        _conversation(world.catalog, f"copy-{n:02}", f"2026-10-{n + 1:02}")
    calls: list[str] = []
    actual_events = Ledger.events
    actual_row = routes._handed_in

    def events(ledger: Ledger) -> list[dict[str, Any]]:
        calls.append("ledger")
        return actual_events(ledger)

    def row(conversation: dict[str, Any], files: dict[str, list[str]], event: dict[str, Any] | None = None) -> dict:
        calls.append(str(conversation["id"]))
        return actual_row(conversation, files, event)

    world.monkeypatch.setattr(Ledger, "events", events)
    world.monkeypatch.setattr(routes, "_handed_in", row)
    listed = routes.list_projects(world.catalog)
    assert len(listed) == 20
    assert [item["conversation_id"] for item in listed] == [f"copy-{n:02}" for n in range(29, 9, -1)]
    assert calls.count("ledger") == 1
    assert [call for call in calls if call != "ledger"] == [f"copy-{n:02}" for n in range(29, 9, -1)]
