import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from thomas.cli.commands.nodes.p030_node_cli_group_scaffold import nodes_group


def _write(path: Path, text: str) -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_nodes_list_success_json_from_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Ensure env doesn't accidentally provide a server/config.
    for k in ("THOMAS_SERVER_URL", "THOMAS_API_URL", "THOMAS_NODES_CONFIG", "THOMAS_CONFIG"):
        monkeypatch.delenv(k, raising=False)

    cfg = _write(
        tmp_path / "nodes.yaml",
        """
nodes:
  - id: beta
    label: Beta
  - id: alpha
    label: Alpha
    address: http://alpha.local
""".lstrip(),
    )

    runner = CliRunner()
    res = runner.invoke(nodes_group, ["list", "--config", cfg, "--json"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output.strip())
    assert payload["ok"] is True
    assert payload["result"]["source"] == "config"
    ids = [n["id"] for n in payload["result"]["nodes"]]
    # Deterministic sort
    assert ids == ["alpha", "beta"]


def test_nodes_list_invalid_nodes_shape_is_deterministic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("THOMAS_SERVER_URL", "THOMAS_API_URL", "THOMAS_NODES_CONFIG", "THOMAS_CONFIG"):
        monkeypatch.delenv(k, raising=False)

    cfg = _write(
        tmp_path / "nodes.json",
        json.dumps({"nodes": {"id": "alpha"}}, indent=2),
    )

    runner = CliRunner()
    res = runner.invoke(nodes_group, ["list", "--config", cfg, "--json"])
    assert res.exit_code == 3, res.output
    payload = json.loads(res.output.strip())
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "config"
    assert payload["error"]["code"] == "invalid_nodes"


def test_nodes_list_missing_source_is_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("THOMAS_SERVER_URL", "THOMAS_API_URL", "THOMAS_NODES_CONFIG", "THOMAS_CONFIG"):
        monkeypatch.delenv(k, raising=False)

    runner = CliRunner()
    res = runner.invoke(nodes_group, ["list", "--json"])
    assert res.exit_code == 3, res.output
    payload = json.loads(res.output.strip())
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "config"
    assert payload["error"]["code"] == "missing_node_source"


def test_nodes_list_config_not_found_is_config_error(monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("THOMAS_SERVER_URL", "THOMAS_API_URL", "THOMAS_NODES_CONFIG", "THOMAS_CONFIG"):
        monkeypatch.delenv(k, raising=False)

    runner = CliRunner()
    res = runner.invoke(nodes_group, ["list", "--config", "does_not_exist.yaml", "--json"])
    assert res.exit_code == 3, res.output
    payload = json.loads(res.output.strip())
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "config"
    assert payload["error"]["code"] == "config_not_found"


def test_nodes_show_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("THOMAS_SERVER_URL", "THOMAS_API_URL", "THOMAS_NODES_CONFIG", "THOMAS_CONFIG"):
        monkeypatch.delenv(k, raising=False)

    cfg = _write(
        tmp_path / "nodes.toml",
        """
nodes = [
  { id = "alpha", label = "Alpha", address = "http://alpha.local" },
  { id = "beta", label = "Beta" },
]
""".lstrip(),
    )

    runner = CliRunner()
    res = runner.invoke(nodes_group, ["show", "alpha", "--config", cfg, "--json"])
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output.strip())
    assert payload["ok"] is True
    assert payload["result"]["node"]["id"] == "alpha"
    assert payload["result"]["node"]["address"] == "http://alpha.local"


def test_nodes_show_unknown_node_is_input_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for k in ("THOMAS_SERVER_URL", "THOMAS_API_URL", "THOMAS_NODES_CONFIG", "THOMAS_CONFIG"):
        monkeypatch.delenv(k, raising=False)

    cfg = _write(
        tmp_path / "nodes.yaml",
        "nodes:\n  - id: alpha\n",
    )

    runner = CliRunner()
    res = runner.invoke(nodes_group, ["show", "ghost", "--config", cfg, "--json"])
    assert res.exit_code == 2, res.output
    payload = json.loads(res.output.strip())
    assert payload["ok"] is False
    assert payload["error"]["kind"] == "input"
    assert payload["error"]["code"] == "node_not_found"
