"""CLI wiring for the channel docs generator.

This module registers a `docs` subcommand under the existing `channels` CLI group.

It supports a machine-readable mode (`--json`) suitable for automation.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Mapping
from typing import Any

from thomas.channels.p094_channel_docs_generator import (
    ChannelDocsGeneratorError,
    ChannelDocsRequest,
    dumps_json,
    generate_channel_docs,
    normalize_channel_names,
    render_markdown,
    to_machine_readable,
    validate_output_path,
    write_text_file,
)

COMMAND_NAME = "docs"
HELP = "Generate documentation for Thomas messaging channels."


def _run(
    *,
    channel: str | None,
    output_path: str | None,
    json_mode: bool,
    validate_config: bool,
    stream: Any,
) -> int:
    """Execute the docs generator.

    Returns an exit code (0 on success, 1 on deterministic failure).
    """

    try:
        validate_output_path(output_path)

        channel_names = None
        if channel is not None:
            channel_names = normalize_channel_names(channel)

        result = generate_channel_docs(
            ChannelDocsRequest(
                channel_names=channel_names,
                validate_required_config=bool(validate_config),
            )
        )

        if json_mode:
            payload = to_machine_readable(result, include_markdown=True)
            content = dumps_json(payload)
        else:
            content = render_markdown(result)

        if output_path:
            write_text_file(output_path, content)
            if json_mode:
                stream.write(
                    dumps_json(
                        {
                            "ok": True,
                            "output_path": output_path,
                            "generated_at": result.generated_at,
                        }
                    )
                )
            return 0

        stream.write(content)
        return 0

    except ChannelDocsGeneratorError as exc:
        if json_mode:
            stream.write(dumps_json(exc.to_dict()))
        else:
            stream.write(f"ERROR[{exc.code}]: {exc}\n")
        return 1


def _argparse_handler(args: argparse.Namespace) -> int:
    return _run(
        channel=getattr(args, "channel", None),
        output_path=getattr(args, "out", None),
        json_mode=bool(getattr(args, "json", False)),
        validate_config=bool(getattr(args, "validate_config", False)),
        stream=sys.stdout,
    )


def run(args: Any, _config: Any = None) -> int:
    """Compatibility entrypoint.

    Some command loaders dispatch to a `run(namespace, config)` function.
    """

    if isinstance(args, argparse.Namespace):
        return _argparse_handler(args)

    if isinstance(args, Mapping):
        return _run(
            channel=args.get("channel"),
            output_path=args.get("out") or args.get("output_path"),
            json_mode=bool(args.get("json", False)),
            validate_config=bool(args.get("validate_config", False)),
            stream=sys.stdout,
        )

    raise TypeError("Unsupported args type for channel docs generator.")


def register(target: Any) -> None:
    """Register this op with the parent `channels` command."""

    if hasattr(target, "add_parser"):
        _register_argparse(target)
        return

    try:
        import typer  # type: ignore

        if isinstance(target, typer.Typer):
            _register_typer(target)
            return
    except ImportError:
        pass

    try:
        import click  # type: ignore

        if isinstance(target, click.Group):
            _register_click(target)
            return
    except ImportError:
        pass

    if hasattr(target, "command"):
        _register_command_decorator(target)
        return

    raise TypeError("Unsupported channels command registrar. Expected argparse subparsers, Typer, or Click group.")


def _register_argparse(subparsers: Any) -> None:
    parser = subparsers.add_parser(COMMAND_NAME, help=HELP)
    parser.add_argument(
        "--channel",
        default=None,
        help="Comma-separated channel names to include (default: all discovered).",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Write output to a file instead of stdout.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON output.",
    )
    parser.add_argument(
        "--validate-config",
        action="store_true",
        help="Fail if required env configuration is missing.",
    )

    parser.set_defaults(func=_argparse_handler, handler=_argparse_handler)


def _register_typer(app: Any) -> None:
    import typer  # type: ignore

    @app.command(COMMAND_NAME, help=HELP)
    def docs(
        channel: str | None = typer.Option(
            None,
            "--channel",
            help="Comma-separated channel names to include (default: all discovered).",
        ),
        out: str | None = typer.Option(
            None,
            "--out",
            help="Write output to a file instead of stdout.",
        ),
        json: bool = typer.Option(
            False,
            "--json",
            help="Emit machine-readable JSON output.",
        ),
        validate_config: bool = typer.Option(
            False,
            "--validate-config",
            help="Fail if required env configuration is missing.",
        ),
    ) -> None:
        exit_code = _run(
            channel=channel,
            output_path=out,
            json_mode=bool(json),
            validate_config=bool(validate_config),
            stream=sys.stdout,
        )
        if exit_code != 0:
            raise typer.Exit(code=exit_code)


def _register_click(group: Any) -> None:
    import click  # type: ignore

    @group.command(COMMAND_NAME, help=HELP)
    @click.option(
        "--channel",
        default=None,
        help="Comma-separated channel names to include (default: all discovered).",
    )
    @click.option(
        "--out",
        default=None,
        help="Write output to a file instead of stdout.",
    )
    @click.option(
        "--json",
        "json_mode",
        is_flag=True,
        default=False,
        help="Emit machine-readable JSON output.",
    )
    @click.option(
        "--validate-config",
        "validate_config",
        is_flag=True,
        default=False,
        help="Fail if required env configuration is missing.",
    )
    def docs(channel: str | None, out: str | None, json_mode: bool, validate_config: bool) -> None:
        exit_code = _run(
            channel=channel,
            output_path=out,
            json_mode=bool(json_mode),
            validate_config=bool(validate_config),
            stream=sys.stdout,
        )
        if exit_code != 0:
            raise SystemExit(exit_code)


def _register_command_decorator(group: Any) -> None:
    """Last-resort registration when only `.command` is available."""

    decorator = group.command(COMMAND_NAME) if callable(getattr(group, "command", None)) else None
    if decorator is None:
        return

    @decorator
    def docs(channel: str | None = None, out: str | None = None, json: bool = False) -> None:
        exit_code = _run(
            channel=channel,
            output_path=out,
            json_mode=bool(json),
            validate_config=False,
            stream=sys.stdout,
        )
        if exit_code != 0:
            raise SystemExit(exit_code)


# Compatibility aliases (some loaders may look for these names)
add_parser = _register_argparse
build_parser = _register_argparse


class _ChannelOp:
    """Command descriptor used by some dynamic loaders."""

    name = COMMAND_NAME
    help = HELP

    def register(self, target: Any) -> None:
        register(target)

    def add_parser(self, subparsers: Any) -> None:
        _register_argparse(subparsers)

    def run(self, args: Any, config: Any = None) -> int:
        return run(args, config)


OP = _ChannelOp()
