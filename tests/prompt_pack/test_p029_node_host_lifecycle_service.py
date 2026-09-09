import json
from pathlib import Path

import pytest

from thomas.marketplace.nodes.p029_node_host_lifecycle_service import (
    NodeHostInstallRequest,
    NodeHostLifecycleService,
    NodeHostServiceError,
    NodeHostServiceErrorCode,
)


@pytest.fixture()
def thomas_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolate Thomas config writes for each test."""

    monkeypatch.setenv("THOMAS_HOME", str(tmp_path))
    return tmp_path


def test_install_then_status_running(thomas_home: Path) -> None:
    svc = NodeHostLifecycleService()

    result = svc.install(
        NodeHostInstallRequest(
            gateway_host="example.com",
            gateway_port=1234,
            tls=True,
            tls_fingerprint_sha256="sha256:" + "a" * 64,
            node_id="node-1",
            display_name="Build Node",
            runtime="python",
            force=False,
        )
    )

    assert result.ok is True
    assert result.status.installed is True
    assert result.status.running is True

    config_path = Path(result.status.config_path or "")
    state_path = Path(result.status.state_path or "")
    assert config_path.exists(), "config file should exist"
    assert state_path.exists(), "state file should exist"

    status = svc.status()
    assert status.installed is True
    assert status.running is True
    assert status.gateway_host == "example.com"
    assert status.gateway_port == 1234
    assert status.tls is True
    assert status.tls_fingerprint_sha256 == "a" * 64
    assert status.node_id == "node-1"
    assert status.display_name == "Build Node"


def test_stop_restart_and_uninstall(thomas_home: Path) -> None:
    svc = NodeHostLifecycleService()
    svc.install(NodeHostInstallRequest())

    stopped = svc.stop()
    assert stopped.ok is True
    assert stopped.status.running is False

    restarted = svc.restart()
    assert restarted.ok is True
    assert restarted.status.running is True

    uninstalled = svc.uninstall()
    assert uninstalled.ok is True
    assert uninstalled.status.installed is False
    assert uninstalled.status.running is False

    assert not svc.config_path.exists()
    assert not svc.state_path.exists()


def test_invalid_port_is_deterministic_error(thomas_home: Path) -> None:
    svc = NodeHostLifecycleService()

    with pytest.raises(NodeHostServiceError) as ei:
        svc.install(NodeHostInstallRequest(gateway_port=0))

    err = ei.value
    assert err.code == NodeHostServiceErrorCode.INVALID_INPUT
    assert "gateway_port" in str(err)


def test_stop_without_install_is_deterministic_error(thomas_home: Path) -> None:
    svc = NodeHostLifecycleService()

    with pytest.raises(NodeHostServiceError) as ei:
        svc.stop()

    err = ei.value
    assert err.code == NodeHostServiceErrorCode.NOT_INSTALLED


def test_cli_json_output_success_and_failure(thomas_home: Path, capsys: pytest.CaptureFixture[str]) -> None:
    # Import CLI module lazily so it picks up THOMAS_HOME.
    from thomas.cli.commands.nodes import p029_node_host_lifecycle_service as cli

    code = cli.main(["nodes", "host", "status", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["action"] == "status"
    assert payload["status"]["installed"] is False

    code = cli.main(
        [
            "nodes",
            "host",
            "install",
            "--host",
            "127.0.0.1",
            "--port",
            "18789",
            "--json",
        ]
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["action"] == "install"
    assert payload["status"]["installed"] is True

    # Idempotency error should be deterministic and machine-readable.
    code = cli.main(["nodes", "host", "install", "--json"])
    assert code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["action"] == "install"
    assert payload["error"]["code"] == "already_installed"

    code = cli.main(["nodes", "host", "stop", "--json"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["action"] == "stop"
    assert payload["status"]["running"] is False

    # Invalid input should also be machine-readable.
    code = cli.main(["nodes", "host", "install", "--port", "0", "--json", "--force"])
    assert code != 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
