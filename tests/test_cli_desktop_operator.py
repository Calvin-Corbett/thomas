from __future__ import annotations

import json
from pathlib import Path

import click
from click.testing import CliRunner

from thomas.cli.commands.desktop_operator import register_desktop_operator_commands


def _write_min_config(path: Path) -> Path:
    cfg = path / "thomas.toml"
    cfg.write_text(
        """
default_model = "local"

[memory]
root = "./runtime"

[models.local]
provider = "ollama"
base_url = "http://127.0.0.1:11434/v1"
model = "qwen2.5-coder:7b"
""".strip(),
        encoding="utf-8",
    )
    return cfg


def test_cli_desktop_operator_status_json(tmp_path: Path, monkeypatch) -> None:
    class _StubManager:
        def status_snapshot(self):
            return {
                "service_id": "desktop.operator",
                "running": True,
                "connection_mode": "remote_vm",
                "vm": {"vm_id": "vm-magic-01", "provider": "hyperv_local_vm", "isolated": True},
                "viewer": {
                    "available": True,
                    "mode": "hyperv_console",
                    "label": "Hyper-V console",
                    "url": "",
                    "command": 'vmconnect.exe localhost "ThomasWorker"',
                    "takeover_supported": True,
                },
                "vm_bootstrap": {
                    "launch_mode": "remote_helper_bootstrapped",
                    "guest_workspace": r"C:\ThomasDesktop",
                    "helper_ready": True,
                    "refusal_reason": "",
                },
                "host_posture": {
                    "installation_state": "local_vm_ready",
                    "session_target": "local_vm",
                    "trust_mode": "ask_every_time",
                    "local_vm_ready": True,
                    "next_action": "Start an isolated desktop session.",
                },
            }

    monkeypatch.setattr(
        "thomas.cli.commands.desktop_operator.get_global_desktop_operator_manager",
        lambda: _StubManager(),
    )

    group = click.Group("thomas")
    register_desktop_operator_commands(group)
    runner = CliRunner()
    result = runner.invoke(group, ["desktop-operator", "status", "--json-output"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["service_id"] == "desktop.operator"
    assert payload["connection_mode"] == "remote_vm"
    assert payload["viewer"]["mode"] == "hyperv_console"


def test_cli_desktop_operator_bootstrap_json(tmp_path: Path, monkeypatch) -> None:
    bootstrap_payload = {
        "vm_name": "ThomasWorker",
        "snapshot_name": "thomas-clean",
        "helper_base_url": "http://10.0.0.9:18734",
        "artifact_ingress_dir": str(tmp_path / "ingress"),
        "artifact_egress_dir": str(tmp_path / "egress"),
        "guest_workspace": r"C:\ThomasDesktop",
        "guest_launch_script_path": str(tmp_path / "launch-helper.ps1"),
        "guest_register_task_script_path": str(tmp_path / "register-helper-task.ps1"),
        "startup_command": "python -m thomas.desktop_operator.helper_main --host 0.0.0.0 --port 18734",
        "viewer_mode": "hyperv_console",
        "viewer_label": "Hyper-V console",
        "viewer_url": "",
        "viewer_command": 'vmconnect.exe localhost "ThomasWorker"',
        "refusal_reason": "",
    }

    class _StubSupervisor:
        def build_bootstrap(self):
            class _Obj:
                def to_dict(self_nonlocal):
                    return dict(bootstrap_payload)

            return _Obj()

    monkeypatch.setattr(
        "thomas.cli.commands.desktop_operator.resolve_vm_context",
        lambda: object(),
    )
    monkeypatch.setattr(
        "thomas.cli.commands.desktop_operator.resolve_artifacts_dir",
        lambda: tmp_path,
    )
    monkeypatch.setattr(
        "thomas.cli.commands.desktop_operator.create_vm_supervisor",
        lambda *args, **kwargs: _StubSupervisor(),
    )

    group = click.Group("thomas")
    register_desktop_operator_commands(group)
    runner = CliRunner()
    result = runner.invoke(
        group,
        [
            "desktop-operator",
            "bootstrap",
            "--vm-name",
            "ThomasWorker",
            "--vm-address",
            "10.0.0.9",
            "--helper-port",
            "18734",
            "--managed",
            "--json-output",
        ],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["vm_name"] == "ThomasWorker"
    assert payload["helper_base_url"] == "http://10.0.0.9:18734"
    assert payload["next_steps"]


def test_cli_desktop_operator_install_host_json(monkeypatch) -> None:
    class _StubService:
        def request_opt_in(self, *, hidden_by_default: bool = True):
            class _Obj:
                def to_dict(self_nonlocal):
                    return {"installation_state": "host_service_not_installed"}

            return _Obj()

        def launch_host_service_install(self):
            return {
                "ok": True,
                "launched": True,
                "posture": {
                    "installation_state": "host_service_installing",
                    "next_action": "Approve the Windows admin prompt to install isolated desktop mode.",
                },
            }

    monkeypatch.setattr(
        "thomas.cli.commands.desktop_operator.get_global_desktop_host_service",
        lambda: _StubService(),
    )

    group = click.Group("thomas")
    register_desktop_operator_commands(group)
    runner = CliRunner()
    result = runner.invoke(group, ["desktop-operator", "install-host", "--json-output"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["launched"] is True
    assert payload["posture"]["installation_state"] == "host_service_installing"
