"""CLI command: plugin-manifest-schema.

This command prints the JSON Schema document describing the Thomas plugin
manifest format.

It supports a machine-readable output mode via ``--json``.
"""

from __future__ import annotations

import json
from typing import Any, Dict

import typer

from thomas.plugins.p098_plugin_manifest_schema import (
    PluginManifestSchemaError,
    PluginManifestSchemaRequest,
    build_plugin_manifest_schema,
)


COMMAND_NAME = "plugin-manifest-schema"


def _render_json(data: Dict[str, Any], *, compact: bool) -> str:
    if compact:
        return json.dumps(data, separators=(",", ":"), sort_keys=True)
    return json.dumps(data, indent=2, sort_keys=True)


def _emit_error(err: PluginManifestSchemaError, *, as_json: bool) -> None:
    if as_json:
        typer.echo(_render_json(err.to_dict(), compact=True))
        return

    typer.echo(f"Error [{err.code}]: {err.message}", err=True)
    if err.details:
        typer.echo(_render_json({"details": err.details}, compact=False), err=True)


def _run(
    *,
    schema_version: str,
    draft: str,
    include_examples: bool,
    json_output: bool,
) -> None:
    try:
        result = build_plugin_manifest_schema(
            PluginManifestSchemaRequest(
                schema_version=schema_version,
                draft=draft,  # type: ignore[arg-type]
                include_examples=include_examples,
            )
        )
    except PluginManifestSchemaError as e:
        _emit_error(e, as_json=json_output)
        raise typer.Exit(code=2)
    except Exception as e:  # pragma: no cover
        # Deterministic wrapper for unexpected failures.
        err = PluginManifestSchemaError(
            code="unexpected_failure",
            message="Unexpected failure while building plugin manifest schema.",
            details={"reason": str(e)},
        )
        _emit_error(err, as_json=json_output)
        raise typer.Exit(code=1)

    typer.echo(_render_json(result.schema, compact=json_output))


def register(app: typer.Typer) -> None:
    """Register the command on an existing Typer app."""

    @app.command(COMMAND_NAME)
    def plugin_manifest_schema(
        schema_version: str = typer.Option(
            "v1",
            "--schema-version",
            help="Plugin manifest schema version to emit.",
        ),
        draft: str = typer.Option(
            "2020-12",
            "--draft",
            help="JSON Schema draft to target (2020-12 or 7).",
        ),
        include_examples: bool = typer.Option(
            False,
            "--include-examples",
            help="Include example manifests in the schema output.",
        ),
        json_output: bool = typer.Option(
            False,
            "--json",
            help="Emit compact machine-readable JSON (also used for errors).",
        ),
    ) -> None:
        _run(
            schema_version=schema_version,
            draft=draft,
            include_examples=include_examples,
            json_output=json_output,
        )


# Local app instance for unit tests and potential auto-discovery.
app = typer.Typer(add_help_option=True)
register(app)


__all__ = ["COMMAND_NAME", "app", "register"]
