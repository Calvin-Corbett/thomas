import json

import pytest
import typer
from typer.testing import CliRunner

from thomas.cli.commands.plugins import p098_plugin_manifest_schema as cli
from thomas.plugins.p098_plugin_manifest_schema import (
    PluginManifestSchemaError,
    PluginManifestSchemaRequest,
    build_plugin_manifest_schema,
)


def test_build_plugin_manifest_schema_success_minimal_contract() -> None:
    result = build_plugin_manifest_schema(PluginManifestSchemaRequest())
    schema = result.schema

    assert schema["title"] == "Thomas Plugin Manifest"
    assert schema["type"] == "object"
    assert schema["additionalProperties"] is False

    assert set(schema["required"]) == {"schema_version", "plugin", "tools"}

    props = schema["properties"]
    assert "plugin" in props
    assert "tools" in props

    plugin_ref = props["plugin"]
    assert "$ref" in plugin_ref


def test_build_plugin_manifest_schema_include_examples() -> None:
    result = build_plugin_manifest_schema(
        PluginManifestSchemaRequest(include_examples=True)
    )
    schema = result.schema

    assert "examples" in schema
    assert isinstance(schema["examples"], list)
    assert schema["examples"], "expected at least one example"


def test_build_plugin_manifest_schema_invalid_draft_is_deterministic() -> None:
    with pytest.raises(PluginManifestSchemaError) as exc:
        build_plugin_manifest_schema(
            PluginManifestSchemaRequest(draft="definitely-not-a-draft")  # type: ignore[arg-type]
        )

    assert exc.value.code == "invalid_draft"
    assert "Supported values" in exc.value.message


def test_build_plugin_manifest_schema_unsupported_version_is_deterministic() -> None:
    with pytest.raises(PluginManifestSchemaError) as exc:
        build_plugin_manifest_schema(
            PluginManifestSchemaRequest(schema_version="v999")
        )

    assert exc.value.code == "unsupported_schema_version"
    assert "Supported values" in exc.value.message


def _build_group_app() -> typer.Typer:
    """Create a Typer app that behaves like a command group.

    Typer collapses single-command apps into a direct command, which changes how
    Click parses arguments during tests. Adding a dummy command ensures the
    command under test is exercised as a proper subcommand.
    """

    app = typer.Typer()

    @app.command("__dummy")
    def _dummy() -> None:  # pragma: no cover
        raise RuntimeError("dummy command should never be called")

    cli.register(app)
    return app


def test_cli_plugin_manifest_schema_json_output_is_machine_readable() -> None:
    runner = CliRunner()
    app = _build_group_app()

    result = runner.invoke(app, [cli.COMMAND_NAME, "--json"])
    assert result.exit_code == 0, result.stdout

    parsed = json.loads(result.stdout)
    assert parsed["title"] == "Thomas Plugin Manifest"
    assert parsed["type"] == "object"


def test_cli_plugin_manifest_schema_invalid_draft_exits_nonzero_and_emits_json_error() -> None:
    runner = CliRunner()
    app = _build_group_app()

    result = runner.invoke(app, [cli.COMMAND_NAME, "--draft", "nope", "--json"])
    assert result.exit_code == 2

    payload = json.loads(result.stdout)
    assert payload["error"]["code"] == "invalid_draft"
