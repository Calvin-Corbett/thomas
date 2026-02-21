import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from thomas.nodes.p048_nodes_reject_action import NodesRejectActionError, NodesRejectActionInput, reject_node_action
from thomas.cli.commands.nodes.p048_nodes_reject_action import click_command


def _write_store(tmp_path: Path, actions: dict) -> Path:
    store_path = tmp_path / "node_actions.json"
    store_path.write_text(json.dumps({"actions": actions}, indent=2) + "\n", encoding="utf-8")
    return store_path


def test_reject_action_success_updates_store(tmp_path: Path):
    store_path = _write_store(
        tmp_path,
        {
            "a1": {"node_id": "n1", "action_id": "a1", "status": "pending", "created_at": "2020-01-01T00:00:00Z"},
        },
    )
    payload = NodesRejectActionInput(node_id="n1", action_id="a1", reason="nope")
    out = reject_node_action(payload, state_dir=tmp_path)
    assert out.status == "rejected"
    assert out.reason == "nope"

    data = json.loads(store_path.read_text(encoding="utf-8"))
    assert data["actions"]["a1"]["status"] == "rejected"
    assert data["actions"]["a1"]["reason"] == "nope"
    assert "updated_at" in data["actions"]["a1"]


def test_reject_action_idempotent_when_already_rejected(tmp_path: Path):
    _write_store(
        tmp_path,
        {
            "a1": {"node_id": "n1", "action_id": "a1", "status": "rejected", "reason": "done", "updated_at": "x"},
        },
    )
    out = reject_node_action(NodesRejectActionInput(node_id="n1", action_id="a1"), state_dir=tmp_path)
    assert out.status == "rejected"
    assert out.reason == "done"


def test_reject_action_not_found(tmp_path: Path):
    _write_store(tmp_path, {})
    payload = NodesRejectActionInput(node_id="n1", action_id="missing", reason=None)
    with pytest.raises(NodesRejectActionError) as ei:
        reject_node_action(payload, state_dir=tmp_path)
    assert ei.value.code == "not_found"


def test_reject_action_invalid_input():
    with pytest.raises(NodesRejectActionError) as ei:
        NodesRejectActionInput.from_mapping({"node_id": "   ", "action_id": "a1"})
    assert ei.value.code == "invalid_input"


def test_cli_json_success(tmp_path: Path):
    _write_store(tmp_path, {"a1": {"node_id": "n1", "action_id": "a1", "status": "pending"}})
    runner = CliRunner()
    res = runner.invoke(
        click_command,
        ["--node-id", "n1", "--action-id", "a1", "--reason", "later", "--state-dir", str(tmp_path), "--json"],
    )
    assert res.exit_code == 0
    payload = json.loads(res.output)
    assert payload["ok"] is True
    assert payload["result"]["status"] == "rejected"


def test_cli_json_failure_missing_store(tmp_path: Path):
    # Don't create node_actions.json
    runner = CliRunner()
    res = runner.invoke(
        click_command,
        ["--node-id", "n1", "--action-id", "a1", "--state-dir", str(tmp_path), "--json"],
    )
    assert res.exit_code != 0
    payload = json.loads(res.output)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"
