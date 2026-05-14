"""CLI command: plugin registry core model.

This command is meant for automation and debugging.

- Default: human-readable summary.
- `--json`: machine-readable JSON (stable key ordering).
"""

from __future__ import annotations

import json
import sys
from typing import List, Optional

import typer

_REGISTERED = False


def registry_model(
    plugin: list[str] | None = typer.Option(
        None,
        "--plugin",
        "-p",
        help="Restrict output to specific plugin module(s). Can be repeated.",
    ),
    include_tools: bool = typer.Option(
        True,
        "--tools/--no-tools",
        help="Include tool metadata in the model.",
    ),
    include_failed: bool = typer.Option(
        True,
        "--include-failed/--exclude-failed",
        help="Include plugins that failed to import or introspect.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON (stable key ordering).",
    ),
) -> None:
    """Show the plugin registry core model."""

    from thomas.plugins.p105_plugin_registry_core_model import (
        BuildPluginRegistryRequest,
        PluginRegistryError,
        build_plugin_registry_core_model,
    )

    try:
        model = build_plugin_registry_core_model(
            BuildPluginRegistryRequest(
                plugin_modules=plugin or None,
                include_tools=include_tools,
                include_failed=include_failed,
            )
        )
    except PluginRegistryError as exc:
        if json_output:
            typer.echo(json.dumps({"ok": False, "error": exc.to_dict()}, sort_keys=True, separators=(",", ":")))
        else:
            typer.echo(f"Error: {exc.message}", err=True)
        raise typer.Exit(code=1)

    payload = {"ok": True, "result": model.to_dict()}

    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return

    # Human output
    plugins = model.plugins
    typer.echo(f"{len(plugins)} plugin(s)")

    for plugin_desc in plugins:
        suffix_parts: list[str] = []
        if plugin_desc.version:
            suffix_parts.append(f"v{plugin_desc.version}")
        if plugin_desc.load_error is not None:
            suffix_parts.append(f"ERROR:{plugin_desc.load_error.code}")
        suffix = f" ({', '.join(suffix_parts)})" if suffix_parts else ""

        typer.echo(f"- {plugin_desc.name}{suffix}")
        if plugin_desc.description:
            first_line = plugin_desc.description.strip().splitlines()[0]
            typer.echo(f"    {first_line}")
        if include_tools and plugin_desc.tools:
            for tool in plugin_desc.tools:
                typer.echo(f"    • {tool.name}")


def register(target_app: typer.Typer) -> None:
    """Register this command onto a Typer app (idempotent)."""

    global _REGISTERED
    if _REGISTERED:
        return

    target_app.command("registry-model", help="Show the plugin registry core model")(registry_model)
    _REGISTERED = True


def _resolve_plugins_group_app() -> typer.Typer | None:
    """Best-effort lookup of the canonical `thomas plugins` command group."""
    pkg = sys.modules.get("thomas.cli.commands.plugins")
    if pkg is None:
        return None
    candidate = getattr(pkg, "app", None)
    if isinstance(candidate, typer.Typer):
        return candidate
    return None


# If we're imported as part of the `thomas.cli.commands.plugins` package, that
# package is usually already in sys.modules. If it exposes an `app`, register
# onto it. Otherwise, create a standalone group app for direct invocation/tests.
_plugins_app = _resolve_plugins_group_app()
if _plugins_app is None:
    app = typer.Typer(help="Plugin-related commands")

    @app.callback()
    def _plugins_group() -> None:  # pragma: no cover
        """Plugin-related commands."""

    register(app)
else:
    register(_plugins_app)
    app = _plugins_app


__all__ = ["app", "register", "registry_model"]
