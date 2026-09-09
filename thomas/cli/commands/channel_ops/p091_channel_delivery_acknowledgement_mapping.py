from __future__ import annotations

import json
import sys
from typing import Any

from thomas.channels.p091_channel_delivery_acknowledgement_mapping import (
    ChannelDeliveryAckMappingError,
    ChannelDeliveryAckMappingRequest,
    build_channel_delivery_ack_mapping,
    response_json_schema,
)

# Thomas-native command names.
# Include aliases because different callers prefer different spellings.
COMMAND_ALIASES: list[str] = [
    "delivery-acknowledgement-mapping",
    "delivery-acknowledgment-mapping",
    "delivery-ack-mapping",
    "delivery-ack-map",
]


def _emit(obj: dict[str, Any], *, as_json: bool) -> None:
    # For now, keep both human and machine output as JSON for determinism.
    # The `--json` flag exists for parity + explicitness.
    if as_json:
        sys.stdout.write(json.dumps(obj, indent=2, sort_keys=True))
        sys.stdout.write("\n")
    else:
        sys.stdout.write(json.dumps(obj, indent=2, sort_keys=True))
        sys.stdout.write("\n")


def run_delivery_ack_mapping(
    *,
    channels: list[str] | None = None,
    config_path: str | None = None,
    json_output: bool = False,
    json_schema: bool = False,
) -> int:
    """Core runner for CLI integration.

    Exit codes:
      0: success
      2: deterministic failure
    """

    if json_schema:
        _emit(response_json_schema(), as_json=True)
        return 0

    try:
        resp = build_channel_delivery_ack_mapping(
            ChannelDeliveryAckMappingRequest(
                channels=channels,
                config_path=config_path,
                strict=True,
            )
        )
    except ChannelDeliveryAckMappingError as e:
        _emit(e.to_dict(), as_json=True)
        return 2

    _emit(resp.to_dict(), as_json=json_output)
    return 0


def register(target: Any, *args: Any, **kwargs: Any) -> None:
    """Register the command on a Typer/Click/argparse command container."""

    # Typer
    try:
        import typer  # type: ignore

        if isinstance(target, typer.Typer):

            def _typer_cmd(
                channels: list[str] | None = typer.Option(
                    None,
                    "--channel",
                    "-c",
                    help="Channel(s) to include. Repeatable.",
                ),
                config: str | None = typer.Option(
                    None,
                    "--config",
                    help="Path to a Thomas config JSON file.",
                ),
                json_out: bool = typer.Option(
                    False,
                    "--json",
                    help="Emit machine-readable JSON.",
                ),
                schema: bool = typer.Option(
                    False,
                    "--json-schema",
                    help="Emit JSON schema for the response.",
                ),
            ) -> None:
                code = run_delivery_ack_mapping(
                    channels=channels,
                    config_path=config,
                    json_output=json_out,
                    json_schema=schema,
                )
                raise typer.Exit(code=code)

            for name in COMMAND_ALIASES:
                target.command(name=name)(_typer_cmd)
            return
    except Exception:  # REVIEWED: broad catch
        # Fall through.
        pass

    # Click
    try:
        import click  # type: ignore

        if isinstance(target, click.core.Group):
            cmd = _build_click_command()
            for name in COMMAND_ALIASES:
                target.add_command(cmd, name=name)
            return
    except ImportError:
        pass

    # argparse
    if hasattr(target, "add_parser"):
        _register_argparse(target)
        return


# Extra export names increase compatibility with different loader conventions.
register_channels_commands = register
register_channel_ops = register
register_commands = register


def _build_click_command():
    import click  # type: ignore

    @click.command(help="Describe Thomas delivery acknowledgement behavior by channel")
    @click.option(
        "--channel",
        "channels",
        multiple=True,
        help="Channel(s) to include. Repeatable.",
    )
    @click.option(
        "--config",
        "config_path",
        default=None,
        help="Path to a Thomas config JSON file.",
    )
    @click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
    @click.option(
        "--json-schema",
        "json_schema",
        is_flag=True,
        help="Emit JSON schema for the response.",
    )
    def _cmd(
        channels: list[str],
        config_path: str | None,
        json_output: bool,
        json_schema: bool,
    ) -> None:
        code = run_delivery_ack_mapping(
            channels=list(channels) if channels else None,
            config_path=config_path,
            json_output=json_output,
            json_schema=json_schema,
        )
        raise SystemExit(code)

    return _cmd


def _register_argparse(subparsers: Any) -> None:
    import argparse

    parser = subparsers.add_parser(
        COMMAND_ALIASES[0],
        help="Describe Thomas delivery acknowledgement behavior by channel",
    )
    parser.add_argument(
        "-c",
        "--channel",
        dest="channels",
        action="append",
        default=None,
        help="Channel(s) to include. Repeatable.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Path to a Thomas config JSON file.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help="Emit machine-readable JSON.",
    )
    parser.add_argument(
        "--json-schema",
        dest="json_schema",
        action="store_true",
        help="Emit JSON schema for the response.",
    )

    def _handler(ns: argparse.Namespace) -> int:
        return run_delivery_ack_mapping(
            channels=ns.channels,
            config_path=ns.config_path,
            json_output=ns.json_output,
            json_schema=ns.json_schema,
        )

    parser.set_defaults(_thomas_handler=_handler)
