"""A project file that stays unreadable is skipped by name; it no longer stops every other project from starting.

On 2026-11-04 the Improve Thomas panel said "0 running; 0 queued. More cannot start: Thomas projects could not all be
read": a few conversation files raised PermissionError for the caged account on every scan, so the automatic loop and
the Start button could never start anything. Transient failures are still retried (and still block while they are);
a file that fails ``READ_ATTEMPTS`` scans in a row is skipped, and a skipped green copy still holds its project slot.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from tests.test_the_project_listing_reads_the_catalog_once import CONVERSATIONS, conversation, scene  # noqa: F401
from thomas.server import self_project_queue_tick
from thomas.server.routes import self_project_routes as routes

ATTEMPTS = 3  # self_project_unreadable.READ_ATTEMPTS


@pytest.fixture(autouse=True)
def _fresh_counts():
    try:
        module = importlib.import_module("thomas.server.routes.self_project_unreadable")
    except ImportError:  # the code before this fix: nothing to reset
        yield
        return
    assert module.READ_ATTEMPTS == ATTEMPTS
    module._reset()
    yield
    module._reset()


def _deny(monkeypatch: pytest.MonkeyPatch, denied: set[Path]) -> None:
    real = Path.open

    def open_record(self: Path, *args, **kwargs):
        if self in denied:
            raise PermissionError(13, "Access is denied", str(self))
        return real(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", open_record)


def _capacity(report: dict) -> dict:
    slot = {"snapshot": report, "captured_at": 0}
    return self_project_queue_tick.queue_status({"self_project_listing_slot": slot}, {"queued": [], "started": []})


def _scene_with_denied_files(root: Path, catalog: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[str, Path, Path]:
    readable, _, _ = conversation(root, 1)
    green_bad = root / "work" / "e2" / CONVERSATIONS / "fc_denied.json"
    green_bad.parent.mkdir(parents=True)
    green_bad.write_text("{}", encoding="utf-8")
    catalog_bad = catalog / CONVERSATIONS / "fc_old_game.json"
    catalog_bad.write_text("{}", encoding="utf-8")
    _deny(monkeypatch, {green_bad, catalog_bad})
    return readable, green_bad, catalog_bad


def test_a_file_unreadable_in_every_scan_is_skipped_by_name_and_starts_are_no_longer_blocked(scene, monkeypatch):
    root, catalog = scene
    readable, green_bad, catalog_bad = _scene_with_denied_files(root, catalog, monkeypatch)

    for _ in range(ATTEMPTS - 1):
        report = routes.read_projects(catalog, changed_files=False)
        assert report["unreadable"] == []
        assert len(report["warnings"]) == 2
        assert "could not all be read" not in str(_capacity(report)["blocked_by"])

    report = routes.read_projects(catalog, changed_files=False)

    assert report["unreadable"] == []
    assert {(item["id"], item["reason"]) for item in report["skipped"]} == {
        ("fc_denied", "PermissionError: Access is denied"),
        ("fc_old_game", "PermissionError: Access is denied"),
    }
    by_id = {row["conversation_id"]: row for row in report["projects"]}
    assert readable in by_id
    assert by_id["fc_denied"]["state"] == "unreadable"
    assert "PermissionError" in by_id["fc_denied"]["detail"]
    assert by_id["fc_denied"]["execution_id"] == "e2"
    capacity = _capacity(report)
    assert "could not all be read" not in str(capacity["blocked_by"])
    # The skipped green copy may be a working team: it still holds a slot beside the readable project.
    assert capacity["running"] == 2
    assert "fc_old_game" not in by_id  # a handed-in copy is not a working team and holds no slot


def test_a_file_that_reads_again_starts_its_count_over(scene, monkeypatch):
    root, catalog = scene
    conversation(root, 1)
    green_bad = root / "work" / "e2" / CONVERSATIONS / "fc_denied.json"
    green_bad.parent.mkdir(parents=True)
    green_bad.write_text('{"id": "fc_denied", "turns": []}', encoding="utf-8")
    with pytest.MonkeyPatch.context() as denied:
        _deny(denied, {green_bad})
        for _ in range(ATTEMPTS - 1):
            routes.read_projects(catalog, changed_files=False)
    assert routes.read_projects(catalog, changed_files=False)["unreadable"] == []  # a replace finished: it reads
    # A file read cleanly is cached until it changes, and a changed file is read again: so a later denial is seen.
    green_bad.write_text('{"id": "fc_denied", "turns": [], "again": true}', encoding="utf-8")
    _deny(monkeypatch, {green_bad})

    report = routes.read_projects(catalog, changed_files=False)

    assert report["unreadable"] == []
    assert [entry["id"] for entry in report["skipped"]] == ["fc_denied"]
    assert len(report["warnings"]) == 1


def test_a_green_folder_that_cannot_be_listed_is_never_skipped(scene, monkeypatch):
    root, catalog = scene
    conversation(root, 1)
    work_root = root / "work"
    real = Path.iterdir

    def iterdir(self: Path):
        if self == work_root:
            raise PermissionError(13, "Access is denied", str(self))
        return real(self)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    for _ in range(ATTEMPTS + 1):
        report = routes.read_projects(catalog, changed_files=False)
        assert report["unreadable"]
        assert "could not all be read" in _capacity(report)["blocked_by"]
