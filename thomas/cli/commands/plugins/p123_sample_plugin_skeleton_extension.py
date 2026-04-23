"""CLI entrypoint for P123 - Sample plugin skeleton extension.

This module is designed to integrate with Thomas' Typer-based CLI.

Supported modes:
- Default (human-readable): prints the rendered string
- `--json`: emits machine-readable wrapper JSON
- `--schema`: prints request/response schemas and exits
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer


COMMAND_NAME = "p123-sample-plugin-skeleton-extension"

app = typer.Typer(
    name=COMMAND_NAME,
    add_completion=False,
    help="P123: Sample plugin skeleton extension (example plugin + schema + JSON output).",
    context_settings={"allow_interspersed_args": True},
)


def _import_plugin():
    # Normal import path (expected in Thomas repo)
    from thomas.plugins import p123_sample_plugin_skeleton_extension as plugin

    return plugin


@app.callback(invoke_without_command=True)
def main(
    message: Optional[str] = typer.Argument(None, help="Message to render"),
    times: int = typer.Option(1, "--times", "-n", min=1, max=20, help="Repeat count"),
    uppercase: bool = typer.Option(False, "--uppercase/--no-uppercase", help="Uppercase the message"),
    use_config: bool = typer.Option(
        False,
        "--use-config",
        help="Load a JSON config file to get the prefix (see schema/docs).",
    ),
    config_path: Optional[Path] = typer.Option(
        None,
        "--config-path",
        help="Path to JSON config file (overrides env var THOMAS_P123_SAMPLE_PLUGIN_CONFIG).",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    schema: bool = typer.Option(False, "--schema", help="Print request/response JSON Schema and exit"),
):
    plugin = _import_plugin()

    if schema:
        typer.echo(json.dumps(plugin.manifest(), ensure_ascii=False, sort_keys=True))
        return

    if not message:
        typer.echo("ERROR [invalid_input]: MESSAGE is required unless --schema is used", err=True)
        raise typer.Exit(code=2)

    payload = {
        "message": message,
        "times": times,
        "uppercase": uppercase,
        "use_config": use_config,
    }

    wrapper = plugin.invoke(payload, config_path=str(config_path) if config_path else None)

    if json_output:
        typer.echo(json.dumps(wrapper, ensure_ascii=False, sort_keys=True))
    else:
        if wrapper.get("ok"):
            result = wrapper.get("result") or {}
            typer.echo(result.get("rendered", ""))
        else:
            error = wrapper.get("error") or {}
            typer.echo(f"ERROR [{error.get('code','error')}]: {error.get('message','')}", err=True)

    if not wrapper.get("ok"):
        raise typer.Exit(code=1)


def register(parent_app: typer.Typer) -> None:
    """Register this command with a parent Typer app."""

    parent_app.add_typer(app, name=COMMAND_NAME)


__all__ = ["app", "COMMAND_NAME", "register"]
