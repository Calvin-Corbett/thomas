"""Messages CLI group.

Prompt P074 wires message operations into the root CLI via
`thomas.cli.parity_compat`.

This sub-app intentionally keeps a small command surface:
  - `messages send` (with `--json` output for automation)
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import typer

from thomas.messages.p074_message_integration_into_cli_group import (
    InvalidMessageInputError,
    MessageConfigError,
    MessageDeliveryError,
    MessageIntegrationError,
    MessageSendRequest,
    load_message_delivery_config,
    send_message,
)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help="Send and inspect messages.",
)


def _exit_code_for_error(err: MessageIntegrationError) -> int:
    if isinstance(err, InvalidMessageInputError):
        return 2
    if isinstance(err, MessageConfigError):
        return 3
    if isinstance(err, MessageDeliveryError):
        return 4
    return 1


def _render_json(payload: Dict[str, Any]) -> str:
    # Stable key ordering helps with diffs and scripting.
    return json.dumps(payload, sort_keys=True)


def _parse_metadata(pairs: List[str]) -> Dict[str, str]:
    metadata: Dict[str, str] = {}
    for item in pairs:
        if "=" not in item:
            raise InvalidMessageInputError("Metadata must be key=value.", details={"value": item})
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise InvalidMessageInputError("Metadata key cannot be empty.", details={"value": item})
        metadata[key] = value
    return metadata


@app.command("send")
def send_command(
    text: str = typer.Argument(..., help="Message text."),
    channel: str = typer.Option(..., "--channel", "-c", help="Destination channel."),
    meta: List[str] = typer.Option([], "--meta", help="Optional metadata as key=value (repeatable)."),
    message_id: Optional[str] = typer.Option(
        None,
        "--id",
        help="Optional explicit message id (useful for idempotency in scripts).",
    ),
    webhook_url: Optional[str] = typer.Option(
        None,
        "--webhook-url",
        help="Override the configured webhook URL.",
    ),
    timeout_seconds: Optional[float] = typer.Option(
        None,
        "--timeout",
        help="HTTP timeout in seconds.",
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output.",
    ),
) -> None:
    """Send a message to a channel."""

    try:
        metadata = _parse_metadata(meta)
        config = load_message_delivery_config(webhook_url=webhook_url, timeout_seconds=timeout_seconds)
        result = send_message(
            MessageSendRequest(channel=channel, text=text, metadata=metadata, message_id=message_id),
            config,
        )
    except MessageIntegrationError as e:
        if json_output:
            typer.echo(_render_json({"ok": False, "error": e.to_dict()}))
        else:
            typer.echo(f"Error ({e.code}): {e}", err=True)
        raise typer.Exit(code=_exit_code_for_error(e))

    if json_output:
        typer.echo(_render_json({"ok": True, "result": result.to_dict()}))
    else:
        typer.echo(f"Sent {result.message_id} to {result.channel} via {result.provider}.")
