import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from thomas.nodes.p037_nodes_registry_model import (
    ENV_REGISTRY_JSON,
    NodesRegistryConfigError,
    NodesRegistryInputError,
    NodesRegistryExternalError,
    load_nodes_registry,
    filter_nodes,
    run_nodes_registry_model,
)
from thomas.cli.commands.nodes import p037_nodes_registry_model as cli_mod


runner = CliRunner()


def _write_json(tmp_path: Path, obj) -> Path:
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def test_load_nodes_registry_from_json_file_success(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path,
        {
            "nodes": [
                {"id": "alpha", "endpoint": "http://alpha.local:8080", "labels": ["gpu", "us"]},
                {"id": "beta", "endpoint": "beta.local:9090", "tags": "eu,edge"},
            ]
        },
    )

    reg = load_nodes_registry(source=str(path))
    assert reg.source.startswith("file:")
    assert [n.node_id for n in reg.nodes] == ["alpha", "beta"]  # deterministic ordering
    assert reg.nodes[0].endpoint == "http://alpha.local:8080"
    assert reg.nodes[1].endpoint.startswith("http://beta.local:9090")
    assert reg.nodes[1].labels == ["eu", "edge"]


def test_load_nodes_registry_inline_config_success() -> None:
    reg = load_nodes_registry(
        config={
            "nodes": [
                {"id": "n1", "endpoint": "http://n1"},
                {"id": "n2", "endpoint": "http://n2", "labels": "a,b"},
            ]
        }
    )
    assert [n.node_id for n in reg.nodes] == ["n1", "n2"]
    assert reg.source == "config:nodes"


def test_load_nodes_registry_env_inline_json_success() -> None:
    env = {ENV_REGISTRY_JSON: json.dumps([{"id": "n1", "endpoint": "http://n1"}])}
    reg = load_nodes_registry(env=env)
    assert [n.node_id for n in reg.nodes] == ["n1"]
    assert reg.source == f"env:{ENV_REGISTRY_JSON}"


def test_filter_nodes_by_label_and_id(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path,
        [
            {"id": "a", "endpoint": "http://a", "labels": ["x"]},
            {"id": "b", "endpoint": "http://b", "labels": ["y"]},
        ],
    )
    reg = load_nodes_registry(source=str(path))
    reg2 = filter_nodes(reg, label="x")
    assert [n.node_id for n in reg2.nodes] == ["a"]
    reg3 = filter_nodes(reg, node_id="b")
    assert [n.node_id for n in reg3.nodes] == ["b"]


def test_load_nodes_registry_missing_config_error() -> None:
    with pytest.raises(NodesRegistryConfigError) as ei:
        load_nodes_registry(env={})
    assert "No nodes registry source configured" in str(ei.value)


def test_load_nodes_registry_invalid_schema_error(tmp_path: Path) -> None:
    path = _write_json(tmp_path, {"nodes": [{"id": "bad"}]})  # missing endpoint
    with pytest.raises(NodesRegistryInputError):
        load_nodes_registry(source=str(path))


def test_load_nodes_registry_duplicate_id_error(tmp_path: Path) -> None:
    path = _write_json(
        tmp_path,
        {"nodes": [{"id": "dup", "endpoint": "http://a"}, {"id": "dup", "endpoint": "http://b"}]},
    )
    with pytest.raises(NodesRegistryInputError) as ei:
        load_nodes_registry(source=str(path))
    assert "Duplicate node ids" in str(ei.value)


def test_load_nodes_registry_external_parse_error(tmp_path: Path) -> None:
    p = tmp_path / "registry.json"
    p.write_text("{not-json", encoding="utf-8")
    with pytest.raises(NodesRegistryExternalError):
        load_nodes_registry(source=str(p))


def test_load_nodes_registry_rejects_loopback_registry_url() -> None:
    with pytest.raises(NodesRegistryInputError, match="public host"):
        load_nodes_registry(source="http://127.0.0.1:8080/registry.json")


def test_load_nodes_registry_rejects_local_registry_host() -> None:
    with pytest.raises(NodesRegistryInputError, match="public host"):
        load_nodes_registry(source="http://nodes.local/registry.json")


def test_load_nodes_registry_loads_from_public_http_url(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps([{"id": "n1", "endpoint": "http://n1"}]).encode("utf-8")

    class FakeResponse:
        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(self, *_exc: object) -> bool:
            return False

        def read(self) -> bytes:
            return payload

    def fake_urlopen(_url: str, timeout: float) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr(
        "thomas.nodes.p037_nodes_registry_model.urllib.request.urlopen",
        fake_urlopen,
    )

    reg = load_nodes_registry(source="https://example.com/registry.json")
    assert reg.source == "url:https://example.com/registry.json"
    assert [n.node_id for n in reg.nodes] == ["n1"]


def test_run_nodes_registry_model_non_throwing_error_response() -> None:
    out = run_nodes_registry_model({"timeout_s": 0})
    assert out["ok"] is False
    assert out["schema_version"] == 1
    assert out["error"]["code"] == "nodes_registry_input_error"


def test_cli_registry_model_json_success(tmp_path: Path) -> None:
    path = _write_json(tmp_path, {"nodes": [{"id": "n1", "endpoint": "http://n1"}]})

    result = runner.invoke(cli_mod.app, ["registry-model", "--source", str(path), "--json"])
    assert result.exit_code == 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["schema_version"] == 1
    assert payload["count"] == 1
    assert payload["nodes"][0]["id"] == "n1"


def test_cli_registry_model_json_failure_missing_config() -> None:
    result = runner.invoke(cli_mod.app, ["registry-model", "--json"], env={})
    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["schema_version"] == 1
    assert payload["error"]["code"] == "nodes_registry_config_error"
