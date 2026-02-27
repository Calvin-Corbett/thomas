"""thomas.cli.commands.messages.p057_message_search_command

P057 - Message search command (CLI wiring).

This module wires the core message search logic into the Thomas CLI.

Key features
- Deterministic JSON output via `--json` for automation
- Optional backend selection (`--backend auto|local|discord`)
"""

from __future__ import annotations

import json
from typing import Any

import typer

from thomas.messages.p057_message_search_command import (
    MessageSearchBackend,
    MessageSearchError,
    search_messages,
    to_json_success,
    validate_message_search_input,
)


def _resolve_runtime(ctx: typer.Context | None) -> Any | None:
    if ctx is None:
        return None
    return getattr(ctx, "obj", None)


def _emit_json(payload: object) -> None:
    typer.echo(json.dumps(payload, sort_keys=True, separators=(",", ":")))


def _emit_human(payload: dict[str, Any]) -> None:
    total = payload.get("total_results", 0)
    hits = payload.get("hits", [])
    typer.echo(f"{len(hits)} match(es) (total_results={total})")
    for h in hits:
        ts = h.get("timestamp") or ""
        author = h.get("author_id") or ""
        ch = h.get("channel_id") or ""
        url = h.get("url") or ""
        content = (h.get("content") or "").replace("\n", " ").strip()
        if len(content) > 140:
            content = content[:140] + "…"
        typer.echo(f"- [{ts}] channel={ch} author={author} {content}")
        if url:
            typer.echo(f"  {url}")


def message_search_command(
    ctx: typer.Context,
    query: str = typer.Option(
        ..., "--query", help="Search query (substring match for local store; content filter for Discord)"
    ),
    guild_id: str | None = typer.Option(None, "--guild-id", help="Guild/server id (required for Discord backend)"),
    channel_id: str | None = typer.Option(None, "--channel-id", help="Single channel id filter"),
    channel_ids: list[str] = typer.Option([], "--channel-ids", help="Repeatable channel id filters"),
    author_id: str | None = typer.Option(None, "--author-id", help="Single author/user id filter"),
    author_ids: list[str] = typer.Option([], "--author-ids", help="Repeatable author/user id filters"),
    limit: int = typer.Option(25, "--limit", min=1, max=100, help="Max matches returned (1-100)"),
    backend: MessageSearchBackend = typer.Option(
        MessageSearchBackend.AUTO, "--backend", help="Backend: auto, local, or discord"
    ),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
) -> None:
    """Search messages."""
    runtime = _resolve_runtime(ctx)

    try:
        validated = validate_message_search_input(
            query=query,
            guild_id=guild_id,
            channel_id=channel_id,
            channel_ids=channel_ids,
            author_id=author_id,
            author_ids=author_ids,
            limit=limit,
        )
        result = search_messages(validated, runtime_or_config=runtime, backend=backend)
        payload = to_json_success(result)
        if json_out:
            _emit_json(payload)
        else:
            _emit_human(payload)
    except MessageSearchError as e:
        if json_out:
            _emit_json(e.to_json())
        else:
            typer.echo(f"ERROR[{e.code}]: {e}", err=True)
        raise typer.Exit(code=1) from e


def register(parent_app: Any) -> None:
    """Register the command on a parent Typer app/group.

    The Thomas CLI typically discovers command modules and calls `register()`.
    This function is idempotent when called multiple times.
    """
    # Idempotency guard on the parent app object.
    if getattr(parent_app, "_p057_message_search_registered", False):
        return

    command_attr = getattr(parent_app, "command", None)
    if callable(command_attr):
        parent_app.command("search")(message_search_command)
        parent_app._p057_message_search_registered = True
        return

    add_command = getattr(parent_app, "add_command", None)
    if callable(add_command):
        tmp = typer.Typer(add_completion=False)
        tmp.command("search")(message_search_command)
        add_command(typer.main.get_command(tmp), "search")
        parent_app._p057_message_search_registered = True
        return

    raise RuntimeError("Unsupported CLI container for message search command registration")


# Best-effort side-effect registration when imported inside the messages commands package.
try:
    from . import app as _messages_app  # type: ignore
except ImportError:  # pragma: no cover
    _messages_app = None  # type: ignore

if _messages_app is not None:  # pragma: no cover
    try:
        register(_messages_app)
    except ImportError:
        pass
