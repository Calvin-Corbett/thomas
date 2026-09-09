import json
from pathlib import Path

import pytest

from thomas.cli.commands.nodes.p049_nodes_pairing_handshake import main as cli_main
from thomas.marketplace.nodes.p049_nodes_pairing_handshake import (
    NodesPairingHandshakeError,
    NodesPairingHandshakeInput,
    nodes_pairing_handshake,
)


def test_pairing_handshake_creates_and_reuses_pending_request(tmp_path: Path) -> None:
    out1 = nodes_pairing_handshake(
        NodesPairingHandshakeInput(node_id="node-123", display_name="Kitchen iPad"),
        state_dir=tmp_path,
        now_ms=lambda: 1_000,
        ttl_ms=10_000,
    )
    assert out1.ok is True
    assert out1.created is True
    assert out1.node_id == "node-123"
    assert out1.display_name == "Kitchen iPad"
    assert out1.request_id
    assert out1.expires_at_ms == 11_000

    # Calling again before expiry should reuse the same request id (idempotent per node).
    out2 = nodes_pairing_handshake(
        NodesPairingHandshakeInput(node_id="node-123", display_name="Kitchen iPad"),
        state_dir=tmp_path,
        now_ms=lambda: 2_000,
        ttl_ms=10_000,
    )
    assert out2.ok is True
    assert out2.created is False
    assert out2.request_id == out1.request_id

    pending_path = tmp_path / "nodes" / "pending.json"
    assert pending_path.exists()
    pending = json.loads(pending_path.read_text(encoding="utf-8"))
    assert out1.request_id in pending
    assert pending[out1.request_id]["node_id"] == "node-123"


def test_pairing_handshake_expires_and_creates_new_request(tmp_path: Path) -> None:
    out1 = nodes_pairing_handshake(
        NodesPairingHandshakeInput(node_id="node-abc"),
        state_dir=tmp_path,
        now_ms=lambda: 1_000,
        ttl_ms=1_000,
    )

    out2 = nodes_pairing_handshake(
        NodesPairingHandshakeInput(node_id="node-abc"),
        state_dir=tmp_path,
        now_ms=lambda: 3_000,  # after expiry
        ttl_ms=1_000,
    )
    assert out2.request_id != out1.request_id
    assert out2.created is True


def test_pairing_handshake_rejects_invalid_input(tmp_path: Path) -> None:
    with pytest.raises(NodesPairingHandshakeError) as ei:
        nodes_pairing_handshake(NodesPairingHandshakeInput(node_id=""), state_dir=tmp_path)
    assert ei.value.code == "invalid_input"

    with pytest.raises(NodesPairingHandshakeError) as ei2:
        nodes_pairing_handshake(NodesPairingHandshakeInput(node_id=" space "), state_dir=tmp_path)
    assert ei2.value.code == "invalid_input"

    with pytest.raises(NodesPairingHandshakeError) as ei3:
        nodes_pairing_handshake(NodesPairingHandshakeInput(node_id="!!!"), state_dir=tmp_path)
    assert ei3.value.code == "invalid_input"

    with pytest.raises(NodesPairingHandshakeError) as ei4:
        nodes_pairing_handshake(NodesPairingHandshakeInput(node_id="node-1"), state_dir=tmp_path, ttl_ms=0)
    assert ei4.value.code == "invalid_input"


def test_pairing_handshake_missing_config_state_dir_is_file(tmp_path: Path) -> None:
    # If state_dir points at a file, treat as missing config deterministically.
    bad_state_dir = tmp_path / "not_a_dir"
    bad_state_dir.write_text("x", encoding="utf-8")

    with pytest.raises(NodesPairingHandshakeError) as ei:
        nodes_pairing_handshake(NodesPairingHandshakeInput(node_id="node-1"), state_dir=bad_state_dir)

    assert ei.value.code == "missing_config"


def test_pairing_handshake_storage_error_on_corrupt_pending_store(tmp_path: Path) -> None:
    nodes_dir = tmp_path / "nodes"
    nodes_dir.mkdir(parents=True, exist_ok=True)
    (nodes_dir / "pending.json").write_text("{not-json", encoding="utf-8")

    with pytest.raises(NodesPairingHandshakeError) as ei:
        nodes_pairing_handshake(NodesPairingHandshakeInput(node_id="node-1"), state_dir=tmp_path)

    assert ei.value.code == "storage_error"


def test_state_dir_env_fallback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("THOMAS_STATE_DIR", str(tmp_path))
    out = nodes_pairing_handshake(NodesPairingHandshakeInput(node_id="node-env"))
    assert out.node_id == "node-env"
    assert (tmp_path / "nodes" / "pending.json").exists()


def test_cli_json_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli_main(
        [
            "--node-id",
            "node-xyz",
            "--display-name",
            "Build Server",
            "--state-dir",
            str(tmp_path),
            "--json",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert payload["ok"] is True
    assert payload["payload"]["node_id"] == "node-xyz"
    assert payload["payload"]["display_name"] == "Build Server"
    assert payload["payload"]["request_id"]


def test_cli_json_failure_invalid_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli_main(["--node-id", "!!!", "--state-dir", str(tmp_path), "--json"])
    assert rc == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_input"
