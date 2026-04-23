import json
from pathlib import Path

import pytest

from thomas.cli.commands.nodes.p028_node_host_state_store import cli_main
from thomas.marketplace.nodes.p028_node_host_state_store import (
    NodeHostStateStore,
    NodeHostStateStoreConfigError,
    NodeHostStateStoreExternalFailureError,
    NodeHostStateStoreInvalidInputError,
    resolve_host_state_store_dir,
)


def test_put_get_round_trip(tmp_path: Path) -> None:
    store = NodeHostStateStore(tmp_path)
    rec = store.put("hostA", {"status": "online", "cpu": 0.42}, updated_at="2026-02-20T00:00:00Z")
    assert rec.host_id == "hostA"
    assert rec.updated_at == "2026-02-20T00:00:00+00:00"
    assert rec.state["status"] == "online"

    loaded = store.get("hostA")
    assert loaded is not None
    assert loaded.host_id == "hostA"
    assert loaded.updated_at == "2026-02-20T00:00:00+00:00"
    assert loaded.state == {"status": "online", "cpu": 0.42}


def test_list_is_deterministic(tmp_path: Path) -> None:
    store = NodeHostStateStore(tmp_path)
    store.put("b", {"n": 2}, updated_at="2026-02-20T00:00:00+00:00")
    store.put("a", {"n": 1}, updated_at="2026-02-20T00:00:01+00:00")

    records = store.list()
    assert [r.host_id for r in records] == ["a", "b"]


def test_scan_collects_corrupt_record_errors(tmp_path: Path) -> None:
    store = NodeHostStateStore(tmp_path)
    store.put("good", {"x": 1}, updated_at="2026-02-20T00:00:00+00:00")
    (tmp_path / "bad.json").write_text("{not-json", encoding="utf-8")

    records, errors = store.scan()
    assert [r.host_id for r in records] == ["good"]
    assert len(errors) == 1
    assert errors[0]["error"]["code"] == "corrupt_record"


def test_invalid_host_id_is_deterministic(tmp_path: Path) -> None:
    store = NodeHostStateStore(tmp_path)
    with pytest.raises(NodeHostStateStoreInvalidInputError) as excinfo:
        store.put("bad/id", {"x": 1})
    assert excinfo.value.code == "invalid_host_id"


def test_invalid_updated_at_is_deterministic(tmp_path: Path) -> None:
    store = NodeHostStateStore(tmp_path)
    with pytest.raises(NodeHostStateStoreInvalidInputError) as excinfo:
        store.put("host1", {"x": 1}, updated_at="2026-02-20T00:00:00")  # missing timezone
    assert excinfo.value.code == "invalid_updated_at"


def test_missing_config_can_error_deterministically() -> None:
    env = {}
    with pytest.raises(NodeHostStateStoreConfigError) as excinfo:
        resolve_host_state_store_dir(None, env=env, allow_default=False)
    assert excinfo.value.code == "missing_store_dir"


def test_invalid_store_dir_path_is_deterministic(tmp_path: Path) -> None:
    not_a_dir = tmp_path / "file.txt"
    not_a_dir.write_text("x", encoding="utf-8")
    with pytest.raises(NodeHostStateStoreConfigError) as excinfo:
        NodeHostStateStore(not_a_dir)
    assert excinfo.value.code == "invalid_store_dir"


def test_corrupt_record_get_is_deterministic(tmp_path: Path) -> None:
    store = NodeHostStateStore(tmp_path)
    (tmp_path / "host1.json").write_text("{not-json", encoding="utf-8")
    with pytest.raises(NodeHostStateStoreExternalFailureError) as excinfo:
        store.get("host1")
    assert excinfo.value.code == "corrupt_record"


def test_cli_json_set_get_delete_and_merge(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store_dir = str(tmp_path)

    code = cli_main(
        [
            "host-state-store",
            "--store-dir",
            store_dir,
            "--json",
            "set",
            "hostZ",
            "--state",
            json.dumps({"a": 1}),
            "--updated-at",
            "2026-02-20T00:00:00Z",
        ],
        env={},
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["record"]["host_id"] == "hostZ"
    assert payload["record"]["updated_at"] == "2026-02-20T00:00:00+00:00"
    assert payload["record"]["state"]["a"] == 1

    # Merge new key
    code = cli_main(
        [
            "host-state-store",
            "--store-dir",
            store_dir,
            "--json",
            "set",
            "hostZ",
            "--merge",
            "--state",
            json.dumps({"b": 2}),
        ],
        env={},
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["record"]["state"] == {"a": 1, "b": 2}

    code = cli_main(
        [
            "host-state-store",
            "--store-dir",
            store_dir,
            "--json",
            "get",
            "hostZ",
        ],
        env={},
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["found"] is True
    assert payload["record"]["state"] == {"a": 1, "b": 2}

    code = cli_main(
        [
            "host-state-store",
            "--store-dir",
            store_dir,
            "--json",
            "delete",
            "hostZ",
        ],
        env={},
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["deleted"] is True

    code = cli_main(
        [
            "host-state-store",
            "--store-dir",
            store_dir,
            "--json",
            "get",
            "hostZ",
        ],
        env={},
    )
    assert code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["found"] is False


def test_cli_invalid_input_json_mode(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store_dir = str(tmp_path)
    code = cli_main(
        [
            "host-state-store",
            "--store-dir",
            store_dir,
            "--json",
            "set",
            "bad/id",
            "--state",
            json.dumps({"x": 1}),
        ],
        env={},
    )
    assert code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_host_id"
