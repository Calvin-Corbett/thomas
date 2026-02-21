"""Plugin HTTP route registry CLI.

Adds a `plugins http-route-registry` (and/or similar) subcommand that prints the HTTP
routes registered by plugins.

Goals:
- Deterministic output (stable sort order).
- Machine-readable mode via --json.
- JSON Schema emission via --schema.
- Deterministic error envelopes for automation.

Integration note:
This module exposes multiple conventional entrypoints (`app`, `cli`, `COMMAND`, `register`)
because Thomas CLI loaders may differ across environments.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import typer

from thomas.plugins.p116_plugin_http_route_registry import (
    PluginHttpRouteRegistry,
    PluginRouteRegistryError,
    get_default_registry,
    load_routes_from_config,
)


app = typer.Typer(
    add_completion=False,
    help="Inspect HTTP routes registered by Thomas plugins.",
)


def _emit_error(err: PluginRouteRegistryError, *, json_mode: bool) -> None:
    """Emit deterministic error output."""

    if json_mode:
        payload = {"error": {"code": err.code, "message": str(err), "details": err.details}}
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    typer.echo(f"ERROR[{err.code}]: {err}", err=True)


def _build_registry_view(config: Optional[Path]) -> PluginHttpRouteRegistry:
    """Build an isolated registry view for the CLI run.

    We copy the current process-global registry into a fresh registry so CLI operations
    (like --config loading) do not mutate shared global state. This improves test isolation
    and keeps CLI behavior predictable.
    """
    base = get_default_registry()
    view = PluginHttpRouteRegistry()

    for route in base.list():
        view.register(plugin_id=route.plugin_id, path=route.path, source=route.source)

    if config is not None:
        load_routes_from_config(config, registry=view)

    return view


@app.callback(invoke_without_command=True)
def main(
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    schema: bool = typer.Option(
        False,
        "--schema",
        help="Emit JSON Schema for the --json output shape.",
    ),
    plugin_id: Optional[str] = typer.Option(
        None,
        "--plugin-id",
        help="Only show routes belonging to this plugin id.",
    ),
    config: Optional[Path] = typer.Option(
        None,
        "--config",
        dir_okay=False,
        file_okay=True,
        readable=True,
        help=(
            "Optional JSON config file to preload routes. Supported keys: "
            "plugins.http_routes, http_routes, plugin_http_routes."
        ),
    ),
) -> None:
    """List plugin HTTP routes."""

    json_mode = bool(json_output or schema)

    if schema and json_output:
        _emit_error(
            PluginRouteRegistryError(
                code="invalid_input",
                message="--schema and --json are mutually exclusive",
                details={"json": True, "schema": True},
            ),
            json_mode=True,
        )
        raise typer.Exit(code=2)

    try:
        registry = _build_registry_view(config)

        if schema:
            typer.echo(json.dumps(PluginHttpRouteRegistry.json_schema(), indent=2, sort_keys=True))
            return

        routes = registry.list(plugin_id=plugin_id)

        if json_output:
            payload = {"count": len(routes), "routes": [r.to_dict() for r in routes]}
            typer.echo(json.dumps(payload, indent=2, sort_keys=True))
            return

        if not routes:
            typer.echo("No plugin HTTP routes registered.")
            return

        typer.echo("PLUGIN_ID\tPATH\tSOURCE")
        for r in routes:
            typer.echo(f"{r.plugin_id}\t{r.path}\t{r.source or '-'}")

    except PluginRouteRegistryError as e:
        _emit_error(e, json_mode=json_mode)
        raise typer.Exit(code=1)


# Click command for frameworks that expect click.Command (Typer is click-based).
cli = typer.main.get_command(app)

# Common aliases used by various command registries / dynamic loaders.
COMMAND = cli
APP = app

# Stable command name hint for dynamic loaders.
COMMAND_NAME = "http-route-registry"
COMMAND_ALIASES = ["http-routes"]


def get_command():
    """Return the Click command for this module."""
    return cli


def register(parent: Any, *, name: str = COMMAND_NAME) -> None:
    """Register this command with a parent CLI container.

    Supports:
    - Typer: parent.add_typer(app, name=...)
    - Click Group: parent.add_command(cli, name=...)
    """
    # Typer instance (preferred when available)
    try:
        if isinstance(parent, typer.Typer):
            parent.add_typer(app, name=name)
            return
    except Exception:
        # If Typer changes its types, fall through to Click.
        pass

    # Click Group fallback
    try:
        import click  # type: ignore

        if isinstance(parent, click.Group):
            parent.add_command(cli, name=name)
            # Best-effort aliases
            for alias in COMMAND_ALIASES:
                if alias != name:
                    parent.add_command(cli, name=alias)
            return
    except Exception as e:  # pragma: no cover
        raise TypeError("Unsupported parent command container") from e

    raise TypeError("Unsupported parent command container")
