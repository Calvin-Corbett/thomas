"""An approved Autopilot survives a restart of the caged Thomas.

Grants lived only in the server's memory (dial_elevation, 5213bb30), so every
restart quietly ran Autopilot at a lower level while the screen still said
Autopilot: measured 2026-09-23, two resumed builds ran at autonomy 3. In the cage
the owner's desk now records each approval where only you can write, and the
server reads it back. Outside the cage the server runs as you and could write
that file itself, so there it is ignored.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.cage import owner_desk as desk

from thomas.server import dial_elevation
from thomas.tools import owner_desk, trusted_card


@pytest.fixture
def pins(tmp_path: Path) -> Path:
    root = tmp_path / "pins"
    root.mkdir()
    (root / trusted_card.PIN_NAME).write_text(trusted_card.catalogue_digest(trusted_card.CATALOGUE_PATH))
    return root


@pytest.fixture(autouse=True)
def _no_grants_in_memory():
    dial_elevation.reset_grants()
    yield
    dial_elevation.reset_grants()


def _file_request(root: Path, rid: str, content_hash: str, value: str = "5") -> None:
    requests = root / "desk" / "requests"
    requests.mkdir(parents=True, exist_ok=True)
    request = {
        "id": rid,
        "kind": "raise_dial",
        "details": {"dial": "its autonomy", "value": value},
        "content_hash": content_hash,
        "created_at": 0,
    }
    (requests / f"{rid}.json").write_text(json.dumps(request), encoding="utf-8")


def test_an_approved_raise_is_recorded_on_the_desk(tmp_path: Path, pins: Path) -> None:
    _file_request(tmp_path, "a" * 32, "autonomy=5")
    assert desk.serve_once(tmp_path, ask=lambda *_: True, pin_root=pins) == 1
    assert owner_desk.recorded_grants(tmp_path) == {"autonomy": "5"}


def test_a_refused_raise_records_nothing(tmp_path: Path, pins: Path) -> None:
    _file_request(tmp_path, "b" * 32, "autonomy=5")
    desk.serve_once(tmp_path, ask=lambda *_: False, pin_root=pins)
    assert owner_desk.recorded_grants(tmp_path) == {}


def test_a_lower_approval_never_lowers_a_higher_one(tmp_path: Path, pins: Path) -> None:
    for rid, content_hash, value in (("c" * 32, "autonomy=5", "5"), ("d" * 32, "autonomy=4", "4")):
        _file_request(tmp_path, rid, content_hash, value)
        desk.serve_once(tmp_path, ask=lambda *_: True, pin_root=pins)
    assert owner_desk.recorded_grants(tmp_path) == {"autonomy": "5"}


def test_no_request_can_be_answered_under_the_grants_file_name(tmp_path: Path, pins: Path) -> None:
    requests = tmp_path / "desk" / "requests"
    requests.mkdir(parents=True)
    rid = owner_desk.GRANTS_NAME[: -len(".json")]
    forged = {"id": rid, "kind": "raise_dial", "details": {"dial": "x", "value": "5"}, "content_hash": "autonomy=5"}
    (requests / owner_desk.GRANTS_NAME).write_text(json.dumps(forged), encoding="utf-8")
    desk.serve_once(tmp_path, ask=lambda *_: True, pin_root=pins)
    assert not (tmp_path / "desk" / "answers" / owner_desk.GRANTS_NAME).exists()


def test_after_a_restart_the_cage_still_runs_autopilot(
    tmp_path: Path, pins: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(owner_desk.DESK_ENV, "1")
    monkeypatch.setattr(owner_desk, "desk_root", lambda root=None: tmp_path / "desk")
    assert dial_elevation.cap("autonomy", 5) != 5
    _file_request(tmp_path, "e" * 32, "autonomy=5")
    desk.serve_once(tmp_path, ask=lambda *_: True, pin_root=pins)
    dial_elevation.reset_grants()  # what a restart does to memory
    assert dial_elevation.cap("autonomy", 5) == 5
    assert dial_elevation.grants()["autonomy"] == 5


def test_outside_the_cage_a_grants_file_is_ignored(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(owner_desk.DESK_ENV, raising=False)
    answers = tmp_path / "desk" / "answers"
    answers.mkdir(parents=True)
    (answers / owner_desk.GRANTS_NAME).write_text(json.dumps({"autonomy": "5"}), encoding="utf-8")
    monkeypatch.setattr(owner_desk, "desk_root", lambda root=None: tmp_path / "desk")
    assert dial_elevation.cap("autonomy", 5) != 5
