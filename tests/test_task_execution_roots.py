"""Task creation, chat controls, and reopening must agree on record location."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from thomas.core import shared_root_sandbox, task_execution_roots
from thomas.core import task_bot_runtime as rt
from thomas.core.project_root import coordination_root
from thomas.server import chat_delegation_session
from thomas.server.routes import chat_v2_session_routes as routes


@pytest.fixture
def stores(tmp_path, monkeypatch):
    launch = tmp_path / "launcher"
    launch.mkdir()
    data = tmp_path / "data"
    for key in ("THOMAS_PROFILE", "THOMAS_HOME", "THOMAS_STATE_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("THOMAS_DATA_DIR", str(data))
    monkeypatch.setenv("THOMAS_PROJECT_ROOT", str(launch))
    monkeypatch.setenv("THOMAS_USER_DIR", str(data))
    monkeypatch.setattr(rt, "ROOT", launch)
    monkeypatch.chdir(launch)
    return launch, data, tmp_path / "project"


def create(root, sid="chat-a"):
    return rt.create_execution(session_id=sid, summary="Make the report", repo_root=root)["execution_id"]


def card_id(record, **kw):
    return {"id": record["execution_id"]}


def request(eid, sid="chat-a", message="Use the revised title"):
    async def body():
        return {"message": message}

    return SimpleNamespace(match_info={"session_id": sid, "execution_id": eid}, json=body)


@pytest.mark.parametrize("workspace", ["isolated", "project"])
def test_real_chat_routes_list_detail_steer_cancel_at_creation_root(stores, workspace):
    launch, data, project = stores
    root = coordination_root(project, workspace)
    eid = create(root)
    listed = asyncio.run(routes.handle_session_delegations(request(eid)))
    assert [row["execution_id"] for row in json.loads(listed.text)["delegations"]] == [eid]
    assert asyncio.run(routes.handle_delegation_detail(request(eid))).status == 200
    assert asyncio.run(routes.handle_steer_delegation(request(eid))).status == 200
    assert rt.take_pending_instructions(eid, repo_root=root) == ["Use the revised title"]
    assert asyncio.run(routes.handle_cancel_delegation(request(eid))).status == 200
    assert rt.is_cancel_requested(eid, repo_root=root)
    assert not rt.runtime_dir(launch).exists(), "chat controls must not create a shadow record"


def test_other_session_cannot_control_or_read_indexed_task(stores):
    eid = create(stores[2])
    wrong = request(eid, sid="unrelated")
    assert asyncio.run(routes.handle_cancel_delegation(wrong)).status == 404
    assert asyncio.run(routes.handle_steer_delegation(wrong)).status == 404
    assert asyncio.run(routes.handle_delegation_detail(wrong)).status == 403
    assert not rt.is_cancel_requested(eid, repo_root=stores[2])


def test_reported_marker_updates_the_original_record(stores):
    eid = create(stores[2])
    response = asyncio.run(routes.handle_mark_delegation_reported(request(eid)))
    assert response.status == 200
    assert rt.get_execution(eid, stores[2])["reported_to_chat_at"]
    assert rt.get_execution(eid, stores[0]) is None


def test_explicit_project_scope_does_not_fall_back_to_another_project(stores):
    eid = create(stores[2])
    assert rt.get_execution(eid, stores[0]) is None
    assert rt.list_executions(stores[0]) == []
    with pytest.raises(FileNotFoundError):
        rt.request_cancel(eid, repo_root=stores[0])
    assert rt.get_execution(eid)["execution_id"] == eid


def test_index_survives_new_process_and_different_launch_directory(stores, monkeypatch):
    monkeypatch.setattr(shared_root_sandbox, "in_test_run", lambda: False)
    eid = create(stores[2])
    env = os.environ.copy()
    env.pop("PYTEST_CURRENT_TEST", None)
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    code = "import json, sys; from thomas.server.chat_delegation_session import session_active_delegations as read; print(json.dumps([r['execution_id'] for r in read(sys.argv[1])]))"
    args = [sys.executable, "-B", "-c", code, "chat-a"]
    output = subprocess.check_output(args, cwd=stores[0], env=env, text=True, timeout=30)
    assert json.loads(output) == [eid]


def test_pre_index_one_off_and_legacy_installation_tasks_remain_visible(stores):
    launch, data, _ = stores
    eids = [create(launch), create(data)]
    for root in (launch, data):
        task_execution_roots.index_path(root).unlink()
    assert {row["execution_id"] for row in rt.list_user_executions()} == set(eids)
    assert all(rt.get_execution(eid) for eid in eids)


def test_existing_linked_project_is_discovered_without_new_registration(stores):
    _, data, project = stores
    eid = create(project)
    task_execution_roots.index_path(project).unlink()
    registry = data / ".thomas" / "linked_projects.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(json.dumps({"projects": [{"root_path": str(project)}]}), encoding="utf-8")
    assert rt.get_execution(eid)["execution_id"] == eid


def test_root_discovery_resolves_shared_index_and_registry_path_once(stores, monkeypatch):
    launch, data, project = stores
    create(project)
    registry = data / ".thomas" / "linked_projects.json"
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps({"projects": [{"root_path": str(project)}] * 3}), encoding="utf-8")
    resolve = Path.resolve
    calls = []

    def counted(path, *args, **kwargs):
        if path == project:
            calls.append(path)
        return resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counted)
    assert project in task_execution_roots.roots_for_user(launch)
    assert len(calls) == 1
    # Discovery is fresh each time: additions are never hidden by a lasting cache.
    added = project.parent / "new-project"
    registry.write_text(json.dumps({"projects": [{"root_path": str(added)}]}), encoding="utf-8")
    assert added in task_execution_roots.roots_for_user(launch)


def test_user_index_is_profile_scoped(stores, monkeypatch):
    eid = create(stores[2])
    monkeypatch.setenv("THOMAS_PROFILE", "separate")
    assert rt.get_execution(eid) is None
    assert rt.list_user_executions() == []


def test_concurrent_project_starts_do_not_lose_index_entries(stores):
    projects = [stores[0].parent / f"project-{i}" for i in range(8)]
    with ThreadPoolExecutor(max_workers=8) as pool:
        eids = list(pool.map(create, projects))
    assert {row["execution_id"] for row in rt.list_user_executions()} == set(eids)


def test_deleting_session_removes_records_across_its_projects_only(stores):
    roots = [stores[0], stores[1], stores[2]]
    gone = [create(root) for root in roots]
    retained = create(stores[2], sid="chat-b")
    assert rt.delete_session_executions("chat-a") == 3
    assert all(rt.get_execution(eid) is None for eid in gone)
    assert rt.get_execution(retained)["conversation_id"] == "chat-b"
    assert [row["execution_id"] for row in rt.list_user_executions()] == [retained]


def test_duplicate_ids_are_not_arbitrarily_cancelled(stores):
    _, data, project = stores
    eid = create(project)
    create(data, sid="chat-b")
    rt._write_json(rt.execution_path(eid, data), rt.get_execution(eid, project))
    assert chat_delegation_session.session_active_delegations("chat-a") == []
    assert asyncio.run(routes.handle_cancel_delegation(request(eid))).status == 404
    with pytest.raises(ValueError, match="multiple projects"):
        rt.get_execution(eid)
    assert not rt.is_cancel_requested(eid, repo_root=project)


def test_corrupt_index_is_ignored_and_reads_do_not_create_missing_roots(stores):
    launch, data, project = stores
    index = task_execution_roots.index_path(project)
    index.parent.mkdir(parents=True)
    index.write_text("{broken", encoding="utf-8")
    assert rt.list_user_executions() == []
    assert not rt.runtime_dir(launch).exists()
    assert not project.exists()


def test_generated_library_uses_the_same_indexed_records(stores, monkeypatch):
    from thomas.server.routes import local_projects_generated as generated

    eid = create(stores[2])
    monkeypatch.setattr(generated, "_generated_deliverable_project", card_id)
    assert generated._generated_deliverable_projects() == [{"id": eid}]
    assert generated._find_generated_deliverable_project(f"generated-{eid}") == {"id": eid}


def test_generated_library_discovers_roots_once_for_all_records(stores, monkeypatch):
    from thomas.server.routes import local_projects_generated as generated

    eids = {create(stores[2], sid=f"chat-{i}") for i in range(6)}
    other = stores[2] / "another-project"
    eids.add(create(other))
    discover = task_execution_roots.roots_for_user
    calls = []

    def counted(root):
        calls.append(root)
        return discover(root)

    monkeypatch.setattr(task_execution_roots, "roots_for_user", counted)
    monkeypatch.setattr(generated, "_generated_deliverable_project", card_id)
    assert {row["id"] for row in generated._generated_deliverable_projects()} == eids
    assert len(calls) == 1, "Hydrating each library card must reuse its known record directory"


def test_listing_origin_overrides_a_stored_record_root(stores):
    eid = create(stores[2])
    path = rt.execution_path(eid, stores[2])
    payload = rt.get_execution(eid, stores[2])
    payload["_record_root"] = str(stores[1] / "wrong")
    rt._write_json(path, payload)
    before = path.read_bytes()
    for refresh in (True, False):
        rows = rt.list_user_executions(refresh=refresh)
        assert rows[0]["_record_root"] == str(stores[2].resolve())
    assert path.read_bytes() == before


def test_real_library_cards_reuse_records_and_do_not_walk_packages(stores, monkeypatch):
    from thomas.server.routes import deliverable_listing as listing
    from thomas.server.routes import local_projects_generated as generated

    base = stores[1] / "workspaces"
    monkeypatch.setattr(listing, "_WORKSPACES_BASE", base)
    expected = {}
    for i, entry in enumerate(("Index.html", "final report.pdf")):
        eid = create(stores[2], sid=f"library-{i}")
        wd = base / eid
        wd.mkdir(parents=True)
        (wd / entry).write_text("deliverable", encoding="utf-8")
        (wd / "node_modules" / "package").mkdir(parents=True)
        record = rt.get_execution(eid, stores[2])
        record["state"] = "completed"
        if entry.endswith("pdf"):
            (wd / "index.html").write_text("older web output", encoding="utf-8")
            record["proof"] = {"artifacts": [{"path": entry}]}
        rt._write_json(rt.execution_path(eid, stores[2]), record)
        expected[eid] = entry

    discover = task_execution_roots.roots_for_user
    discoveries = []

    def counted(root):
        discoveries.append(root)
        return discover(root)

    def no_recursive_scan(*args, **kwargs):
        pytest.fail("A proven or preferred entry must not recursively walk installed packages")

    monkeypatch.setattr(task_execution_roots, "roots_for_user", counted)
    monkeypatch.setattr(Path, "rglob", no_recursive_scan)
    cards = generated._generated_deliverable_projects()
    assert len(discoveries) == 1, "Nested deliverable detection must reuse the already-read record"
    assert {card["source_execution_id"]: card["artifact_name"] for card in cards} == expected
    assert {card["artifact_kind"] for card in cards} == {"web", "pdf"}
    pdf = next(card for card in cards if card["artifact_kind"] == "pdf")
    assert pdf["artifact_url"].endswith("/final%20report.pdf")


def test_project_worker_sweeps_do_not_discover_other_projects(stores):
    from datetime import datetime, timezone

    from thomas.server.stale_execution_sweep import sweep_stale_executions

    eid = create(stores[2])
    assert rt.list_executions(refresh=False) == []
    assert sweep_stale_executions(orphaned_before=datetime.now(timezone.utc)) == 0
    assert rt.get_execution(eid, stores[2])["state"] == "requested"
    assert [row["execution_id"] for row in rt.list_user_executions()] == [eid]


def test_user_listing_does_not_write_project_summary_caches(stores, monkeypatch):
    eid = create(stores[2])
    original_write = rt._write_json

    def guarded_write(path, payload):
        if path.name == rt.SUMMARY_FILENAME:
            raise PermissionError("project cache is read-only")
        return original_write(path, payload)

    monkeypatch.setattr(rt, "_write_json", guarded_write)
    assert [row["execution_id"] for row in rt.list_user_executions()] == [eid]
    assert [row["execution_id"] for row in chat_delegation_session.session_active_delegations("chat-a")] == [eid]
