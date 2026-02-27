"""CLI command: Plugin diagnostics collector (P118).

This command collects diagnostics about available plugins and (optionally)
registered tools. It supports a machine-readable JSON output mode.
"""

from __future__ import annotations

import json

import typer

from thomas.plugins.p118_plugin_diagnostics_collector import (
    PluginDiagnosticsCollectorError,
    PluginDiagnosticsInput,
    collect_plugin_diagnostics,
    report_to_dict,
)

COMMAND_NAME = "p118-plugin-diagnostics-collector"


def _run(
    plugin: list[str] | None = typer.Option(
        None,
        "--plugin",
        "-p",
        help="Plugin module base-name(s) to inspect (repeatable).",
    ),
    include_tools: bool = typer.Option(
        True,
        "--include-tools/--no-include-tools",
        help="Include tool registry correlation.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Exit non-zero on first critical error (unknown plugin, missing registry, import failure).",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output.",
    ),
) -> None:
    """Collect and print plugin diagnostics."""
    plugin_names = list(plugin) if plugin else None

    try:
        report = collect_plugin_diagnostics(
            PluginDiagnosticsInput(plugin_names=plugin_names, include_tools=include_tools, strict=strict)
        )
        payload = report_to_dict(report)
    except PluginDiagnosticsCollectorError as e:
        error_payload = {"ok": False, "error": e.to_dict()}
        if json_output:
            typer.echo(json.dumps(error_payload, indent=2, sort_keys=True))
        else:
            typer.echo(f"{e.code}: {e}", err=True)
        raise typer.Exit(code=2)

    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        ok_mark = "OK" if payload.get("ok") else "NOT OK"
        typer.echo(f"{ok_mark}: {len(payload.get('plugins', []))} plugin(s) inspected")
        for p in payload.get("plugins", []):
            status = p.get("status", "unknown")
            tools = p.get("tool_names") or []
            tool_part = f" ({len(tools)} tool(s))" if include_tools else ""
            typer.echo(f"- {p.get('name')}: {status}{tool_part}")
        if payload.get("issues"):
            typer.echo("Issues:", err=True)
            for issue in payload["issues"]:
                typer.echo(f"- {issue.get('code')}: {issue.get('message')}", err=True)

    if not payload.get("ok"):
        raise typer.Exit(code=1)


# Standalone app (useful for unit tests).
app = typer.Typer(add_completion=False, no_args_is_help=True)
app.command(COMMAND_NAME)(_run)


def register(root: typer.Typer) -> None:
    """Register this command onto a Typer app (used by Thomas CLI discovery)."""
    # Typer keeps a list of registered commands.
    existing = getattr(root, "registered_commands", None)
    if isinstance(existing, list):
        for cmd in existing:
            if getattr(cmd, "name", None) == COMMAND_NAME:
                return
    root.command(COMMAND_NAME)(_run)


def _auto_register() -> None:
    """Best-effort attachment to the central `thomas plugins` command group.

    This keeps CLI parity tests happy across different discovery strategies:
    - some CLIs import modules and expect a `register(app)` function
    - others expect the module to self-register at import time
    """
    try:
        from thomas.cli.commands.plugins import app as plugins_app  # type: ignore
    except ImportError:
        return

    if plugins_app is app:
        return
    try:
        register(plugins_app)
    except ImportError:
        # Do not fail import of the module due to CLI wiring differences.
        return


_auto_register()
