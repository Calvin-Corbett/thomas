"""CLI wrapper: `thomas channels logs` (P082).

This module wires the domain logic into the Thomas CLI.

Because Thomas can evolve between argparse/Typer loaders, we expose multiple
common registration hooks and set several common dispatch attributes.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Mapping

from thomas.channels.p082_channel_logs_command import (
    ChannelLogsError,
    ChannelLogsRequest,
    get_channel_logs,
)

# Optional: some Thomas builds may use Typer for the CLI.
try:  # pragma: no cover
    import typer  # type: ignore
except Exception:  # pragma: no cover
    typer = None  # type: ignore


COMMAND_NAME = "logs"
COMMAND = COMMAND_NAME
HELP = "Show recent channel-related logs (optionally filtered by provider)."


def add_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `logs` subcommand under `channels`."""

    parser = subparsers.add_parser(COMMAND_NAME, help=HELP, description=HELP)
    parser.add_argument(
        "--channel",
        default="all",
        help="Channel provider to filter (e.g. telegram) or 'all' (default: all)",
    )
    parser.add_argument(
        "--lines",
        type=int,
        default=200,
        help="Number of log records to show (default: 200)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output machine-readable JSON",
    )

    # Common dispatch attribute names.
    parser.set_defaults(func=_run_from_args)
    parser.set_defaults(run=_run_from_args)
    parser.set_defaults(handler=_run_from_args)
    parser.set_defaults(command=_run_from_args)
    return parser


# Aliases used by different loaders.
build_parser = add_parser
register_command = add_parser
register_subcommand = add_parser
add_subcommand = add_parser
def register(subparsers: Any) -> Any:
    """Best-effort registration hook."""

    if hasattr(subparsers, "add_parser"):
        return add_parser(subparsers)

    if typer is not None:
        try:
            if isinstance(subparsers, typer.Typer):
                subparsers.command(COMMAND_NAME)(typer_command)
                return subparsers
        except Exception:
            pass

    return None


if typer is not None:  # pragma: no cover

    def typer_command(
        channel: str = typer.Option(
            "all",
            "--channel",
            help="Channel provider to filter (e.g. telegram) or 'all' (default: all)",
        ),
        lines: int = typer.Option(
            200,
            "--lines",
            min=1,
            help="Number of log records to show (default: 200)",
        ),
        json_output: bool = typer.Option(
            False,
            "--json",
            help="Output machine-readable JSON",
        ),
    ) -> None:
        """Typer-compatible command entrypoint."""

        args = argparse.Namespace(channel=channel, lines=lines, json=json_output)
        rc = _run_from_args(args)
        raise SystemExit(rc)

else:

    def typer_command(channel: str = "all", lines: int = 200, json_output: bool = False) -> None:
        args = argparse.Namespace(channel=channel, lines=lines, json=json_output)
        rc = _run_from_args(args)
        raise SystemExit(rc)


def _run_from_args(args: argparse.Namespace) -> int:
    """argparse-compatible handler."""

    json_mode = bool(getattr(args, "json", False))
    try:
        result = get_channel_logs(
            ChannelLogsRequest(
                channel=str(getattr(args, "channel", "all")),
                lines=int(getattr(args, "lines", 200)),
            )
        )

        if json_mode:
            sys.stdout.write(json.dumps(result.to_jsonable(), indent=2, sort_keys=True))
            sys.stdout.write("\n")
        else:
            # For "logs" commands, raw lines are usually the most useful.
            for entry in result.entries:
                sys.stdout.write(entry.raw)
                sys.stdout.write("\n")

        return 0

    except ChannelLogsError as e:
        if json_mode:
            payload: Mapping[str, Any] = {
                "ok": False,
                "error": {
                    "code": getattr(e, "code", "channel_logs_error"),
                    "message": str(e),
                    "details": getattr(e, "details", {}),
                },
            }
            sys.stdout.write(json.dumps(payload, indent=2, sort_keys=True))
            sys.stdout.write("\n")
        else:
            sys.stderr.write(f"ERROR [{getattr(e, 'code', 'channel_logs_error')}]: {e}\n")
        return 1
