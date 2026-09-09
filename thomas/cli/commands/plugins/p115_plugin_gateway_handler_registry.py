from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import typer

from thomas.plugins.p115_plugin_gateway_handler_registry import (
    GatewayHandlerRegistryError,
    build_gateway_handler_registry_from_config,
    get_gateway_handler_registry,
)

COMMAND_NAME = "p115-plugin-gateway-handler-registry"

app = typer.Typer(
    name=COMMAND_NAME,
    help="Inspect the gateway handler registry (core + plugin-contributed handlers).",
    add_completion=False,
)


def _print_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, sort_keys=True, ensure_ascii=True))


def _load_registry(config_path: Path | None) -> Any:
    if config_path is None:
        return get_gateway_handler_registry()

    if not config_path.exists():
        raise GatewayHandlerRegistryError(
            "config_not_found",
            "config file not found",
            details={"path": str(config_path)},
        )

    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GatewayHandlerRegistryError(
            "invalid_config",
            "failed to parse config as JSON",
            details={"path": str(config_path), "exception_type": type(exc).__name__, "exception": str(exc)},
        ) from exc

    if not isinstance(raw, dict):
        raise GatewayHandlerRegistryError(
            "invalid_config",
            "config root must be a JSON object",
            details={"path": str(config_path), "type": type(raw).__name__},
        )

    return build_gateway_handler_registry_from_config(raw)


@app.command("list")
def list_handlers(
    config: Path | None = typer.Option(
        None,
        "--config",
        "-c",
        exists=False,
        dir_okay=False,
        readable=True,
        help="Optional JSON config file used to load plugin modules and their gateway handlers.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON.",
    ),
) -> None:
    """List registered gateway handlers."""
    try:
        registry = _load_registry(config)
        snapshot = registry.snapshot(include_core=True)

        if json_output:
            _print_json({"ok": True, "result": snapshot.to_dict()})
            return

        # Human output
        for spec in snapshot.handlers:
            origin = "core" if spec.is_core else (spec.plugin_id or "plugin")
            typer.echo(f"{spec.name}\t[{origin}]")
    except GatewayHandlerRegistryError as exc:
        if json_output:
            _print_json({"ok": False, "error": exc.to_dict()})
            raise typer.Exit(code=2)
        typer.echo(str(exc), err=True)
        raise typer.Exit(code=2)


@app.command("schema")
def schema(
    json_output: bool = typer.Option(
        True,
        "--json/--no-json",
        help="Emit machine-readable JSON schema.",
    ),
) -> None:
    """Emit a JSON Schema for the `list --json` payload."""
    schema_obj = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "GatewayHandlerRegistryListResponse",
        "type": "object",
        "required": ["ok"],
        "properties": {
            "ok": {"type": "boolean"},
            "result": {
                "type": "object",
                "required": ["handlers"],
                "properties": {
                    "handlers": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["name", "is_core"],
                            "properties": {
                                "name": {"type": "string"},
                                "plugin_id": {"type": ["string", "null"]},
                                "description": {"type": ["string", "null"]},
                                "input_schema": {},
                                "output_schema": {},
                                "source": {"type": ["string", "null"]},
                                "is_core": {"type": "boolean"},
                            },
                        },
                    }
                },
            },
            "error": {
                "type": "object",
                "required": ["code", "message"],
                "properties": {
                    "code": {"type": "string"},
                    "message": {"type": "string"},
                    "details": {"type": ["object", "null"]},
                },
            },
        },
    }

    if json_output:
        _print_json(schema_obj)
        return

    typer.echo(schema_obj)


def register(parent: Any, /, *args: Any, **kwargs: Any) -> None:
    """Register with a parent CLI app/group (Typer or Click).

    Some parts of the Thomas CLI auto-discover modules under thomas.cli.commands.* and call
    a module-level register() hook. We accept a duck-typed parent to stay compatible.
    """
    _ = (args, kwargs)

    try:
        # Typer parent
        if hasattr(parent, "add_typer"):
            parent.add_typer(app, name=COMMAND_NAME)
            return
    except AttributeError:
        pass

    try:
        # Click parent
        import click
        from typer.main import get_command

        if isinstance(parent, click.core.Group):
            parent.add_command(get_command(app), name=COMMAND_NAME)
    except ImportError:
        # If we can't register, don't crash import-time.
        return


# Click compatibility for CLIs that load click.Command objects from modules.
try:
    from typer.main import get_command as _typer_get_command

    COMMAND = _typer_get_command(app)
    cli = COMMAND
except ImportError:  # pragma: no cover
    COMMAND = None
    cli = None
