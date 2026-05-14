"""
P087 - CLI command: channels validate-auth

Wires `thomas.channels.p087_channel_auth_validation_helper.validate_channel_auth` into CLI.

Supports:
- Human output (default)
- JSON output for automation: `--json`
"""

from __future__ import annotations

import json
from typing import Any, Optional

import click

try:
    from thomas.marketplace.channels.p087_channel_auth_validation_helper import (
        ChannelAuthValidationError,
        ChannelAuthValidationRequest,
        ChannelAuthValidationResult,
        validate_channel_auth,
    )
except ImportError:  # pragma: no cover
    from thomas.channels.p087_channel_auth_validation_helper import (
        ChannelAuthValidationError,
        ChannelAuthValidationRequest,
        ChannelAuthValidationResult,
        validate_channel_auth,
    )


COMMAND_NAME = "validate-auth"


def _render_human_success(result: ChannelAuthValidationResult) -> str:
    ident = result.identity
    if ident is None:
        who = "unknown"
    elif ident.username:
        who = f"@{ident.username}"
    elif ident.display_name:
        who = ident.display_name
    else:
        who = ident.id
    return f"{result.channel}: auth valid ({who})"


def _render_human_error(err: ChannelAuthValidationError) -> str:
    ch = f"{err.channel}: " if getattr(err, "channel", None) else ""
    return f"{ch}{err.code}: {err}"


def _json_success(result: ChannelAuthValidationResult) -> str:
    payload: dict[str, Any] = {"ok": True, **result.to_dict()}
    return json.dumps(payload, sort_keys=True)


def _json_error(err: ChannelAuthValidationError) -> str:
    payload: dict[str, Any] = {"ok": False, "error": err.to_dict()}
    return json.dumps(payload, sort_keys=True)


@click.command(name=COMMAND_NAME)
@click.argument("channel", type=str)
@click.option("--token", type=str, default=None, help="Channel auth token (overrides config/env).")
@click.option(
    "--timeout",
    "timeout_s",
    type=float,
    default=10.0,
    show_default=True,
    help="Network timeout (seconds).",
)
@click.option("--json", "json_output", is_flag=True, help="Emit machine-readable JSON.")
def command(channel: str, token: str | None, timeout_s: float, json_output: bool) -> None:
    """Validate that a channel integration is authenticated."""

    try:
        result = validate_channel_auth(
            ChannelAuthValidationRequest(channel=channel, token=token, timeout_s=timeout_s),
        )
    except ChannelAuthValidationError as e:
        if json_output:
            click.echo(_json_error(e))
            raise SystemExit(1)
        raise click.ClickException(_render_human_error(e)) from e
    except Exception as e:
        unknown = ChannelAuthValidationError(
            "unexpected failure during auth validation",
            channel=(channel or "").strip().lower() or None,
            details={"exc_type": type(e).__name__},
        )
        if json_output:
            click.echo(_json_error(unknown))
            raise SystemExit(1)
        raise click.ClickException(_render_human_error(unknown)) from e

    if json_output:
        click.echo(_json_success(result))
    else:
        click.echo(_render_human_success(result))


# Common loader aliases
COMMAND = command
CLI_COMMAND = command


def get_command() -> click.Command:
    return command


def register(app: Any) -> None:
    """Register this command onto a parent CLI app/group."""

    if hasattr(app, "add_command"):
        app.add_command(command)  # type: ignore[attr-defined]
        return

    if hasattr(app, "command") and callable(app.command):
        app.command(COMMAND_NAME)(command)  # type: ignore[misc]
        return

    raise RuntimeError(f"Unsupported CLI app type for registration: {type(app).__name__}")
