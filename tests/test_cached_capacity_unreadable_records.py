"""Individual records are skipped; an unreadable registry still blocks capacity."""

from __future__ import annotations

import json

import pytest

from tests.test_the_project_listing_reads_the_catalog_once import CONVERSATIONS, conversation, scene  # noqa: F401
from thomas.forge.anvil import forge_code_conversations
from thomas.server import self_project_queue_tick
from thomas.server.routes import self_project_routes as routes


@pytest.mark.parametrize("denied_stage", ["conversations", "work-entry"])
@pytest.mark.asyncio
async def test_denied_project_directory_does_not_block_queued_work(scene, monkeypatch, denied_stage):
    from pathlib import Path

    from thomas.server import self_project_queue_tick as queue

    work, catalog = scene
    denied = work / "work" / "exec_denied" / CONVERSATIONS
    denied.mkdir(parents=True)
    conversation(work, 1)
    original = Path.iterdir

    def guarded(path):
        if path == denied:
            raise PermissionError("directory access denied")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", guarded)
    if denied_stage == "work-entry":
        original_is_dir = Path.is_dir

        def is_dir(path):
            if path == work / "work" / "exec_denied":
                raise PermissionError("project access denied")
            return original_is_dir(path)

        monkeypatch.setattr(Path, "is_dir", is_dir)
    listing = routes.read_projects(catalog, set())
    assert listing["unreadable"] == []
    assert len(listing["warnings"]) == 1
    assert "exec_denied" in listing["warnings"][0]
    from tests.test_a_self_project_queue import CLAUDE, _room

    _room(monkeypatch)
    app = {"self_project_listing_slot": {"snapshot": listing}}
    queue.self_project_queue.enqueue(catalog, "readable queued work", CLAUDE, "", 8899)
    starts = []

    async def start(*args, **kwargs):
        starts.append(kwargs["request"])
        return {"conversation_id": "fc_started"}

    monkeypatch.setattr(queue.thomas_project, "start_thomas_project", start)
    selected = queue._select(catalog, app, 8899, queue.time.time())
    assert selected is not None
    await queue._start(app, catalog, selected, 8899)
    assert starts == ["readable queued work"]


@pytest.mark.parametrize("content", ["{", "[]", '{"fc_one": []}', '{"other": []}', "denied"])
def test_unreadable_registry_cannot_authorize_capacity(scene, monkeypatch, content):
    _, catalog = scene
    path = forge_code_conversations._registry_path(catalog)
    if content == "denied":
        original = type(path).open

        def open_record(self, *args, **kwargs):
            if self == path:
                raise PermissionError("registry denied")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(type(path), "open", open_record)
    else:
        path.write_text(content, encoding="utf-8")
    report = routes.read_projects(catalog, changed_files=False)
    assert report["unreadable"]
    assert any(str(path) in warning for warning in report["unreadable"])
    capacity = self_project_queue_tick.queue_status({"self_project_listing_slot": {"snapshot": report}}, {"queued": []})
    assert capacity["running"] is None
    assert "read" in capacity["blocked_by"]


@pytest.mark.parametrize("location", ["green", "catalog"])
@pytest.mark.parametrize(
    "content",
    [
        b"{",
        b"\xff",
        b"[]",
        json.dumps({"id": "bad id", "thomas_project": {"execution_id": "e2"}}).encode(),
        *[
            json.dumps({"id": "fc_broken", "thomas_project": project}).encode()
            for project in [
                None,
                [],
                "project",
                {},
                {"execution_id": 1},
                {"execution_id": ""},
                {"execution_id": " "},
                {"execution_id": "\t"},
            ]
        ],
    ],
    ids=[
        "truncated-json",
        "invalid-encoding",
        "not-an-object",
        "invalid-identity",
        "null-project",
        "list-project",
        "string-project",
        "missing-execution",
        "non-string-execution",
        "empty-execution",
        "space-execution",
        "tab-execution",
    ],
)
def test_unreadable_conversation_warns_without_blocking_cached_capacity(scene, location, content):
    root, catalog = scene
    cid, _, _ = conversation(root, 1)
    folder = root / "work" / "e2" / CONVERSATIONS if location == "green" else catalog / CONVERSATIONS
    folder.mkdir(parents=True, exist_ok=True)
    broken = folder / "fc_broken.json"
    broken.write_bytes(content)

    report = routes.read_projects(catalog, changed_files=False)

    assert any(row["conversation_id"] == cid for row in report["projects"])
    assert report["unreadable"] == []
    assert len(report["warnings"]) == 1 and broken.stem in report["warnings"][0]
    capacity = self_project_queue_tick.queue_status(
        {"self_project_listing_slot": {"snapshot": report}}, {"queued": [], "started": []}
    )
    assert capacity["running"] == 1
    assert "read" not in (capacity["blocked_by"] or "")


@pytest.mark.parametrize("location", ["green", "catalog"])
@pytest.mark.parametrize("broken_name", ["fc_0.json", "fc_9.json"])
def test_cold_inventory_keeps_readable_cards_beside_a_malformed_record(scene, location, broken_name):
    root, catalog = scene
    cid, path, _ = conversation(root, 1)
    if location == "catalog":
        path = path.replace(catalog / CONVERSATIONS / path.name)
    broken = path.parent / broken_name
    broken.write_bytes(b"{")

    report = routes.read_projects(catalog, changed_files=False)

    assert [row["conversation_id"] for row in report["projects"]] == [cid]
    assert report["unreadable"] == []
    assert len(report["warnings"]) == 1 and broken.stem in report["warnings"][0]
    capacity = self_project_queue_tick.queue_status(
        {"self_project_listing_slot": {"snapshot": report}}, {"queued": [], "started": []}
    )
    assert capacity["running"] == (1 if location == "green" else 0)
    assert "read" not in (capacity["blocked_by"] or "")


def test_denied_project_directory_warns_without_stopping_planner(scene, monkeypatch):
    from pathlib import Path

    from thomas.server import self_project_queue

    root, catalog = scene
    cid, _, _ = conversation(root, 1)
    denied = root / "work" / "denied-project" / CONVERSATIONS
    denied.mkdir(parents=True)
    original = Path.iterdir

    def iterdir(path):
        if path == denied:
            raise PermissionError("access denied")
        return original(path)

    monkeypatch.setattr(Path, "iterdir", iterdir)
    report = routes.read_projects(catalog, changed_files=False)
    assert [row["conversation_id"] for row in report["projects"] if row["state"] != "unreadable"] == [cid]
    assert [row["execution_id"] for row in report["projects"] if row["state"] == "unreadable"] == ["denied-project"]
    assert report["unreadable"] == []
    assert len(report["warnings"]) == 1
    assert "denied-project" in report["warnings"][0]
    queued = self_project_queue.enqueue(catalog, "Improve a readable project", {}, "", 8899)
    monkeypatch.setattr(self_project_queue_tick.capacity_ledger, "refusal", lambda *a, **k: "")
    app = {"self_project_listing_slot": {"snapshot": report}}
    selected = self_project_queue_tick._select(catalog, app, 8899, self_project_queue_tick.time.time())
    assert selected["id"] == queued["id"]


def test_a_valid_non_project_conversation_does_not_block_capacity(scene):
    root, catalog = scene
    conversation(root, 1)
    folder = root / "work" / "ordinary" / CONVERSATIONS
    folder.mkdir(parents=True)
    (folder / "fc_ordinary.json").write_text(json.dumps({"id": "fc_ordinary", "turns": []}), encoding="utf-8")

    report = routes.read_projects(catalog, changed_files=False)

    assert len(report["projects"]) == 1
    assert report["unreadable"] == []
