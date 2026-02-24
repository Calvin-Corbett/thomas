from __future__ import annotations

import json

from thomas.core.persistence import PersistenceEngine
from thomas.server.workspaces import WorkspaceStore


def test_persistence_save_is_atomic_and_leaves_no_tmp_file(tmp_path):
    state_file = tmp_path / "thomas_state.json"
    engine = PersistenceEngine(state_file=state_file, report_dir=tmp_path, auto_save=False)
    engine.record_turn("chat", "hello", "world")

    assert engine.save() is True
    assert state_file.exists()
    assert not state_file.with_suffix(state_file.suffix + ".tmp").exists()

    payload = json.loads(state_file.read_text(encoding="utf-8"))
    assert isinstance(payload.get("turn_history"), list)
    assert len(payload["turn_history"]) == 1


def test_workspace_store_quarantines_corrupt_primary_and_recovers_backup(tmp_path):
    store_path = tmp_path / "workspaces.json"
    store = WorkspaceStore(store_path)
    store.create_workspace("Primary", owner_user_id="alice")
    store.create_workspace("Secondary", owner_user_id="alice")

    backup_path = store_path.with_suffix(store_path.suffix + ".bak")
    assert backup_path.exists()

    # Simulate primary file corruption after a valid backup exists.
    store_path.write_text("{ this is not json", encoding="utf-8")

    recovered = WorkspaceStore(store_path)
    workspaces = recovered.list_workspaces("alice")
    assert len(workspaces) >= 1

    quarantined = list(tmp_path.glob("workspaces.json.corrupt.*"))
    assert quarantined, "expected corrupt primary file to be quarantined"


def test_workspace_store_quarantines_corrupt_primary_without_backup(tmp_path):
    store_path = tmp_path / "workspaces.json"
    store_path.write_text("{ broken", encoding="utf-8")

    store = WorkspaceStore(store_path)
    assert store.list_workspaces("alice") == []

    quarantined = list(tmp_path.glob("workspaces.json.corrupt.*"))
    assert quarantined, "expected corrupt workspace file to be quarantined"
