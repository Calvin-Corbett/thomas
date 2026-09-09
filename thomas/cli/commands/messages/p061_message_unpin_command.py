"""CLI surface for the Thomas-native message unpin command.

The Thomas CLI is Typer-based in most deployments, but the parity layer may
import this module directly. To stay compatible with a variety of loader
patterns we expose:

* ``app``: a Typer app containing the ``unpin`` command
* ``click_command``: the Click command generated from the Typer app
* ``register(parent_app)``: helper to attach the command to an existing Typer app

The command supports ``--json`` for machine-readable automation output.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    import typer
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Typer is required for the Thomas CLI") from exc

from thomas.messages.p061_message_unpin_command import (
    MessageUnpinConfigError,
    MessageUnpinError,
    MessageUnpinInput,
    MessageUnpinInputError,
    execute,
    format_error_json,
    format_success_json,
)

logger = logging.getLogger(__name__)

app = typer.Typer(add_completion=False, help="Unpin a message from a channel.", invoke_without_command=True)


def _resolve_client_for_cli() -> Any | None:
    """CLI-side client resolution hook.

    The Thomas runtime typically injects a client via context. The CLI entry
    point does not know that context, so it delegates to the core command's
    resolution logic by passing ctx=None.

    Tests monkeypatch this function to avoid external calls.
    """
    return None


def _run_unpin(
    channel_id: str | None = typer.Option(
        None,
        "--channel",
        "--channel-id",
        help="Channel identifier (e.g. Slack channel ID, Discord channel ID)",
    ),
    message_id: str | None = typer.Option(
        None,
        "--message",
        "--message-id",
        "--id",
        "--ts",
        "--timestamp",
        help="Message identifier (message ID or Slack timestamp)",
    ),
    message_url: str | None = typer.Option(
        None,
        "--url",
        "--message-url",
        help="Optional message URL (Slack/Discord permalinks are supported)",
    ),
    json_mode: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output.",
    ),
) -> None:
    req = MessageUnpinInput(channel_id=channel_id, message_id=message_id, message_url=message_url)

    try:
        client = _resolve_client_for_cli()
        result = execute(req, ctx=None, client=client)
    except MessageUnpinError as err:
        if json_mode:
            typer.echo(format_error_json(err))
        else:
            typer.echo(str(err), err=True)

        # Deterministic exit codes: input/config => 2, external => 1
        exit_code = 2 if isinstance(err, (MessageUnpinInputError, MessageUnpinConfigError)) else 1
        raise typer.Exit(code=exit_code)

    if json_mode:
        typer.echo(format_success_json(result))
    else:
        typer.echo(f"Unpinned message {result.message_id} in channel {result.channel_id}")


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    channel_id: str | None = typer.Option(
        None,
        "--channel",
        "--channel-id",
        help="Channel identifier (e.g. Slack channel ID, Discord channel ID)",
    ),
    message_id: str | None = typer.Option(
        None,
        "--message",
        "--message-id",
        "--id",
        "--ts",
        "--timestamp",
        help="Message identifier (message ID or Slack timestamp)",
    ),
    message_url: str | None = typer.Option(
        None,
        "--url",
        "--message-url",
        help="Optional message URL (Slack/Discord permalinks are supported)",
    ),
    json_mode: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output.",
    ),
) -> None:
    if ctx.invoked_subcommand is not None:
        return
    _run_unpin(channel_id=channel_id, message_id=message_id, message_url=message_url, json_mode=json_mode)


@app.command("unpin")
def unpin_command(
    channel_id: str | None = typer.Option(
        None,
        "--channel",
        "--channel-id",
        help="Channel identifier (e.g. Slack channel ID, Discord channel ID)",
    ),
    message_id: str | None = typer.Option(
        None,
        "--message",
        "--message-id",
        "--id",
        "--ts",
        "--timestamp",
        help="Message identifier (message ID or Slack timestamp)",
    ),
    message_url: str | None = typer.Option(
        None,
        "--url",
        "--message-url",
        help="Optional message URL (Slack/Discord permalinks are supported)",
    ),
    json_mode: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output.",
    ),
) -> None:
    """Unpin a message."""
    _run_unpin(channel_id=channel_id, message_id=message_id, message_url=message_url, json_mode=json_mode)


def register(parent_app: typer.Typer) -> None:
    """Attach this command to an existing Typer app.

    Different Thomas CLI loaders wire subcommands in different ways. We support
    two common patterns:
      1) Parent is already the *message(s)* group -> register an ``unpin`` command.
      2) Parent is the root app -> register a ``message`` sub-app.
    """
    try:
        parent_app.command("unpin")(unpin_command)
        return
    except Exception:  # REVIEWED: broad catch
        # Broad catch: different Typer loaders reject duplicate/direct command registration differently.
        logger.exception("Failed to register message unpin as a direct command.")
        pass

    try:
        parent_app.add_typer(app, name="message")
        return
    except Exception:  # REVIEWED: broad catch
        # Broad catch: fall back to a standalone compatibility command name when message group registration fails.
        logger.exception("Failed to register message unpin under the message group.")
        pass

    parent_app.add_typer(app, name="message-unpin")


# Many loaders expect a Click command object.
try:
    from typer.main import get_command as _get_command  # type: ignore

    click_command = _get_command(app)
except ImportError:  # pragma: no cover
    click_command = typer.main.get_command(app)


# Compatibility aliases for different CLI loaders/parity harnesses.
COMMAND = click_command


def get_command() -> Any:
    return click_command


def get_app() -> typer.Typer:
    return app


__all__ = [
    "app",
    "click_command",
    "COMMAND",
    "get_command",
    "get_app",
    "register",
    "main",
    "unpin_command",
]
