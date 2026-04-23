"""CLI command: load and validate the channel registry.

This module is intended to be discovered by the main ``channels`` command.
It registers a subcommand that can emit either human-readable or machine-readable
output.
"""

from __future__ import annotations

import json
import sys
from typing import Any

from thomas.channels.p076_channel_registry_loader import (
    ChannelRegistryError,
    ChannelRegistryLoadRequest,
    channel_registry_load_result_schema,
    load_channel_registry,
)

COMMAND_NAME = "registry-load"
COMMAND_HELP = "Load and validate the configured channel registry."

EXIT_OK = 0
EXIT_ERROR = 2


def register(app_or_subparsers: Any) -> None:
    """Register the command with either Typer or argparse.

    The Thomas CLI has evolved across versions; some environments use Typer while
    others use argparse. This function supports both without forcing a hard
    dependency on either.
    """
    if _looks_like_typer(app_or_subparsers):
        _register_typer(app_or_subparsers)
        return
    if _looks_like_argparse(app_or_subparsers):
        _register_argparse(app_or_subparsers)
        return
    # Unknown registrar: ignore to keep discovery robust.


def _looks_like_typer(obj: Any) -> bool:
    return hasattr(obj, "command") and callable(obj.command)


def _looks_like_argparse(obj: Any) -> bool:
    return hasattr(obj, "add_parser") and callable(obj.add_parser)


def _register_typer(app: Any) -> None:
    try:
        import typer  # type: ignore
    except ImportError:  # pragma: no cover
        return

    @app.command(COMMAND_NAME, help=COMMAND_HELP)
    def registry_load(
        path: str | None = typer.Option(None, "--path", "-p", help="Path to a channel registry file (YAML/JSON/TOML)."),
        json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
        json_schema: bool = typer.Option(
            False, "--json-schema", help="Print the JSON schema for --json output and exit."
        ),
        strict: bool = typer.Option(
            True, "--strict/--no-strict", help="Enable/disable strict validation for known channel kinds."
        ),
    ) -> None:
        if json_schema:
            typer.echo(json.dumps(channel_registry_load_result_schema(), indent=2, sort_keys=True))
            raise typer.Exit(code=EXIT_OK)

        try:
            result = load_channel_registry(ChannelRegistryLoadRequest(registry_path=path, strict=strict))
        except ChannelRegistryError as e:
            _emit_error(e, json_output=json_output, emitter=typer.echo)
            raise typer.Exit(code=EXIT_ERROR)

        payload = {"ok": True, "registry": result.to_dict()}
        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True))
            return

        typer.echo(f"Loaded {len(result.channels)} channel(s) from {result.source_path}")
        for ch in result.channels:
            status = "enabled" if ch.enabled else "disabled"
            typer.echo(f"- {ch.name} ({ch.kind}, {status})")


def _register_argparse(subparsers: Any) -> None:
    import argparse

    parser: argparse.ArgumentParser = subparsers.add_parser(COMMAND_NAME, help=COMMAND_HELP, description=COMMAND_HELP)
    parser.add_argument(
        "--path",
        "-p",
        dest="path",
        default=None,
        help="Path to a channel registry file (YAML/JSON/TOML).",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON to stdout.",
    )
    parser.add_argument(
        "--json-schema",
        dest="json_schema",
        action="store_true",
        help="Print the JSON schema for --json output and exit.",
    )
    parser.add_argument(
        "--no-strict",
        dest="strict",
        action="store_false",
        default=True,
        help="Disable strict validation for known channel kinds.",
    )
    parser.set_defaults(func=_run_argparse)


def _run_argparse(args: Any) -> int:
    if getattr(args, "json_schema", False):
        print(json.dumps(channel_registry_load_result_schema(), indent=2, sort_keys=True))
        return EXIT_OK

    try:
        result = load_channel_registry(ChannelRegistryLoadRequest(registry_path=args.path, strict=args.strict))
    except ChannelRegistryError as e:
        _emit_error(e, json_output=getattr(args, "json_output", False))
        return EXIT_ERROR

    payload = {"ok": True, "registry": result.to_dict()}
    if getattr(args, "json_output", False):
        print(json.dumps(payload, sort_keys=True))
        return EXIT_OK

    print(f"Loaded {len(result.channels)} channel(s) from {result.source_path}")
    for ch in result.channels:
        status = "enabled" if ch.enabled else "disabled"
        print(f"- {ch.name} ({ch.kind}, {status})")
    return EXIT_OK


def _emit_error(err: ChannelRegistryError, *, json_output: bool, emitter: Any | None = None) -> None:
    """Emit an error in either human or machine-readable form.

    JSON errors go to stdout to keep automation workflows simple. Human-readable
    errors go to stderr.
    """
    if emitter is None:
        emitter = print

    if json_output:
        payload = {"ok": False, "error": err.to_dict()}
        emitter(json.dumps(payload, sort_keys=True))
        return

    if emitter is print:
        print(f"{err.code}: {err}", file=sys.stderr)
        return

    # Typer's echo supports 'err=True'; feature-detect to avoid hard coupling.
    try:
        emitter(f"{err.code}: {err}", err=True)
    except TypeError:  # pragma: no cover
        emitter(f"{err.code}: {err}")


# Backwards-compatible aliases for various CLI loaders/discovery systems
add_parser = register
add_subparser = register
add_command = register
