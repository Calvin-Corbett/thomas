import json
import subprocess
from argparse import Namespace

import pytest

from thomas.marketplace.nodes.p034_node_command_restart import (
    NodeRestartError,
    NodeRestartRequest,
    restart_node_host_service,
)


def _write_node_config(tmp_path, payload):
    path = tmp_path / "node.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_restart_success_systemd(monkeypatch, tmp_path):
    _write_node_config(tmp_path, {"serviceName": "thomas-node"})

    calls = {"count": 0}

    def fake_run(cmd, capture_output, text, timeout, check):
        calls["count"] += 1
        calls["cmd"] = cmd
        assert timeout == 5.0
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    res = restart_node_host_service(NodeRestartRequest(state_dir=tmp_path, timeout_s=5.0, manager="systemd"))

    assert res.ok is True
    assert res.service_name == "thomas-node"
    assert res.manager == "systemd"
    assert calls["count"] == 1
    assert res.steps[0].command[:3] == ["systemctl", "--user", "restart"]
    assert res.steps[0].returncode == 0


def test_restart_missing_config(tmp_path):
    with pytest.raises(NodeRestartError) as ei:
        restart_node_host_service(NodeRestartRequest(state_dir=tmp_path, manager="systemd"))

    assert ei.value.code == "missing_config"
    assert ei.value.exit_code == 2


def test_restart_invalid_config(tmp_path):
    (tmp_path / "node.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(NodeRestartError) as ei:
        restart_node_host_service(NodeRestartRequest(state_dir=tmp_path, manager="systemd"))

    assert ei.value.code == "invalid_config"
    assert ei.value.exit_code == 2


def test_restart_external_failure(monkeypatch, tmp_path):
    _write_node_config(tmp_path, {"serviceName": "thomas-node"})

    def fake_run(cmd, capture_output, text, timeout, check):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="nope")

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(NodeRestartError) as ei:
        restart_node_host_service(NodeRestartRequest(state_dir=tmp_path, timeout_s=5.0, manager="systemd"))

    assert ei.value.code == "external_failure"
    assert ei.value.exit_code == 1
    assert "steps" in ei.value.details


def test_cli_json_success(monkeypatch, tmp_path, capsys):
    from thomas.cli.commands.nodes import p034_node_command_restart as cli

    _write_node_config(tmp_path, {"serviceName": "thomas-node"})

    def fake_run(cmd, capture_output, text, timeout, check):
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    args = Namespace(
        json=True, state_dir=tmp_path, manager="systemd", timeout_s=5.0, config_path=None, service_name=None
    )
    code = cli.run(args)
    out = capsys.readouterr().out

    assert code == 0
    payload = json.loads(out)
    assert payload["ok"] is True
    assert payload["result"]["ok"] is True
    assert payload["result"]["service_name"] == "thomas-node"
    assert payload["result"]["manager"] == "systemd"
    assert payload["result"]["steps"][0]["command"][:3] == ["systemctl", "--user", "restart"]


def test_cli_json_failure_missing_config(tmp_path, capsys):
    from thomas.cli.commands.nodes import p034_node_command_restart as cli

    args = Namespace(
        json=True, state_dir=tmp_path, manager="systemd", timeout_s=5.0, config_path=None, service_name=None
    )
    code = cli.run(args)
    out = capsys.readouterr().out

    assert code == 2
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "missing_config"
