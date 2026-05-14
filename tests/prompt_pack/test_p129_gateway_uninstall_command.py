import json
from pathlib import Path

import pytest

from thomas.cli.commands.gateway.p129_gateway_uninstall_command import (
    format_error,
    format_success,
)
from thomas.server.routes.gateway.p129_gateway_uninstall_command import (
    GatewayUninstallError,
    GatewayUninstallRequest,
    uninstall_gateway,
)


def _write_gateway_install(state_dir: Path) -> None:
    """Create a minimal fake gateway install footprint for tests."""

    gateway_dir = state_dir / "gateway"
    gateway_dir.mkdir(parents=True, exist_ok=True)
    (gateway_dir / "installed.txt").write_text("ok", encoding="utf-8")
    (state_dir / "gateway.json").write_text(json.dumps({"version": 1}), encoding="utf-8")


def test_uninstall_success_removes_gateway_files(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    _write_gateway_install(state_dir)

    req = GatewayUninstallRequest(state_dir=str(state_dir), dry_run=False, purge_state=False)
    result = uninstall_gateway(req)

    assert result.uninstalled is True
    assert result.dry_run is False
    assert result.already_absent is False
    assert any(p.endswith("/gateway") or p.endswith("\\gateway") for p in result.removed_paths)
    assert any(p.endswith("gateway.json") for p in result.removed_paths)

    assert not (state_dir / "gateway").exists()
    assert not (state_dir / "gateway.json").exists()


def test_uninstall_dry_run_does_not_touch_files(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    _write_gateway_install(state_dir)

    req = GatewayUninstallRequest(state_dir=str(state_dir), dry_run=True, purge_state=False)
    result = uninstall_gateway(req)

    assert result.dry_run is True
    assert result.uninstalled is False
    assert result.already_absent is False
    assert (state_dir / "gateway").exists()
    assert (state_dir / "gateway.json").exists()


def test_uninstall_absent_is_idempotent_success(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    req = GatewayUninstallRequest(state_dir=str(state_dir), dry_run=False, purge_state=False)
    result = uninstall_gateway(req)

    assert result.uninstalled is False
    assert result.already_absent is True
    assert result.dry_run is False


def test_uninstall_invalid_state_dir_error() -> None:
    # This should be rejected on all platforms.
    req = GatewayUninstallRequest(state_dir="/", dry_run=False, purge_state=False)
    with pytest.raises(GatewayUninstallError) as ei:
        uninstall_gateway(req)
    assert ei.value.code == "invalid_request"
    assert ei.value.http_status == 400


def test_uninstall_external_command_failure_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    state_dir = tmp_path / "state"
    _write_gateway_install(state_dir)
    (state_dir / "gateway.json").write_text(
        json.dumps({"uninstall_command": ["some-missing-bin-xyz"]}),
        encoding="utf-8",
    )

    def _fake_run(*args, **kwargs):
        raise FileNotFoundError("nope")

    import thomas.server.routes.gateway.p129_gateway_uninstall_command as mod

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)

    req = GatewayUninstallRequest(state_dir=str(state_dir), dry_run=False, purge_state=False)
    with pytest.raises(GatewayUninstallError) as ei:
        uninstall_gateway(req)

    err = ei.value
    assert err.code == "external_uninstall_failed"
    assert err.http_status == 502


def test_cli_json_output_is_machine_readable(tmp_path: Path) -> None:
    state_dir = tmp_path / "state"
    _write_gateway_install(state_dir)

    req = GatewayUninstallRequest(state_dir=str(state_dir), dry_run=True, purge_state=False)
    result = uninstall_gateway(req)

    s = format_success(result, json_output=True)
    payload = json.loads(s)
    assert payload["ok"] is True
    assert payload["result"]["dry_run"] is True

    err = GatewayUninstallError.invalid_request("boom")
    s2 = format_error(err, json_output=True)
    payload2 = json.loads(s2)
    assert payload2["ok"] is False
    assert payload2["error"]["code"] == "invalid_request"
