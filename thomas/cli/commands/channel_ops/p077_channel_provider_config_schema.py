from __future__ import annotations

"""
CLI wiring for P077: channel provider config schema.

This module is intentionally thin: it adapts the Thomas CLI layer to the domain
API in `thomas.channels.p077_channel_provider_config_schema`.

It exposes a `register(target)` helper that can attach the command to:
- argparse subparsers (has `add_parser`)
- Click/Typer-style apps (has `command` / `add_command`)
"""

from typing import Any


COMMAND_NAME = "provider-config-schema"


def register(target: Any) -> None:
    """
    Register this command on the given CLI target.

    Supported targets:
    - argparse subparsers action: has `.add_parser(...)`
    - Typer/Click app/group: has `.command(...)` and/or `.add_command(...)`
    """
    if hasattr(target, "add_parser"):
        _register_argparse(target)
        return

    if hasattr(target, "add_command"):
        cmd = get_click_command()
        target.add_command(cmd, name=COMMAND_NAME)
        return

    # Typer apps expose `.command(...)` but not `.add_command(...)`.
    if hasattr(target, "command"):
        _register_typer(target)
        return

    raise TypeError(f"Unsupported CLI registration target: {type(target).__name__}")


def get_click_command():
    import click

    @click.command(name=COMMAND_NAME)
    @click.argument("provider", type=str)
    @click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON output.")
    def _cmd(provider: str, json_output: bool) -> None:
        _run(provider=provider, json_output=json_output)

    return _cmd


def _register_argparse(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        COMMAND_NAME,
        help="Show the configuration schema required by a channel provider.",
    )
    parser.add_argument("provider", type=str, help="Provider name (e.g. telegram)")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Emit machine-readable JSON output.")
    parser.set_defaults(func=_argparse_entrypoint)


def _register_typer(app: Any) -> None:
    import typer

    @app.command(
        name=COMMAND_NAME,
        help="Show the configuration schema required by a channel provider.",
    )
    def _cmd(
        provider: str = typer.Argument(..., help="Provider name (e.g. telegram)"),
        json_output: bool = typer.Option(
            False,
            "--json",
            help="Emit machine-readable JSON output.",
        ),
    ) -> None:
        _run(provider=provider, json_output=json_output)


def _argparse_entrypoint(args: Any) -> None:
    _run(provider=args.provider, json_output=bool(getattr(args, "json_output", False)))


def _run(*, provider: str, json_output: bool) -> None:
    import json
    import sys

    from thomas.channels.p077_channel_provider_config_schema import (
        ChannelProviderConfigSchemaError,
        get_channel_provider_config_schema,
    )

    try:
        result = get_channel_provider_config_schema(provider)
    except ChannelProviderConfigSchemaError as e:
        if json_output:
            sys.stdout.write(json.dumps({"ok": False, "error": e.to_dict()}, sort_keys=True))
            sys.stdout.write("\n")
        else:
            sys.stderr.write(f"Error [{e.code}]: {e}\n")
        raise SystemExit(1) from None

    if json_output:
        sys.stdout.write(json.dumps({"ok": True, **result.to_json()}, sort_keys=True))
        sys.stdout.write("\n")
        return

    # Human-friendly output.
    sys.stdout.write(f"Provider: {result.provider}\n")
    sys.stdout.write(f"Source:   {result.source_module}\n")
    sys.stdout.write("Schema:\n")
    sys.stdout.write(json.dumps(result.schema, indent=2, sort_keys=True))
    sys.stdout.write("\n")
