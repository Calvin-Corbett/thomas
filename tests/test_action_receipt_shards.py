"""Receipt history migrates without making ordinary saves scale with its size."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from thomas.server.routes import evolve_agent_receipts as receipts


@pytest.fixture
def root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("THOMAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(receipts, "_KNOWN", {})
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


def _legacy(root: Path, count: int = 3, *, output_bytes: int = 8192) -> tuple[Path, dict[str, dict[str, Any]]]:
    path = receipts._receipt_path(root)
    history = {
        receipts._receipt_key("run", f"old-{i}"): {
            "state": "completed",
            "response": {"run_id": f"run-{i}"},
            "output": "x" * output_bytes,
        }
        for i in range(count)
    }
    path.write_text(json.dumps(history), encoding="utf-8")
    return path, history


def test_large_history_migrates_and_saves_only_the_requested_receipt(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Keep the original catalog's byte volume without thousands of filesystem operations.
    path, history = _legacy(root, 4, output_bytes=4_194_304)
    assert path.stat().st_size > 16_000_000
    receipts._save_action_receipt(root, "run", "new", {"state": "running"})
    marker = path.read_bytes()
    assert len(marker) < 128
    assert len(list(path.with_suffix("").glob("*/*.json"))) == len(history) + 1
    assert receipts._read_receipts(root) == {**history, receipts._receipt_key("run", "new"): {"state": "running"}}

    reads: list[Path] = []
    writes: list[Path] = []
    original_read, original_write = Path.read_text, receipts._write_receipts

    def read(item: Path, *args: Any, **kwargs: Any) -> str:
        reads.append(item)
        return original_read(item, *args, **kwargs)

    def write(item: Path, data: dict[str, dict[str, Any]]) -> None:
        writes.append(item)
        original_write(item, data)

    monkeypatch.setattr(Path, "read_text", read)
    monkeypatch.setattr(receipts, "_write_receipts", write)
    # Neither mutation nor lookup may enumerate or deserialize historical entries.
    monkeypatch.setattr(Path, "glob", lambda *args, **kwargs: pytest.fail("history was enumerated"))
    receipts._save_action_receipt(root, "run", "new", {"state": "completed"})
    key = receipts._receipt_key("run", "new")
    assert writes == [receipts._entry_path(path, key)]
    assert reads == writes
    assert receipts._action_receipt(root, "run", "new") == {"state": "completed"}
    assert reads == writes * 2
    assert path.read_bytes() == marker
    assert all(data == receipts._LAYOUT for _, data in receipts._KNOWN.values())


def test_receipt_is_synced_before_atomic_publication(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = root / "receipt.json"
    key = receipts._receipt_key("run", "synced")
    value = {key: {"state": "completed"}}
    events: list[str] = []
    sync, replace = receipts.os.fsync, receipts.os.replace

    def synced(fd: int) -> None:
        sync(fd)
        events.append("synced")

    def published(source: Any, destination: Any) -> None:
        assert events == ["synced"]
        assert not path.exists()
        replace(source, destination)
        events.append("published")

    monkeypatch.setattr(receipts.os, "fsync", synced)
    monkeypatch.setattr(receipts.os, "replace", published)
    receipts._write_receipts(path, value)
    assert events == ["synced", "published"]
    assert json.loads(path.read_text(encoding="utf-8")) == value


def test_failed_migration_sync_preserves_legacy_history(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, history = _legacy(root, 1)
    original = path.read_bytes()

    def fail_sync(fd: int) -> None:
        raise OSError("receipt sync failed")

    with monkeypatch.context() as patch:
        patch.setattr(receipts.os, "fsync", fail_sync)
        with pytest.raises(OSError, match="receipt sync failed"):
            receipts._action_receipt(root, "run", "old-0")
    assert path.read_bytes() == original
    assert not list(path.parent.rglob("*.tmp"))
    assert receipts._read_receipts(root) == history


def test_interrupted_migration_retains_legacy_source_and_can_retry(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, history = _legacy(root, 3)
    original = path.read_bytes()
    write = receipts._write_receipts
    calls = 0

    def interrupted(item: Path, data: dict[str, dict[str, Any]]) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk full")
        write(item, data)

    with monkeypatch.context() as patch:
        patch.setattr(receipts, "_write_receipts", interrupted)
        with pytest.raises(OSError, match="disk full"):
            receipts._save_action_receipt(root, "run", "new", {"state": "running"})
    assert path.read_bytes() == original
    receipts._save_action_receipt(root, "run", "new", {"state": "running"})
    assert receipts._read_receipts(root) == {**history, receipts._receipt_key("run", "new"): {"state": "running"}}


def test_failed_marker_publish_keeps_legacy_history_for_retry(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, history = _legacy(root, 3)
    original = path.read_bytes()
    replace = receipts.os.replace

    def fail_marker(source: Any, destination: Any) -> None:
        if Path(destination) == path:
            raise OSError("marker publish failed")
        replace(source, destination)

    with monkeypatch.context() as patch:
        patch.setattr(receipts.os, "replace", fail_marker)
        with pytest.raises(OSError, match="marker publish failed"):
            receipts._save_action_receipt(root, "run", "new", {})
    assert path.read_bytes() == original
    assert not list(path.parent.rglob("*.tmp"))
    assert receipts._read_receipts(root) == history
    for key, value in history.items():
        assert receipts._read_entry(receipts._entry_path(path, key), key) == value


@pytest.mark.parametrize("damage", ["corrupt", "wrong-key", "empty", "missing-marker", "missing-directory"])
def test_damaged_storage_fails_closed(root: Path, damage: str) -> None:
    receipts._save_action_receipt(root, "run", "old", {"state": "completed"})
    path = receipts._receipt_path(root)
    entry = receipts._entry_path(path, receipts._receipt_key("run", "old"))
    if damage == "corrupt":
        entry.write_text("not json", encoding="utf-8")
    elif damage == "wrong-key":
        entry.write_text(json.dumps({"wrong": {}}), encoding="utf-8")
    elif damage == "empty":
        entry.write_text("{}", encoding="utf-8")
    elif damage == "missing-marker":
        path.unlink()
    else:
        shutil.rmtree(path.with_suffix(""))
    with pytest.raises(RuntimeError):
        receipts._action_receipt(root, "run", "old")
    with pytest.raises(RuntimeError):
        receipts._save_action_receipt(root, "run", "old", {"state": "running"})
    with pytest.raises(RuntimeError):
        receipts._read_receipts(root)


@pytest.mark.parametrize("damage", ["receipt", "bucket", "index"])
def test_partial_store_loss_never_releases_an_old_id(root: Path, damage: str) -> None:
    receipts._save_action_receipt(root, "run", "old", {"state": "completed"})
    receipts._save_action_receipt(root, "run", "another", {"state": "completed"})
    path = receipts._receipt_path(root)
    entry = receipts._entry_path(path, receipts._receipt_key("run", "old"))
    if damage == "receipt":
        entry.unlink()
    elif damage == "bucket":
        shutil.rmtree(entry.parent)
    else:
        (path.with_suffix("") / "request_ids.sqlite3").unlink()
    receipts._KNOWN.clear()
    with pytest.raises(RuntimeError):
        receipts._action_receipt(root, "run", "old")
    with pytest.raises(RuntimeError):
        receipts._save_action_receipt(root, "run", "old", {})
    with pytest.raises(RuntimeError):
        receipts._read_receipts(root)


def test_first_initialization_can_retry_after_marker_failure(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = receipts._receipt_path(root)
    write = receipts._write_receipts

    def fail_marker(item: Path, data: dict[str, dict[str, Any]]) -> None:
        if data == receipts._LAYOUT:
            raise OSError("marker failed")
        write(item, data)

    with monkeypatch.context() as patch:
        patch.setattr(receipts, "_write_receipts", fail_marker)
        with pytest.raises(OSError, match="marker failed"):
            receipts._save_action_receipt(root, "run", "new", {})
    receipts._KNOWN.clear()
    assert path.read_text(encoding="utf-8") == "{}"
    assert receipts._action_receipt(root, "run", "new") is None
    receipts._save_action_receipt(root, "run", "new", {"state": "completed"})
    assert receipts._action_receipt(root, "run", "new") == {"state": "completed"}


def test_failed_first_receipt_write_reserves_id(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipts._action_receipt(root, "run", "new")
    with monkeypatch.context() as patch:
        patch.setattr(receipts, "_write_receipts", lambda *args: (_ for _ in ()).throw(OSError("write failed")))
        with pytest.raises(OSError, match="write failed"):
            receipts._save_action_receipt(root, "run", "new", {})
    receipts._KNOWN.clear()
    with pytest.raises(RuntimeError):
        receipts._action_receipt(root, "run", "new")


def test_invalid_legacy_keys_do_not_publish_a_partial_migration(root: Path) -> None:
    path, history = _legacy(root, 1)
    history["../../outside"] = {"state": "completed"}
    path.write_text(json.dumps(history), encoding="utf-8")
    original = path.read_bytes()
    with pytest.raises(RuntimeError, match="invalid key"):
        receipts._action_receipt(root, "run", "old-0")
    assert path.read_bytes() == original
    assert not path.with_suffix("").exists()


def test_atomic_receipt_update_failure_keeps_previous_value(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipts._save_action_receipt(root, "run", "old", {"state": "running"})

    def fail_replace(*args: Any) -> None:
        raise OSError("replace failed")

    with monkeypatch.context() as patch:
        patch.setattr(receipts.os, "replace", fail_replace)
        with pytest.raises(OSError, match="replace failed"):
            receipts._save_action_receipt(root, "run", "old", {"state": "completed"})
    assert receipts._action_receipt(root, "run", "old") == {"state": "running"}
    assert list(receipts._receipt_path(root).parent.rglob("*.tmp")) == []


def test_interrupted_rollback_commits_retry_permission_before_cleanup(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipts._save_action_receipt(root, "run", "retry", {"state": "launching"})
    key = receipts._receipt_key("run", "retry")
    entry = receipts._entry_path(receipts._receipt_path(root), key)
    unlink = Path.unlink

    def fail_cleanup(item: Path, *args: Any, **kwargs: Any) -> None:
        if item == entry:
            raise OSError("cleanup interrupted")
        unlink(item, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_cleanup)
        with pytest.raises(OSError, match="cleanup interrupted"):
            receipts._delete_action_receipt(root, "run", "retry")
    assert receipts._action_receipt(root, "run", "retry") is None
    receipts._delete_action_receipt(root, "run", "retry")
    assert not entry.exists()
    receipts._save_action_receipt(root, "run", "retry", {"state": "running"})
    assert receipts._action_receipt(root, "run", "retry") == {"state": "running"}


def test_failed_new_write_does_not_hide_other_receipts_from_recovery(
    root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipts._save_action_receipt(root, "run", "old", {"state": "completed"})
    write = receipts._write_receipts
    key = receipts._receipt_key("run", "failed")

    def fail_write(item: Path, data: dict[str, Any]) -> None:
        if key in data:
            raise OSError("new receipt failed")
        write(item, data)

    with monkeypatch.context() as patch:
        patch.setattr(receipts, "_write_receipts", fail_write)
        with pytest.raises(OSError, match="new receipt failed"):
            receipts._save_action_receipt(root, "run", "failed", {"state": "launching"})
    history = receipts._read_receipts(root)
    assert history[receipts._receipt_key("run", "old")] == {"state": "completed"}
    assert history[key] == {"state": "persistence_failed"}
    with pytest.raises(RuntimeError, match="missing"):
        receipts._action_receipt(root, "run", "failed")


def test_index_disappearing_during_open_is_not_recreated(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipts._save_action_receipt(root, "run", "old", {"state": "completed"})
    path = receipts._index_path(receipts._receipt_path(root).with_suffix(""))
    connect = receipts.sqlite3.connect

    def disappearing(*args: Any, **kwargs: Any) -> Any:
        path.unlink()
        return connect(*args, **kwargs)

    monkeypatch.setattr(receipts.sqlite3, "connect", disappearing)
    with pytest.raises(RuntimeError, match="unreadable"):
        receipts._action_receipt(root, "run", "old")
    assert not path.exists()


def test_index_with_nullable_keys_is_rejected(root: Path) -> None:
    receipts._save_action_receipt(root, "run", "old", {"state": "completed"})
    path = receipts._index_path(receipts._receipt_path(root).with_suffix(""))
    with receipts.sqlite3.connect(path) as index:
        index.execute("DROP TABLE requests")
        index.execute("CREATE TABLE requests (key TEXT PRIMARY KEY, deleted INTEGER NOT NULL)")
    with pytest.raises(RuntimeError, match="invalid schema"):
        receipts._action_receipt(root, "run", "old")


def test_failed_retry_cannot_resurrect_a_rolled_back_receipt(root: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    receipts._save_action_receipt(root, "run", "retry", {"state": "launching"})
    entry = receipts._entry_path(receipts._receipt_path(root), receipts._receipt_key("run", "retry"))
    unlink = Path.unlink
    write = receipts._write_receipts

    def fail_cleanup(path: Path, *args: Any, **kwargs: Any) -> None:
        if path == entry:
            raise OSError("cleanup interrupted")
        unlink(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "unlink", fail_cleanup)
        with pytest.raises(OSError, match="cleanup interrupted"):
            receipts._delete_action_receipt(root, "run", "retry")

    def fail_write(path: Path, data: dict[str, Any]) -> None:
        if path == entry:
            raise OSError("retry interrupted")
        write(path, data)

    with monkeypatch.context() as patch:
        patch.setattr(receipts, "_write_receipts", fail_write)
        with pytest.raises(OSError, match="retry interrupted"):
            receipts._save_action_receipt(root, "run", "retry", {"state": "running"})
    with pytest.raises(RuntimeError, match="missing"):
        receipts._action_receipt(root, "run", "retry")
    assert receipts._read_receipts(root)[receipts._receipt_key("run", "retry")] == {"state": "persistence_failed"}


@pytest.mark.parametrize("state", [3, "invalid"])
def test_invalid_index_state_is_refused(root: Path, state: Any) -> None:
    receipts._save_action_receipt(root, "run", "old", {"state": "completed"})
    with receipts._index(receipts._receipt_path(root).with_suffix("")) as index:
        index.execute("UPDATE requests SET deleted = ?", (state,))
    with pytest.raises(RuntimeError, match="invalid state"):
        receipts._action_receipt(root, "run", "old")
    with pytest.raises(RuntimeError, match="invalid state"):
        receipts._read_receipts(root)
