"""CLI command: validate plugin configuration against its JSON schema.

This module is designed to work with multiple Thomas CLI wiring styles:

- Export a Typer app (`app`) that can be mounted as a sub-command.
- Export a `register(plugins_app)` helper for command registries.
- Best-effort auto-registration if `thomas.cli.commands.plugins` exposes a shared app.

Core validation logic lives in :mod:`thomas.plugins.p117_plugin_config_schema_validator`.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import typer

from thomas.plugins.p117_plugin_config_schema_validator import (
    PluginConfigSchemaValidatorError,
    PluginConfigValidationRequest,
    format_result_human,
    get_output_envelope_schema,
    json_envelope_error,
    json_envelope_ok,
    validate_plugin_config,
)


def _load_inline_json(value: str, *, kind: str) -> Any:
    try:
        return json.loads(value)
    except Exception as e:
        code = "SCHEMA_PARSE_ERROR" if kind == "schema" else "CONFIG_PARSE_ERROR"
        message = "Failed to parse inline schema JSON." if kind == "schema" else "Failed to parse inline config JSON."
        raise PluginConfigSchemaValidatorError(code=code, message=message, details={"error": str(e)}) from e


def _ensure_mapping(obj: Any, *, kind: str) -> Mapping[str, Any]:
    if not isinstance(obj, Mapping):
        raise PluginConfigSchemaValidatorError(
            code="SCHEMA_INVALID" if kind == "schema" else "CONFIG_INVALID",
            message=(
                "Inline schema must be a JSON object." if kind == "schema" else "Inline config must be a JSON object."
            ),
            details={"type": type(obj).__name__},
        )
    return obj


def _cmd_validate_config(
    plugin: str | None = typer.Option(
        None,
        "--plugin",
        "-p",
        help="Plugin identifier used for schema discovery (module path or plugin name).",
    ),
    config_path: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        exists=False,
        dir_okay=False,
        readable=True,
        help="Path to the plugin configuration file (json/yaml/toml).",
    ),
    config_json: str | None = typer.Option(
        None,
        "--config-json",
        help="Inline config as a JSON string (useful for CI).",
    ),
    schema_path: Path | None = typer.Option(
        None,
        "--schema",
        exists=False,
        dir_okay=False,
        readable=True,
        help="Path to the JSON schema file (json/yaml/toml).",
    ),
    schema_json: str | None = typer.Option(
        None,
        "--schema-json",
        help="Inline schema as a JSON string (useful for CI).",
    ),
    json_out: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output.",
    ),
    output_schema: bool = typer.Option(
        False,
        "--output-schema",
        help="Print the JSON schema for the --json output envelope and exit.",
    ),
) -> None:
    """Validate a plugin config against a JSON schema.

    Exit codes:
      * 0: config is valid
      * 2: config does not match schema
      * 1: fatal error (missing inputs, missing schema, parse errors, etc.)
    """
    if output_schema:
        typer.echo(json.dumps(get_output_envelope_schema(), sort_keys=True))
        raise typer.Exit(code=0)

    try:
        if config_path is not None and config_json is not None:
            raise PluginConfigSchemaValidatorError(
                code="INVALID_REQUEST",
                message="Provide either --config or --config-json, not both.",
                details={},
            )
        if schema_path is not None and schema_json is not None:
            raise PluginConfigSchemaValidatorError(
                code="INVALID_REQUEST",
                message="Provide either --schema or --schema-json, not both.",
                details={},
            )

        schema: Mapping[str, Any] | None = None
        if schema_json is not None:
            schema_raw = _load_inline_json(schema_json, kind="schema")
            schema = _ensure_mapping(schema_raw, kind="schema")

        config: Any | None = None
        if config_json is not None:
            config = _load_inline_json(config_json, kind="config")

        request = PluginConfigValidationRequest(
            plugin=plugin,
            config=config,
            config_path=config_path,
            schema=schema,
            schema_path=schema_path,
        )
        result = validate_plugin_config(request)

        if json_out:
            typer.echo(json.dumps(json_envelope_ok(result), sort_keys=True))
        else:
            typer.echo(format_result_human(result))

        raise typer.Exit(code=0 if result.valid else 2)
    except PluginConfigSchemaValidatorError as e:
        if json_out:
            typer.echo(json.dumps(json_envelope_error(e), sort_keys=True))
        else:
            typer.echo(f"Error ({e.code}): {e.message}")
        raise typer.Exit(code=1) from e


# --- Registration surface ---------------------------------------------------

app = typer.Typer(add_completion=False, help="Validate plugin configuration against JSON schema.")


@app.callback()
def _callback() -> None:
    """Plugin validation commands."""
    return


app.command("validate-config")(_cmd_validate_config)


def register(plugins_app: typer.Typer) -> None:
    """Register this command onto an existing Typer app."""
    plugins_app.command("validate-config")(_cmd_validate_config)


# Best-effort auto-registration if a shared plugins app exists.
try:  # pragma: no cover
    from thomas.cli.commands.plugins import app as _shared_plugins_app  # type: ignore

    if _shared_plugins_app is not app:
        _shared_plugins_app.command("validate-config")(_cmd_validate_config)
except ImportError:
    pass
