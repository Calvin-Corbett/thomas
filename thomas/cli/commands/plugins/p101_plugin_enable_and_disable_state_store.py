"""thomas.cli.commands.plugins.p101_plugin_enable_and_disable_state_store

CLI wrapper around the persistent plugin enable/disable state store.

This command is intentionally a thin wrapper around:
    thomas.plugins.p101_plugin_enable_and_disable_state_store

Machine-readable mode:
    --json

NOTE: The surrounding Thomas CLI may import this module and look for an `app`
(or similar) symbol. To increase compatibility with various loaders, this module
exports `app` plus a couple of common aliases.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import typer

from thomas.plugins.p101_plugin_enable_and_disable_state_store import (
    PluginEnablementStore,
    PluginEnablementStoreError,
    resolve_enablement_store_path,
)


app = typer.Typer(
    add_completion=False,
    help="Persist plugin enable/disable state in a local state store.",
)

# Common aliases (helps with different CLI module loaders)
typer_app = app
cli_app = app


def _emit(payload: Dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(payload, sort_keys=True))
        return

    if payload.get("ok") is True:
        result = payload.get("result")
        if isinstance(result, dict) and "plugin" in result and "enabled" in result:
            status = "enabled" if bool(result["enabled"]) else "disabled"
            typer.echo(f"{result['plugin']}: {status}")
        else:
            typer.echo("ok")
        return

    err = payload.get("error") or {}
    code = err.get("code", "ERROR")
    message = err.get("message", "Unknown error")
    typer.echo(f"{code}: {message}", err=True)


def _fail(err: PluginEnablementStoreError, *, as_json: bool) -> None:
    _emit({"ok": False, "error": err.to_dict()}, as_json=as_json)
    raise typer.Exit(code=1)


def _store(store_path: Optional[Path]) -> PluginEnablementStore:
    resolved = resolve_enablement_store_path(store_path)
    return PluginEnablementStore(resolved)


@app.command("enable")
def enable(
    plugin: str = typer.Argument(..., help="Plugin key to enable."),
    store_path: Optional[Path] = typer.Option(
        None,
        "--store-path",
        help="Override the enablement store file path.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON for automation."),
) -> None:
    """Enable a plugin (persisted)."""

    try:
        change = _store(store_path).set_enabled(plugin, True)
    except PluginEnablementStoreError as e:
        _fail(e, as_json=as_json)
    _emit({"ok": True, "result": change.to_dict()}, as_json=as_json)


@app.command("disable")
def disable(
    plugin: str = typer.Argument(..., help="Plugin key to disable."),
    store_path: Optional[Path] = typer.Option(
        None,
        "--store-path",
        help="Override the enablement store file path.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON for automation."),
) -> None:
    """Disable a plugin (persisted)."""

    try:
        change = _store(store_path).set_enabled(plugin, False)
    except PluginEnablementStoreError as e:
        _fail(e, as_json=as_json)
    _emit({"ok": True, "result": change.to_dict()}, as_json=as_json)


@app.command("status")
def status(
    plugin: Optional[str] = typer.Argument(None, help="Plugin key to query."),
    store_path: Optional[Path] = typer.Option(
        None,
        "--store-path",
        help="Override the enablement store file path.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON for automation."),
) -> None:
    """Show enablement status for a plugin (or all stored entries)."""

    try:
        store = _store(store_path)
        if plugin is None:
            _emit(
                {
                    "ok": True,
                    "result": {"store_path": str(store.path), "plugins": store.list_enabled_states()},
                },
                as_json=as_json,
            )
            return

        _emit(
            {
                "ok": True,
                "result": {"store_path": str(store.path), "plugin": plugin, "enabled": store.is_enabled(plugin)},
            },
            as_json=as_json,
        )
    except PluginEnablementStoreError as e:
        _fail(e, as_json=as_json)


@app.command("clear")
def clear(
    plugin: str = typer.Argument(..., help="Plugin key to remove from the store."),
    store_path: Optional[Path] = typer.Option(
        None,
        "--store-path",
        help="Override the enablement store file path.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Emit JSON for automation."),
) -> None:
    """Remove a plugin entry (reverts to default-enabled)."""

    try:
        store = _store(store_path)
        removed = store.clear(plugin)
        _emit(
            {
                "ok": True,
                "result": {"store_path": str(store.path), "plugin": plugin, "removed": removed},
            },
            as_json=as_json,
        )
    except PluginEnablementStoreError as e:
        _fail(e, as_json=as_json)
