"""P066 - CLI wrapper for member moderation (kick/ban).

This module is intended for Thomas' CLI parity loader patterns:
- Provides a `register(app)` function to attach commands to a Typer group.
- Also exposes a standalone `app` Typer instance for direct invocation/tests.

Commands (Thomas-native):
- moderate-member --action kick|ban
- kick-member
- ban-member

Machine output:
- Add `--json` to emit a single JSON object to stdout, suitable for automation.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import typer

from thomas.messages.p066_message_member_kick_and_ban import run as run_moderation


def _emit(result: dict, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(result, sort_keys=True))
        return

    if result.get("ok") is True:
        typer.echo(result.get("message") or "Success")
        return

    err = result.get("error") or {}
    code = err.get("code", "unknown")
    msg = err.get("message", "Unknown failure")
    typer.echo(f"ERROR[{code}] {msg}")


def register(app: typer.Typer) -> None:
    """Register commands onto an existing Typer app/group."""

    @app.command("moderate-member")
    def moderate_member(
        action: str = typer.Option(..., "--action", help="kick or ban"),
        channel_id: str = typer.Option(..., "--channel-id", help="Channel / room identifier"),
        member_id: str = typer.Option(..., "--member-id", help="Member / user identifier"),
        reason: Optional[str] = typer.Option(None, "--reason", help="Optional moderation reason"),
        webhook_url: Optional[str] = typer.Option(
            None,
            "--webhook-url",
            help="Member moderation webhook URL (or set THOMAS_MESSAGES_MODERATION_WEBHOOK_URL)",
        ),
        timeout_s: float = typer.Option(10.0, "--timeout-s", help="HTTP timeout in seconds"),
        json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
        request_id: Optional[str] = typer.Option(None, "--request-id", help="Optional trace / request id"),
    ) -> None:
        """Kick or ban a member from a channel."""

        result = run_moderation(
            {
                "action": action,
                "channel_id": channel_id,
                "member_id": member_id,
                "reason": reason,
                "timeout_s": timeout_s,
                "webhook_url": webhook_url,
                "request_id": request_id,
            }
        )
        _emit(result, as_json=json_out)
        raise typer.Exit(code=0 if result.get("ok") is True else 1)

    @app.command("kick-member")
    def kick_member(
        channel_id: str = typer.Option(..., "--channel-id", help="Channel / room identifier"),
        member_id: str = typer.Option(..., "--member-id", help="Member / user identifier"),
        reason: Optional[str] = typer.Option(None, "--reason", help="Optional moderation reason"),
        webhook_url: Optional[str] = typer.Option(None, "--webhook-url", help="Outbound webhook URL"),
        timeout_s: float = typer.Option(10.0, "--timeout-s", help="HTTP timeout in seconds"),
        json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
        request_id: Optional[str] = typer.Option(None, "--request-id", help="Optional trace / request id"),
    ) -> None:
        """Kick a member from a channel."""

        result = run_moderation(
            {
                "action": "kick",
                "channel_id": channel_id,
                "member_id": member_id,
                "reason": reason,
                "timeout_s": timeout_s,
                "webhook_url": webhook_url,
                "request_id": request_id,
            }
        )
        _emit(result, as_json=json_out)
        raise typer.Exit(code=0 if result.get("ok") is True else 1)

    @app.command("ban-member")
    def ban_member(
        channel_id: str = typer.Option(..., "--channel-id", help="Channel / room identifier"),
        member_id: str = typer.Option(..., "--member-id", help="Member / user identifier"),
        reason: Optional[str] = typer.Option(None, "--reason", help="Optional moderation reason"),
        webhook_url: Optional[str] = typer.Option(None, "--webhook-url", help="Outbound webhook URL"),
        timeout_s: float = typer.Option(10.0, "--timeout-s", help="HTTP timeout in seconds"),
        json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
        request_id: Optional[str] = typer.Option(None, "--request-id", help="Optional trace / request id"),
    ) -> None:
        """Ban a member from a channel."""

        result = run_moderation(
            {
                "action": "ban",
                "channel_id": channel_id,
                "member_id": member_id,
                "reason": reason,
                "timeout_s": timeout_s,
                "webhook_url": webhook_url,
                "request_id": request_id,
            }
        )
        _emit(result, as_json=json_out)
        raise typer.Exit(code=0 if result.get("ok") is True else 1)


# Standalone app (helps unit tests and is harmless for auto-discovery).
app = typer.Typer(add_completion=False, help="Member moderation commands")


@app.callback()
def _main() -> None:
    """Moderate members in a messaging channel."""
    return


register(app)


# Loader compatibility aliases (low-cost, helps if parity loaders look for these names).
def register_commands(app: typer.Typer) -> None:
    register(app)


def attach(app: typer.Typer) -> None:
    register(app)


__all__ = ["app", "register", "register_commands", "attach"]
