"""CLI proxy target for channel verification harness."""

from __future__ import annotations

import json
from typing import Any

import click

from thomas.channels.p097_channel_verification_harness import (
    ChannelVerificationRequest,
    format_verification_report_human,
    run_channel_verification,
)


@click.command(name="verify", help="Verify Thomas channel integrations via contract and optional live probes.")
@click.option(
    "--provider",
    "providers",
    multiple=True,
    help="Limit verification to one or more provider ids.",
)
@click.option(
    "--live/--no-live",
    "include_live",
    default=False,
    show_default=True,
    help="Run live provider health checks for configured channels.",
)
@click.option(
    "--configured-only/--all",
    "configured_only",
    default=False,
    show_default=True,
    help="Verify only configured channels.",
)
@click.option(
    "--timeout",
    "timeout_seconds",
    type=float,
    default=5.0,
    show_default=True,
    help="Timeout in seconds for live checks.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable JSON.")
@click.pass_context
def verify_command(
    ctx: click.Context,
    providers: tuple[str, ...],
    include_live: bool,
    configured_only: bool,
    timeout_seconds: float,
    as_json: bool,
) -> None:
    config = _resolve_click_config(ctx)
    report = run_channel_verification(
        ChannelVerificationRequest(
            config=config,
            providers=list(providers) or None,
            include_live=include_live,
            configured_only=configured_only,
            timeout_seconds=timeout_seconds,
        )
    )
    if as_json:
        click.echo(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        click.echo(format_verification_report_human(report), nl=False)
    raise click.exceptions.Exit(0 if report.ok else 1)


COMMAND = verify_command
cli = COMMAND
COMMANDS = [COMMAND]
NAME = "verify"


def get_command():
    return COMMAND


def get_commands():
    return COMMANDS


def _resolve_click_config(ctx: click.Context) -> Any:
    obj = ctx.obj if isinstance(ctx.obj, dict) else {}
    config = obj.get("config")
    if config is None:
        raise click.ClickException("Missing CLI config context.")
    return config
