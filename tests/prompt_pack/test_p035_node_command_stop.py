import json

import pytest


def test_stop_invalid_input_empty_node_id():
    from thomas.nodes.p035_node_command_stop import (
        NodeCommandStopInput,
        NodeCommandStopInvalidInputError,
        node_command_stop,
    )

    with pytest.raises(NodeCommandStopInvalidInputError) as ei:
        node_command_stop(NodeCommandStopInput(node_id=""), backend=lambda *_args, **_kwargs: True)

    assert ei.value.code == "THOMAS_NODE_STOP_INVALID_INPUT"
    assert "node_id" in str(ei.value)


def test_stop_missing_config_path_is_deterministic(tmp_path):
    from thomas.nodes.p035_node_command_stop import (
        NodeCommandStopConfigError,
        NodeCommandStopInput,
        node_command_stop,
    )

    missing = tmp_path / "does_not_exist.json"
    with pytest.raises(NodeCommandStopConfigError) as ei:
        node_command_stop(
            NodeCommandStopInput(node_id="node-1", config_path=str(missing)),
            backend=lambda *_args, **_kwargs: True,
        )

    assert ei.value.code == "THOMAS_NODE_STOP_MISSING_CONFIG"
    assert ei.value.to_json()["details"]["config_path"].endswith("does_not_exist.json")


def test_stop_external_failure_is_wrapped_deterministically():
    from thomas.nodes.p035_node_command_stop import (
        NodeCommandStopExternalError,
        NodeCommandStopInput,
        node_command_stop,
    )

    def boom(*_args, **_kwargs):
        raise RuntimeError("kaboom")

    with pytest.raises(NodeCommandStopExternalError) as ei:
        node_command_stop(NodeCommandStopInput(node_id="node-1"), backend=boom)

    assert ei.value.code == "THOMAS_NODE_STOP_EXTERNAL_FAILURE"
    assert str(ei.value) == "failed to stop node"
    assert ei.value.to_json()["details"]["reason"] == "RuntimeError"


def test_stop_backend_reported_failure_is_deterministic():
    from thomas.nodes.p035_node_command_stop import (
        NodeCommandStopExternalError,
        NodeCommandStopInput,
        node_command_stop,
    )

    with pytest.raises(NodeCommandStopExternalError) as ei:
        node_command_stop(NodeCommandStopInput(node_id="node-1"), backend=lambda *_a, **_k: False)

    assert ei.value.code == "THOMAS_NODE_STOP_EXTERNAL_FAILURE"
    assert str(ei.value) == "failed to stop node"
    assert ei.value.to_json()["details"]["reason"] == "BackendReportedFailure"


def test_stop_success_returns_contract():
    from thomas.nodes.p035_node_command_stop import NodeCommandStopInput, node_command_stop

    out = node_command_stop(NodeCommandStopInput(node_id="node-1"), backend=lambda *_a, **_k: True)
    assert out.ok is True
    assert out.node_id == "node-1"
    assert out.stopped is True
    assert "stopped" in out.message


def test_stop_signature_adaptation_accepts_node_param():
    from thomas.nodes.p035_node_command_stop import NodeCommandStopInput, node_command_stop

    captured = {}

    def backend(node: str, force: bool = False):
        captured["node"] = node
        captured["force"] = force
        return True

    out = node_command_stop(NodeCommandStopInput(node_id="node-xyz", force=True), backend=backend)
    assert out.ok is True
    assert captured == {"node": "node-xyz", "force": True}


def test_cli_json_output_success(monkeypatch):
    """The CLI module should support --json output for automation."""

    from click.testing import CliRunner

    import thomas.cli.commands.nodes.p035_node_command_stop as cli_mod
    from thomas.nodes.p035_node_command_stop import NodeCommandStopOutput

    runner = CliRunner()

    def fake_stop(_inp):
        return NodeCommandStopOutput(ok=True, node_id="node-xyz", stopped=True, message="ok")

    monkeypatch.setattr(cli_mod, "node_command_stop", fake_stop)

    res = runner.invoke(cli_mod.click_command, ["node-xyz", "--json"])
    assert res.exit_code == 0
    payload = json.loads(res.stdout.strip())
    assert payload["ok"] is True
    assert payload["node_id"] == "node-xyz"
    assert payload["stopped"] is True


def test_cli_json_output_failure(monkeypatch):
    from click.testing import CliRunner

    import thomas.cli.commands.nodes.p035_node_command_stop as cli_mod
    from thomas.nodes.p035_node_command_stop import NodeCommandStopInvalidInputError

    runner = CliRunner()

    def fake_stop(_inp):
        raise NodeCommandStopInvalidInputError("node_id must be a non-empty string", details={"field": "node_id"})

    monkeypatch.setattr(cli_mod, "node_command_stop", fake_stop)

    res = runner.invoke(cli_mod.click_command, ["node-xyz", "--json"])
    assert res.exit_code == 2
    payload = json.loads(res.stdout.strip())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "THOMAS_NODE_STOP_INVALID_INPUT"
