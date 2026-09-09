"""CLI: P065 - Message member timeout.

Thomas-native CLI wrapper around `thomas.messages.p065_message_member_timeout`.
Supports machine-readable output via `--json`.
"""

from __future__ import annotations

import json
from typing import Any

import typer
from typer.main import get_command as _get_typer_command

from thomas.messages.p065_message_member_timeout import (
    MemberTimeoutRequest,
    MessageMemberTimeoutError,
    parse_config,
    timeout_member,
)

APP_NAME = "p065-message-member-timeout"
PROMPT_ID = "P065"

app = typer.Typer(
    name=APP_NAME,
    help="Apply a temporary timeout to a member.",
    add_completion=False,
    no_args_is_help=False,
)


def register(parent: Any) -> None:
    """Register this command with a parent Click/Typer application."""
    if hasattr(parent, "add_typer"):
        parent.add_typer(app, name=APP_NAME)
        return
    if hasattr(parent, "add_command"):
        parent.add_command(command, name=APP_NAME)
        return
    raise TypeError("Parent CLI object does not support add_typer or add_command")


@app.callback(invoke_without_command=True)
def main(
    guild_id: str = typer.Option(..., "--guild-id", help="Guild/server ID (numeric string)."),
    user_id: str = typer.Option(..., "--user-id", help="Member/user ID (numeric string)."),
    duration_seconds: int = typer.Option(
        ...,
        "--duration-seconds",
        "--seconds",
        help="Timeout duration in seconds.",
    ),
    reason: str | None = typer.Option(None, "--reason", help="Optional audit log reason."),
    message_id: str | None = typer.Option(
        None,
        "--message-id",
        help="Optional message ID (traceability only).",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        envvar="THOMAS_DISCORD_BOT_TOKEN",
        help="Bot token (or set THOMAS_DISCORD_BOT_TOKEN).",
    ),
    api_base_url: str | None = typer.Option(
        None,
        "--api-base-url",
        help="Override Discord API base URL (advanced).",
    ),
    timeout_seconds: float = typer.Option(
        10.0,
        "--timeout-seconds",
        help="HTTP timeout in seconds.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output.",
    ),
) -> None:
    """Timeout a member.

    Automation-friendly:
    - Use `--json` for machine output.
    - Provide token via `--token` or `THOMAS_DISCORD_BOT_TOKEN`.
    """
    cfg_dict: dict[str, Any] = {"timeout_seconds": timeout_seconds}
    if token is not None:
        cfg_dict["bot_token"] = token
    if api_base_url is not None:
        cfg_dict["api_base_url"] = api_base_url

    req = MemberTimeoutRequest(
        guild_id=guild_id,
        user_id=user_id,
        duration_seconds=duration_seconds,
        reason=reason,
        message_id=message_id,
    )

    try:
        cfg = parse_config(cfg_dict)
        result = timeout_member(req, cfg)
        payload = {"ok": True, "result": result.to_dict()}

        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True))
        else:
            typer.echo(f"Timed out user {result.user_id} in guild {result.guild_id} until {result.timed_out_until}.")
        return

    except MessageMemberTimeoutError as exc:
        payload = {"ok": False, "error": exc.to_dict()}
        if json_output:
            typer.echo(json.dumps(payload, sort_keys=True))
        else:
            typer.echo(f"ERROR [{exc.code}]: {exc.message}", err=True)
        raise typer.Exit(code=1) from exc


def get_command():
    """Return the Click command (used by Thomas' CLI registry)."""
    return _get_typer_command(app)


command = get_command()
COMMAND = command

__all__ = [
    "PROMPT_ID",
    "APP_NAME",
    "register",
    "app",
    "main",
    "get_command",
    "command",
    "COMMAND",
]
