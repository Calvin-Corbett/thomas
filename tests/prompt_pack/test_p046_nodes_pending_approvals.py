import json

import pytest


def test_nodes_pending_approvals_success(tmp_path):
    from thomas.nodes.p046_nodes_pending_approvals import NodesPendingApprovalsInput, nodes_pending_approvals

    state_dir = tmp_path
    store_path = state_dir / "nodes" / "pending_approvals.json"
    store_path.parent.mkdir(parents=True, exist_ok=True)

    store_path.write_text(
        json.dumps(
            [
                {
                    "node_id": "node-123",
                    "requested_at": "2026-02-20T00:00:00Z",
                    "requested_by": "alice",
                    "reason": "new node enrollment",
                    "metadata": {"ip": "10.0.0.5"},
                },
                {
                    "node_id": "node-456",
                    "requested_at": "2026-02-19T00:00:00Z",
                    "requested_by": "bob",
                    "reason": "new node enrollment",
                },
            ]
        ),
        encoding="utf-8",
    )

    out = nodes_pending_approvals(NodesPendingApprovalsInput(state_dir=str(state_dir)))
    payload = out.to_dict()

    assert payload["count"] == 2
    assert {a["node_id"] for a in payload["approvals"]} == {"node-123", "node-456"}


def test_nodes_pending_approvals_missing_config_is_deterministic(monkeypatch):
    from thomas.nodes import p046_nodes_pending_approvals as mod

    monkeypatch.delenv("THOMAS_STATE_DIR", raising=False)
    monkeypatch.setattr(mod, "_try_state_dir_from_parity_compat", lambda: None)
    monkeypatch.setattr(mod, "_try_load_thomas_config", lambda: None)

    with pytest.raises(mod.NodesPendingApprovalsError) as exc:
        mod.nodes_pending_approvals(mod.NodesPendingApprovalsInput(state_dir=None))

    assert exc.value.code == mod.ERROR_CONFIG_MISSING


def test_nodes_pending_approvals_invalid_store_json(tmp_path):
    from thomas.nodes import p046_nodes_pending_approvals as mod

    state_dir = tmp_path
    store_path = state_dir / "nodes" / "pending_approvals.json"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text("{ not-json", encoding="utf-8")

    with pytest.raises(mod.NodesPendingApprovalsError) as exc:
        mod.nodes_pending_approvals(mod.NodesPendingApprovalsInput(state_dir=str(state_dir)))

    assert exc.value.code == mod.ERROR_EXTERNAL_FAILURE


def test_cli_json_success(tmp_path, capsys):
    from thomas.cli.commands.nodes.p046_nodes_pending_approvals import cli_main

    state_dir = tmp_path
    store_path = state_dir / "nodes" / "pending_approvals.json"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store_path.write_text(json.dumps([{"node_id": "node-1"}]), encoding="utf-8")

    rc = cli_main(["--state-dir", str(state_dir), "--json"])
    assert rc == 0

    stdout = capsys.readouterr().out
    doc = json.loads(stdout)
    assert doc["ok"] is True
    assert doc["count"] == 1
    assert doc["approvals"][0]["node_id"] == "node-1"


def test_cli_json_error_missing_config(monkeypatch, capsys):
    from thomas.cli.commands.nodes import p046_nodes_pending_approvals as cli_mod
    from thomas.nodes import p046_nodes_pending_approvals as core_mod

    monkeypatch.delenv("THOMAS_STATE_DIR", raising=False)
    monkeypatch.setattr(core_mod, "_try_state_dir_from_parity_compat", lambda: None)
    monkeypatch.setattr(core_mod, "_try_load_thomas_config", lambda: None)

    rc = cli_mod.cli_main(["--json"])
    assert rc != 0

    stdout = capsys.readouterr().out
    doc = json.loads(stdout)
    assert doc["ok"] is False
    assert doc["error"]["code"] == core_mod.ERROR_CONFIG_MISSING
