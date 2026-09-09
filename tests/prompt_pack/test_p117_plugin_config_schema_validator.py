import json
from pathlib import Path

import pytest

pytest.importorskip("jsonschema")
from typer.testing import CliRunner

from thomas.cli.commands.plugins.p117_plugin_config_schema_validator import app
from thomas.plugins.p117_plugin_config_schema_validator import (
    PluginConfigSchemaValidatorError,
    PluginConfigValidationRequest,
    resolve_schema,
    validate_plugin_config,
)


def test_validate_plugin_config_success_inline_schema_and_config() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"api_key": {"type": "string"}},
        "required": ["api_key"],
        "additionalProperties": False,
    }
    config = {"api_key": "secret"}

    result = validate_plugin_config(PluginConfigValidationRequest(schema=schema, config=config, plugin="dummy"))

    assert result.valid is True
    assert result.issues == []
    assert result.schema_source == "inline"


def test_validate_plugin_config_failure_schema_mismatch() -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
        "properties": {"api_key": {"type": "string"}},
        "required": ["api_key"],
        "additionalProperties": False,
    }
    # Wrong type.
    config = {"api_key": 123}

    result = validate_plugin_config(PluginConfigValidationRequest(schema=schema, config=config, plugin="dummy"))

    assert result.valid is False
    assert len(result.issues) >= 1
    assert any(("type" in issue.message) or ("string" in issue.message) for issue in result.issues)


def test_validate_plugin_config_missing_file_is_deterministic_error(tmp_path: Path) -> None:
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "type": "object",
    }
    missing = tmp_path / "does_not_exist.json"

    with pytest.raises(PluginConfigSchemaValidatorError) as excinfo:
        validate_plugin_config(PluginConfigValidationRequest(schema=schema, config_path=missing, plugin="dummy"))

    err = excinfo.value
    assert err.code == "CONFIG_NOT_FOUND"
    assert err.details.get("path") == str(missing)


def test_resolve_schema_requires_schema_or_plugin() -> None:
    with pytest.raises(PluginConfigSchemaValidatorError) as excinfo:
        resolve_schema(plugin=None, schema=None, schema_path=None)
    assert excinfo.value.code == "SCHEMA_NOT_PROVIDED"


def test_cli_json_output_success(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.json"
    config_path = tmp_path / "config.json"

    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {"enabled": {"type": "boolean"}},
                "required": ["enabled"],
            }
        ),
        encoding="utf-8",
    )
    config_path.write_text(json.dumps({"enabled": True}), encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "validate-config",
            "--config",
            str(config_path),
            "--schema",
            str(schema_path),
            "--json",
        ],
    )

    assert res.exit_code == 0
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["result"]["valid"] is True
    assert payload["result"]["issues"] == []


def test_cli_json_output_schema_mismatch_exit_code_2(tmp_path: Path) -> None:
    schema_path = tmp_path / "schema.json"
    config_path = tmp_path / "config.json"

    schema_path.write_text(
        json.dumps(
            {
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "type": "object",
                "properties": {"enabled": {"type": "boolean"}},
                "required": ["enabled"],
            }
        ),
        encoding="utf-8",
    )
    # enabled must be boolean, but is a string.
    config_path.write_text(json.dumps({"enabled": "yes"}), encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "validate-config",
            "--config",
            str(config_path),
            "--schema",
            str(schema_path),
            "--json",
        ],
    )

    assert res.exit_code == 2
    payload = json.loads(res.stdout)
    assert payload["ok"] is True
    assert payload["result"]["valid"] is False
    assert payload["result"]["issues"]


def test_cli_json_output_missing_schema_is_fatal_exit_code_1(tmp_path: Path) -> None:
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"enabled": True}), encoding="utf-8")

    runner = CliRunner()
    res = runner.invoke(
        app,
        [
            "validate-config",
            "--config",
            str(config_path),
            "--json",
        ],
    )

    assert res.exit_code == 1
    payload = json.loads(res.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "SCHEMA_NOT_PROVIDED"
