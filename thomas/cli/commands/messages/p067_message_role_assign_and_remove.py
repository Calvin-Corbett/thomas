"""
P067 - Message role assign and remove (CLI).

Thomas-native command that grants/revokes a Discord role for a guild member.

Subcommands:
- assign: grant a role
- remove: revoke a role

Both support `--json` for automation-friendly output.
"""
from __future__ import annotations

import json
from typing import Any, Optional

import typer

from thomas.messages.p067_message_role_assign_and_remove import (
    ExternalMessageRoleFailure,
    InvalidMessageRoleInput,
    MessageRoleChangeResult,
    MissingMessageRoleConfig,
    assign_role_to_member,
    remove_role_from_member,
)

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Assign or remove Discord roles for members.",
)

GuildIdOpt = typer.Option(..., "--guild-id", help="Discord guild (server) id.")
UserIdOpt = typer.Option(..., "--user-id", help="Discord user id (member id).")
RoleIdOpt = typer.Option(..., "--role-id", help="Discord role id.")
JsonFlag = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout.")


def _emit_result(result: MessageRoleChangeResult, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(result.to_dict(), sort_keys=True))
        return

    if result.action == "assign":
        typer.echo(f"Assigned role {result.role_id} to user {result.user_id} in guild {result.guild_id}.")
    else:
        typer.echo(f"Removed role {result.role_id} from user {result.user_id} in guild {result.guild_id}.")


def _emit_error(exc: Exception, *, as_json: bool) -> None:
    if as_json and isinstance(
        exc, (InvalidMessageRoleInput, MissingMessageRoleConfig, ExternalMessageRoleFailure)
    ):
        # Keep JSON on stdout for automation. Avoid leaking secrets (token never included by core module).
        payload: dict[str, Any] = {"ok": False, "error": exc.to_dict()}  # type: ignore[attr-defined]
        typer.echo(json.dumps(payload, sort_keys=True))
        return

    # Human output -> stderr
    typer.secho(str(exc), fg=typer.colors.RED, err=True)


@app.command("assign")
def cli_assign(
    guild_id: str = GuildIdOpt,
    user_id: str = UserIdOpt,
    role_id: str = RoleIdOpt,
    json_output: bool = JsonFlag,
    token: str | None = typer.Option(None, "--token", help="Override Discord bot token (otherwise uses env/config)."),
    timeout_s: float = typer.Option(15.0, "--timeout-s", help="HTTP timeout seconds."),
) -> None:
    """Assign (grant) a role to a member in a guild."""
    try:
        result = assign_role_to_member(
            guild_id=guild_id,
            user_id=user_id,
            role_id=role_id,
            discord_bot_token=token,
            timeout_s=timeout_s,
        )
        _emit_result(result, as_json=json_output)
    except (InvalidMessageRoleInput, MissingMessageRoleConfig, ExternalMessageRoleFailure) as exc:
        _emit_error(exc, as_json=json_output)
        raise typer.Exit(code=1)


@app.command("remove")
def cli_remove(
    guild_id: str = GuildIdOpt,
    user_id: str = UserIdOpt,
    role_id: str = RoleIdOpt,
    json_output: bool = JsonFlag,
    token: str | None = typer.Option(None, "--token", help="Override Discord bot token (otherwise uses env/config)."),
    timeout_s: float = typer.Option(15.0, "--timeout-s", help="HTTP timeout seconds."),
) -> None:
    """Remove (revoke) a role from a member in a guild."""
    try:
        result = remove_role_from_member(
            guild_id=guild_id,
            user_id=user_id,
            role_id=role_id,
            discord_bot_token=token,
            timeout_s=timeout_s,
        )
        _emit_result(result, as_json=json_output)
    except (InvalidMessageRoleInput, MissingMessageRoleConfig, ExternalMessageRoleFailure) as exc:
        _emit_error(exc, as_json=json_output)
        raise typer.Exit(code=1)


# ---- Registration helpers (defensive: different Thomas parity loaders may look for different hooks) ----

def register(parent: typer.Typer, *, name: str = "role") -> None:
    """Register this command group under an existing Typer parent."""
    parent.add_typer(app, name=name)


def get_app() -> typer.Typer:
    """Return the Typer app (common dynamic-discovery hook)."""
    return app


def build_cli() -> typer.Typer:
    """Alias for dynamic discovery."""
    return app
