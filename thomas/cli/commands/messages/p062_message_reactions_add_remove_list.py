"""CLI: message reactions add/remove/list (P062).

Thomas-native CLI surface for managing reactions on a message.

Design goals
- Deterministic machine-readable output via --json
- Thin wrapper over thomas.messages.p062_message_reactions_add_remove_list (core logic)
- Backend selection via flags or env vars (see core module for env var names)
"""

from __future__ import annotations

import json
from typing import Optional

import typer

app = typer.Typer(help="Add, remove, or list reactions on a message.")


def _emit(result: dict, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return

    # Human-readable fallback
    if result.get("ok"):
        action = result.get("action")
        msg_id = result.get("message_id")
        emoji = result.get("emoji")
        if action == "list":
            reactions = result.get("reactions", [])
            if not reactions:
                typer.echo(f"No reactions on message {msg_id}.")
            else:
                formatted = ", ".join(
                    f"{r.get('emoji')}×{r.get('count')}"
                    for r in reactions
                    if isinstance(r, dict) and r.get("emoji") is not None and r.get("count") is not None
                )
                typer.echo(f"Reactions on message {msg_id}: {formatted}")
        else:
            applied = bool(result.get("applied"))
            verb = "Added" if action == "add" else "Removed"
            suffix = "" if applied else " (no-op)"
            typer.echo(f"{verb} {emoji} on message {msg_id}{suffix}.")
    else:
        err = result.get("error", {}) or {}
        typer.echo(f"Error[{err.get('code')}]: {err.get('message')}")


def _run_payload(payload: dict, *, backend: Optional[str], api_base_url: Optional[str], api_token: Optional[str], timeout_seconds: float) -> dict:
    from thomas.messages.p062_message_reactions_add_remove_list import MessageReactionsConfig, run

    cfg = None
    if backend or api_base_url or api_token:
        # Allow partial config: core layer will merge missing pieces from env vars.
        cfg = MessageReactionsConfig(
            backend=(backend or "").strip() or "memory",
            api_base_url=api_base_url,
            api_token=api_token,
            timeout_seconds=timeout_seconds,
        )
    return run(payload, config=cfg)


def _handle_error(exc: Exception, *, json_mode: bool) -> None:
    from thomas.messages.p062_message_reactions_add_remove_list import MessageReactionsError

    if isinstance(exc, MessageReactionsError):
        _emit(exc.to_dict(), json_mode=json_mode)
        raise typer.Exit(code=2 if exc.code == "invalid_input" else 1)

    _emit(
        {
            "ok": False,
            "error": {"code": "unexpected_error", "message": str(exc), "details": {}},
        },
        json_mode=json_mode,
    )
    raise typer.Exit(code=1)


@app.command("add")
def add(
    message_id: str = typer.Option(..., "--message-id", help="Message identifier."),
    emoji: str = typer.Option(..., "--emoji", help="Emoji to add (unicode or :shortcode:)."),
    channel_id: Optional[str] = typer.Option(None, "--channel-id", help="Optional channel identifier."),
    user_id: Optional[str] = typer.Option(None, "--user-id", help="Optional user identifier."),
    backend: Optional[str] = typer.Option(None, "--backend", help="Backend to use (memory/http)."),
    api_base_url: Optional[str] = typer.Option(None, "--api-base-url", help="API base URL for http backend (optional)."),
    api_token: Optional[str] = typer.Option(None, "--api-token", help="Bearer token for http backend (optional)."),
    timeout_seconds: float = typer.Option(10.0, "--timeout-seconds", help="HTTP timeout seconds (optional)."),
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Add a reaction to a message."""
    payload = {
        "operation": "add",
        "message_id": message_id,
        "emoji": emoji,
        "channel_id": channel_id,
        "user_id": user_id,
    }
    try:
        result = _run_payload(
            payload,
            backend=backend,
            api_base_url=api_base_url,
            api_token=api_token,
            timeout_seconds=timeout_seconds,
        )
    except Exception as e:
        _handle_error(e, json_mode=json_mode)
        return
    _emit(result, json_mode=json_mode)


@app.command("remove")
def remove(
    message_id: str = typer.Option(..., "--message-id", help="Message identifier."),
    emoji: str = typer.Option(..., "--emoji", help="Emoji to remove (unicode or :shortcode:)."),
    channel_id: Optional[str] = typer.Option(None, "--channel-id", help="Optional channel identifier."),
    user_id: Optional[str] = typer.Option(None, "--user-id", help="Optional user identifier."),
    backend: Optional[str] = typer.Option(None, "--backend", help="Backend to use (memory/http)."),
    api_base_url: Optional[str] = typer.Option(None, "--api-base-url", help="API base URL for http backend (optional)."),
    api_token: Optional[str] = typer.Option(None, "--api-token", help="Bearer token for http backend (optional)."),
    timeout_seconds: float = typer.Option(10.0, "--timeout-seconds", help="HTTP timeout seconds (optional)."),
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Remove a reaction from a message."""
    payload = {
        "operation": "remove",
        "message_id": message_id,
        "emoji": emoji,
        "channel_id": channel_id,
        "user_id": user_id,
    }
    try:
        result = _run_payload(
            payload,
            backend=backend,
            api_base_url=api_base_url,
            api_token=api_token,
            timeout_seconds=timeout_seconds,
        )
    except Exception as e:
        _handle_error(e, json_mode=json_mode)
        return
    _emit(result, json_mode=json_mode)


@app.command("list")
def list_cmd(
    message_id: str = typer.Option(..., "--message-id", help="Message identifier."),
    channel_id: Optional[str] = typer.Option(None, "--channel-id", help="Optional channel identifier."),
    backend: Optional[str] = typer.Option(None, "--backend", help="Backend to use (memory/http)."),
    api_base_url: Optional[str] = typer.Option(None, "--api-base-url", help="API base URL for http backend (optional)."),
    api_token: Optional[str] = typer.Option(None, "--api-token", help="Bearer token for http backend (optional)."),
    timeout_seconds: float = typer.Option(10.0, "--timeout-seconds", help="HTTP timeout seconds (optional)."),
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """List reactions on a message."""
    payload = {"operation": "list", "message_id": message_id, "channel_id": channel_id}
    try:
        result = _run_payload(
            payload,
            backend=backend,
            api_base_url=api_base_url,
            api_token=api_token,
            timeout_seconds=timeout_seconds,
        )
    except Exception as e:
        _handle_error(e, json_mode=json_mode)
        return
    _emit(result, json_mode=json_mode)


# Parity/auto-discovery helpers.
COMMAND_NAME = "reactions"
PROMPT_ID = "P062"


def register(parent_app: typer.Typer) -> None:
    parent_app.add_typer(app, name=COMMAND_NAME)


def get_click_command():
    from typer.main import get_command

    return get_command(app)


# Export common names that loaders may probe for.
cli = app
command = get_click_command()
COMMAND = command
APP = app
