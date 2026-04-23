import json
from pathlib import Path

import pytest

from thomas.cli.commands.nodes.p027_node_host_config_model import cli as cli_entry
from thomas.marketplace.nodes.p027_node_host_config_model import (
    NodeHostConfigModelExternalFailure,
    NodeHostConfigModelInvalidInputError,
    NodeHostConfigModelMissingConfigError,
    NodeHostConfigModelRequest,
    node_host_config_model,
)


def test_model_schema_contains_browser_proxy() -> None:
    resp = node_host_config_model()
    schema = resp.schema

    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False
    assert "browserProxy" in schema["properties"]

    bp = schema["properties"]["browserProxy"]
    assert bp["type"] == "object"
    assert bp["additionalProperties"] is False

    assert "enabled" in bp["properties"]
    assert bp["properties"]["enabled"]["type"] == "boolean"
    assert bp["properties"]["enabled"].get("default") is True

    assert "allowProfiles" in bp["properties"]
    assert bp["properties"]["allowProfiles"]["type"] == "array"
    assert bp["properties"]["allowProfiles"]["items"]["type"] == "string"


def test_model_json_is_machine_readable() -> None:
    resp = node_host_config_model()
    blob = json.dumps(resp.to_dict(), sort_keys=True)
    payload = json.loads(blob)
    assert "schema" in payload
    assert payload["schema"]["properties"]["browserProxy"]["properties"]["enabled"]["type"] == "boolean"


def test_include_current_loads_from_full_config(tmp_path: Path) -> None:
    cfg = {
        "nodeHost": {
            "browserProxy": {"enabled": False, "allowProfiles": ["work"]},
        }
    }
    p = tmp_path / "thomas.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")

    resp = node_host_config_model(NodeHostConfigModelRequest(config_path=p, include_current=True))
    assert resp.current == cfg["nodeHost"]


def test_include_current_loads_from_raw_node_host_config(tmp_path: Path) -> None:
    cfg = {"browserProxy": {"enabled": True, "allowProfiles": ["default"]}}
    p = tmp_path / "nodehost.json"
    p.write_text(json.dumps(cfg), encoding="utf-8")

    resp = node_host_config_model(NodeHostConfigModelRequest(config_path=p, include_current=True))
    assert resp.current == cfg


def test_missing_config_path_is_deterministic_error(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json5"
    with pytest.raises(NodeHostConfigModelMissingConfigError) as exc:
        node_host_config_model(NodeHostConfigModelRequest(config_path=missing, include_current=True))
    assert exc.value.code == "NODE_HOST_CONFIG_MODEL_MISSING_CONFIG"
    assert "path" in exc.value.details


def test_invalid_config_is_deterministic_error(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json5"
    bad.write_text("{ this is not json }", encoding="utf-8")
    with pytest.raises(NodeHostConfigModelInvalidInputError) as exc:
        node_host_config_model(NodeHostConfigModelRequest(config_path=bad, include_current=True))
    assert exc.value.code == "NODE_HOST_CONFIG_MODEL_INVALID_INPUT"


def test_invalid_keys_are_deterministic_error(tmp_path: Path) -> None:
    bad = {"nodeHost": {"nope": True}}
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(NodeHostConfigModelInvalidInputError) as exc:
        node_host_config_model(NodeHostConfigModelRequest(config_path=p, include_current=True))
    assert exc.value.code == "NODE_HOST_CONFIG_MODEL_INVALID_INPUT"
    assert exc.value.details.get("unknown") == ["nope"]


def test_external_failure_is_deterministic_error(tmp_path: Path) -> None:
    # Point at a directory; read_text will raise IsADirectoryError (OSError subclass).
    d = tmp_path / "cfgdir"
    d.mkdir()
    with pytest.raises(NodeHostConfigModelExternalFailure) as exc:
        node_host_config_model(NodeHostConfigModelRequest(config_path=d, include_current=True))
    assert exc.value.code == "NODE_HOST_CONFIG_MODEL_EXTERNAL_FAILURE"
    assert exc.value.details.get("path") == str(d)


def test_cli_json_success(capsys: pytest.CaptureFixture[str]) -> None:
    rc = cli_entry(["--json"])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is True
    assert "schema" in payload
    assert payload["schema"]["properties"]["browserProxy"]["type"] == "object"


def test_cli_json_error(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    rc = cli_entry(["--json", "--include-current", "--config", str(tmp_path / "nope.json5")])
    assert rc != 0
    out = capsys.readouterr().out.strip()
    payload = json.loads(out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "NODE_HOST_CONFIG_MODEL_MISSING_CONFIG"
