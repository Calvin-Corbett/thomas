import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thomas.nodes.p050_nodes_token_rotate_and_revoke import (
    NodesTokenError,
    rotate_node_token,
    revoke_node_token,
)

import thomas.cli.commands.nodes.p050_nodes_token_rotate_and_revoke as cli_mod


def test_rotate_creates_store_and_token(tmp_path: Path) -> None:
    store = tmp_path / "tokens.json"
    res = rotate_node_token("nodeA", store_path=store)
    assert res.ok is True
    assert res.action == "rotate"
    assert res.node_id == "nodeA"
    assert res.status == "rotated"
    assert res.token and isinstance(res.token, str)
    assert store.exists()

    data = json.loads(store.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert "nodeA" in data["nodes"]
    assert len(data["nodes"]["nodeA"]["tokens"]) == 1
    assert data["nodes"]["nodeA"]["tokens"][0]["revoked_at"] is None


def test_rotate_revokes_previous_token(tmp_path: Path) -> None:
    store = tmp_path / "tokens.json"
    first = rotate_node_token("nodeA", store_path=store)
    second = rotate_node_token("nodeA", store_path=store)
    assert first.token != second.token

    data = json.loads(store.read_text(encoding="utf-8"))
    tokens = data["nodes"]["nodeA"]["tokens"]
    assert len(tokens) == 2
    assert tokens[0]["revoked_at"] is not None
    assert tokens[1]["revoked_at"] is None


def test_revoke_is_idempotent(tmp_path: Path) -> None:
    store = tmp_path / "tokens.json"
    rotate_node_token("nodeA", store_path=store)

    res1 = revoke_node_token("nodeA", store_path=store)
    assert res1.ok is True
    assert res1.status == "revoked"

    res2 = revoke_node_token("nodeA", store_path=store)
    assert res2.ok is True
    assert res2.status == "no_active_token"


def test_revoke_missing_store_is_no_active_token(tmp_path: Path) -> None:
    store = tmp_path / "missing.json"
    res = revoke_node_token("nodeA", store_path=store)
    assert res.ok is True
    assert res.status == "no_active_token"


def test_invalid_node_id_is_deterministic_error(tmp_path: Path) -> None:
    store = tmp_path / "tokens.json"
    with pytest.raises(NodesTokenError) as ei:
        rotate_node_token("bad id", store_path=store)
    assert ei.value.code == "invalid_node_id"


def test_invalid_store_json_is_invalid_config(tmp_path: Path) -> None:
    store = tmp_path / "tokens.json"
    store.write_text("{not json", encoding="utf-8")
    with pytest.raises(NodesTokenError) as ei:
        rotate_node_token("nodeA", store_path=store)
    assert ei.value.code == "invalid_config"


def test_cli_json_success(tmp_path: Path) -> None:
    store = tmp_path / "tokens.json"
    runner = CliRunner()

    result = runner.invoke(cli_mod.app, ["rotate", "nodeA", "--state", str(store), "--json"])
    assert result.exit_code == 0

    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["action"] == "rotate"
    assert payload["node_id"] == "nodeA"
    assert payload["status"] == "rotated"
    assert "token" in payload


def test_cli_json_error(tmp_path: Path) -> None:
    store = tmp_path / "tokens.json"
    runner = CliRunner()

    result = runner.invoke(cli_mod.app, ["rotate", "bad id", "--state", str(store), "--json"])
    assert result.exit_code != 0

    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "invalid_node_id"
