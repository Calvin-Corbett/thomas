"""P060 - Message pin command (CLI).

Thomas-native CLI shape:

    thomas messages pin --channel-id ... --message-id ... [--reason ...] [--requested-by ...]

Automation:
    --json emits a single JSON object to stdout.

This module is designed to be discoverable by whichever command registry mechanism the
existing Thomas CLI uses. To maximize compatibility it exports:

- COMMAND            (the click command)
- get_click_command  (returns the click command)
- register           (registers the command on a click group)

"""

from __future__ import annotations

import json
import os
from dataclasses import asdict

import click

from thomas.messages.p060_message_pin_command import (
    MessagePinCommandError,
    MessagePinInput,
    load_message_pin_config,
    pin_message,
)

PROMPT_ID = "P060"
BATCH = "B08"
LANE = "Messaging and Channels"
DOMAIN = "messages"

COMMAND_PATH = ("messages", "pin")
COMMAND_NAME = "pin"
HELP = "Pin a message in a channel."


def _config_from_env_and_overrides(
    *,
    backend: str | None,
    api_url: str | None,
    api_token: str | None,
    timeout_seconds: float | None,
):
    # Load from environment, with click option overrides applied as env values.
    env = dict(os.environ)
    if backend is not None:
        env["THOMAS_MESSAGES_BACKEND"] = backend
    if api_url is not None:
        env["THOMAS_MESSAGES_API_URL"] = api_url
    if api_token is not None:
        env["THOMAS_MESSAGES_API_TOKEN"] = api_token
    if timeout_seconds is not None:
        env["THOMAS_MESSAGES_TIMEOUT_SECONDS"] = str(timeout_seconds)
    return load_message_pin_config(env)


@click.command(name=COMMAND_NAME, help=HELP)
@click.option("--channel-id", required=True, type=str, help="Channel identifier.")
@click.option("--message-id", required=True, type=str, help="Message identifier.")
@click.option("--reason", required=False, type=str, default=None, help="Reason for pinning.")
@click.option(
    "--requested-by",
    required=False,
    type=str,
    default=None,
    help="Human or system requesting the pin.",
)
@click.option(
    "--backend",
    required=False,
    type=str,
    default=None,
    help="Backend: memory or http. Overrides THOMAS_MESSAGES_BACKEND.",
)
@click.option(
    "--api-url",
    required=False,
    type=str,
    default=None,
    help="Base URL for http backend. Overrides THOMAS_MESSAGES_API_URL.",
)
@click.option(
    "--api-token",
    required=False,
    type=str,
    default=None,
    help="Bearer token for http backend. Overrides THOMAS_MESSAGES_API_TOKEN.",
)
@click.option(
    "--timeout-seconds",
    required=False,
    type=float,
    default=None,
    help="HTTP timeout seconds. Overrides THOMAS_MESSAGES_TIMEOUT_SECONDS.",
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    default=False,
    help="Emit machine-readable JSON output.",
)
@click.pass_context
def pin_command(
    ctx: click.Context,
    channel_id: str,
    message_id: str,
    reason: str | None,
    requested_by: str | None,
    backend: str | None,
    api_url: str | None,
    api_token: str | None,
    timeout_seconds: float | None,
    json_output: bool,
) -> None:
    """Pin a message."""

    try:
        cfg = _config_from_env_and_overrides(
            backend=backend,
            api_url=api_url,
            api_token=api_token,
            timeout_seconds=timeout_seconds,
        )
        result = pin_message(
            MessagePinInput(
                channel_id=channel_id,
                message_id=message_id,
                reason=reason,
                requested_by=requested_by,
            ),
            config=cfg,
        )
    except MessagePinCommandError as e:
        if json_output:
            click.echo(json.dumps({"ok": False, "error": e.to_dict()}, sort_keys=True))
        else:
            click.echo(f"ERROR ({e.code}): {e}")
        ctx.exit(1)
    except (OSError, RuntimeError, ValueError, AttributeError, TypeError, ImportError, KeyError) as e:  # pragma: no cover
        # Avoid leaking unpredictable details in automation output.
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "ok": False,
                        "error": {
                            "type": "internal_error",
                            "code": "internal_error",
                            "message": "Unexpected internal error.",
                            "details": {"exception": e.__class__.__name__},
                        },
                    },
                    sort_keys=True,
                )
            )
        else:
            click.echo("ERROR (internal_error): Unexpected internal error.")
        ctx.exit(1)

    if json_output:
        click.echo(json.dumps({"ok": True, "result": asdict(result)}, sort_keys=True))
        return

    if result.already_pinned:
        click.echo(f"Message {result.message_id} was already pinned in channel {result.channel_id}.")
    else:
        click.echo(f"Pinned message {result.message_id} in channel {result.channel_id}.")


# Common discovery hooks (different parts of the Thomas codebase may use different conventions)
COMMAND = pin_command


def get_click_command() -> click.Command:
    """Return the click command for registry/discovery."""

    return pin_command


def register(group: click.Group) -> None:
    """Register this command under a click group."""

    group.add_command(pin_command)
