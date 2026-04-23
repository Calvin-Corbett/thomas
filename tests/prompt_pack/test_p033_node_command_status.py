import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from thomas.cli.commands.nodes.p033_node_command_status import cli as status_cli
from thomas.marketplace.nodes.p033_node_command_status import (
    NodeCommandStatusConfigError,
    NodeCommandStatusInvalidInputError,
    NodeCommandStatusNotFoundError,
    NodeCommandStatusRequest,
    get_node_command_status,
)


def test_node_command_status_success_from_state_file(tmp_path: Path) -> None:
    # Arrange: create a deterministic command status record
    command_id = "cmd-123"
    record = {
        "command_id": command_id,
        "node_id": "node-a",
        "state": "running",
        "done": False,
        "stdout": "hello",
        "stderr": "warn",
        "exit_code": None,
    }
    (tmp_path / f"{command_id}.json").write_text(json.dumps(record), encoding="utf-8")

    # Act
    resp = get_node_command_status(
        NodeCommandStatusRequest(command_id=command_id, include_output=False, state_dir=tmp_path)
    )

    # Assert
    assert resp.command_id == command_id
    assert resp.node_id == "node-a"
    assert resp.state == "running"
    assert resp.done is False
    assert resp.success is None
    # output excluded by default
    assert resp.stdout is None
    assert resp.stderr is None


def test_node_command_status_include_output(tmp_path: Path) -> None:
    command_id = "cmd-124"
    record = {"command_id": command_id, "state": "succeeded", "stdout": "ok", "stderr": "", "exit_code": 0}
    (tmp_path / f"{command_id}.json").write_text(json.dumps(record), encoding="utf-8")

    resp = get_node_command_status(
        NodeCommandStatusRequest(command_id=command_id, include_output=True, state_dir=tmp_path)
    )
    assert resp.state == "succeeded"
    assert resp.done is True
    assert resp.success is True
    assert resp.stdout == "ok"


def test_node_command_status_not_found(tmp_path: Path) -> None:
    with pytest.raises(NodeCommandStatusNotFoundError) as ei:
        get_node_command_status(NodeCommandStatusRequest(command_id="missing-1", state_dir=tmp_path))
    assert ei.value.code == "not_found"


def test_node_command_status_invalid_command_id_rejected(tmp_path: Path) -> None:
    with pytest.raises(NodeCommandStatusInvalidInputError) as ei:
        get_node_command_status(NodeCommandStatusRequest(command_id="../oops", state_dir=tmp_path))
    assert ei.value.code == "invalid_input"


def test_node_command_status_missing_config(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # Ensure we don't accidentally pick up a real user config.
    monkeypatch.delenv("THOMAS_NODE_COMMAND_STATE_DIR", raising=False)
    monkeypatch.delenv("THOMAS_STATE_DIR", raising=False)
    monkeypatch.delenv("THOMAS_CONFIG", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    with pytest.raises(NodeCommandStatusConfigError) as ei:
        get_node_command_status(NodeCommandStatusRequest(command_id="cmd-999"))
    assert ei.value.code == "missing_config"


def test_cli_json_output_success(tmp_path: Path) -> None:
    command_id = "cmd-200"
    record = {"command_id": command_id, "state": "succeeded", "done": True, "success": True, "exit_code": 0}
    (tmp_path / f"{command_id}.json").write_text(json.dumps(record), encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(
        status_cli,
        [command_id, "--json"],
        env={"THOMAS_NODE_COMMAND_STATE_DIR": str(tmp_path)},
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["command_id"] == command_id
    assert payload["state"] == "succeeded"
    assert payload["success"] is True


def test_cli_json_output_not_found(tmp_path: Path) -> None:
    runner = CliRunner()
    result = runner.invoke(
        status_cli,
        ["missing-2", "--json"],
        env={"THOMAS_NODE_COMMAND_STATE_DIR": str(tmp_path)},
    )

    assert result.exit_code == 4
    payload = json.loads(result.output)
    assert payload["code"] == "not_found"
