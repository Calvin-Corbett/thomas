from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from typing import Any, Protocol

import typer

from thomas.channels.p080_channel_login_command import (
    ChannelLoginRequest,
    channel_login,
    channel_login_result_to_dict,
)

COMMAND_NAME = "login"


def _register_argparse(subparsers: Any) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        COMMAND_NAME,
        help="Authenticate/link a messaging channel account",
    )
    parser.add_argument(
        "--channel",
        required=True,
        help="Channel name (e.g., whatsapp, telegram)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON",
    )
    parser.set_defaults(func=run)
    return parser


def _register_typer(app: typer.Typer) -> typer.Typer:
    @app.command(name=COMMAND_NAME, help="Authenticate/link a messaging channel account")
    def _cmd(
        channel: str = typer.Option(..., "--channel", help="Channel name (e.g., whatsapp, telegram)"),
        json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
    ) -> None:
        code = run(argparse.Namespace(channel=channel, json=json_output))
        raise typer.Exit(code=code)

    return app


def register(subparsers: Any) -> Any:
    """Register the `channels login` subcommand for argparse or Typer registries."""
    add_parser = getattr(subparsers, "add_parser", None)
    if callable(add_parser):
        return _register_argparse(subparsers)
    if isinstance(subparsers, typer.Typer):
        return _register_typer(subparsers)
    return None


# Common alias names used by other command registries.
add_parser = register
register_parser = register
add_subcommand = register


def run(args: argparse.Namespace) -> int:
    """Execute the login command. Returns a POSIX-style exit code."""
    request = ChannelLoginRequest(channel=str(args.channel))
    result = channel_login(request)

    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(channel_login_result_to_dict(result), sort_keys=True))
        sys.stdout.write("\n")
    else:
        stream = sys.stdout if result.ok else sys.stderr
        stream.write(result.message)
        stream.write("\n")

    return 0 if result.ok else 1


class CliCommand(Protocol):
    name: str

    def register(self, subparsers: Any) -> argparse.ArgumentParser: ...

    def run(self, args: argparse.Namespace) -> int: ...


@dataclass(frozen=True)
class ChannelLoginCliCommand:
    """Object-style command wrapper for registries that expect instances."""

    name: str = COMMAND_NAME

    def register(self, subparsers: Any) -> argparse.ArgumentParser:
        return register(subparsers)

    def run(self, args: argparse.Namespace) -> int:
        return run(args)


COMMAND: CliCommand = ChannelLoginCliCommand()


def get_cli_command() -> CliCommand:
    return COMMAND

