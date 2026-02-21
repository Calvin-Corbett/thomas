import json

import pytest

from thomas.nodes.p031_node_command_install import (
    NodeInstallConfigError,
    NodeInstallInputError,
    NodeInstallRequest,
    install_node_command,
)


def test_node_install_success_writes_files(tmp_path, monkeypatch):
    home = tmp_path / ".thomas"
    monkeypatch.setenv("THOMAS_HOME", str(home))
    monkeypatch.setenv("THOMAS_GATEWAY_TOKEN", "test-token")

    req = NodeInstallRequest(
        host="gateway.local",
        port=18789,
        tls=True,
        tls_fingerprint="aa" * 32,
        display_name="Build Node",
        force=True,
    )

    result = install_node_command(req, node_id_factory=lambda: "node-123")
    assert result.ok is True
    assert result.node_id == "node-123"

    cfg_path = home / "node.json"
    env_path = home / "node.env"
    svc_path = home / "services" / "thomas-node.service"

    assert cfg_path.exists()
    assert env_path.exists()
    assert svc_path.exists()

    cfg = json.loads(cfg_path.read_text("utf-8"))
    assert cfg["node"]["id"] == "node-123"
    assert cfg["node"]["display_name"] == "Build Node"
    assert cfg["gateway"]["host"] == "gateway.local"
    assert cfg["gateway"]["port"] == 18789
    assert cfg["gateway"]["tls"] is True
    assert cfg["gateway"]["tls_fingerprint"] == ("aa" * 32)
    assert cfg["runtime"] == "python"

    assert env_path.read_text("utf-8") == "THOMAS_GATEWAY_TOKEN=test-token\n"
    svc_text = svc_path.read_text("utf-8")
    assert "ExecStart=" in svc_text
    assert "EnvironmentFile=" in svc_text
    assert "Environment=THOMAS_HOME=" in svc_text


def test_node_install_missing_gateway_token_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_HOME", str(tmp_path / ".thomas"))
    monkeypatch.delenv("THOMAS_GATEWAY_TOKEN", raising=False)

    with pytest.raises(NodeInstallConfigError) as exc:
        install_node_command(NodeInstallRequest(host="127.0.0.1", port=18789, force=True))

    assert exc.value.code == "NODE_INSTALL_MISSING_GATEWAY_TOKEN"


def test_node_install_invalid_port_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_HOME", str(tmp_path / ".thomas"))
    monkeypatch.setenv("THOMAS_GATEWAY_TOKEN", "test-token")

    with pytest.raises(NodeInstallInputError) as exc:
        install_node_command(NodeInstallRequest(host="127.0.0.1", port=70000, force=True))

    assert exc.value.code == "NODE_INSTALL_INVALID_PORT"


def test_node_install_requires_force_when_already_installed(tmp_path, monkeypatch):
    home = tmp_path / ".thomas"
    monkeypatch.setenv("THOMAS_HOME", str(home))
    monkeypatch.setenv("THOMAS_GATEWAY_TOKEN", "test-token")

    # First install
    install_node_command(
        NodeInstallRequest(host="127.0.0.1", port=18789, force=True),
        node_id_factory=lambda: "node-123",
    )

    # Second install without --force should fail deterministically
    with pytest.raises(NodeInstallConfigError) as exc:
        install_node_command(NodeInstallRequest(host="127.0.0.1", port=18789, force=False))

    assert exc.value.code == "NODE_INSTALL_ALREADY_INSTALLED"


def test_node_install_invalid_tls_fingerprint_is_deterministic(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_HOME", str(tmp_path / ".thomas"))
    monkeypatch.setenv("THOMAS_GATEWAY_TOKEN", "test-token")

    with pytest.raises(NodeInstallInputError) as exc:
        install_node_command(
            NodeInstallRequest(
                host="127.0.0.1",
                port=18789,
                tls=True,
                tls_fingerprint="not-a-sha256",
                force=True,
            )
        )

    assert exc.value.code == "NODE_INSTALL_INVALID_TLS_FINGERPRINT"


def test_node_install_tls_fingerprint_requires_tls(tmp_path, monkeypatch):
    monkeypatch.setenv("THOMAS_HOME", str(tmp_path / ".thomas"))
    monkeypatch.setenv("THOMAS_GATEWAY_TOKEN", "test-token")

    with pytest.raises(NodeInstallInputError) as exc:
        install_node_command(
            NodeInstallRequest(
                host="127.0.0.1",
                port=18789,
                tls=False,
                tls_fingerprint="aa" * 32,
                force=True,
            )
        )

    assert exc.value.code == "NODE_INSTALL_TLS_FINGERPRINT_REQUIRES_TLS"


def test_node_install_force_overwrites_invalid_existing_config_with_warning(tmp_path, monkeypatch):
    home = tmp_path / ".thomas"
    monkeypatch.setenv("THOMAS_HOME", str(home))
    monkeypatch.setenv("THOMAS_GATEWAY_TOKEN", "test-token")

    home.mkdir(parents=True, exist_ok=True)
    (home / "node.json").write_text("not-json", encoding="utf-8")

    result = install_node_command(
        NodeInstallRequest(host="127.0.0.1", port=18789, force=True),
        node_id_factory=lambda: "node-123",
    )

    assert result.ok is True
    assert any("NODE_INSTALL_WARNING_INVALID_EXISTING_CONFIG" in w for w in result.warnings)
