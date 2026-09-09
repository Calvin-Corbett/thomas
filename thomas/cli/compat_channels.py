"""Channels and messages-related compatibility CLI commands."""

from __future__ import annotations

import json
import secrets
import time
from typing import Any

import click

from thomas.cli.pack_bridge import register_pack_proxy_commands
from thomas.cli.parity_support import (
    load_messages as _load_messages,
)
from thomas.cli.parity_support import (
    save_messages as _save_messages,
)
from thomas.cli.parity_support import (
    send_channel_message as _send_channel_message,
)
from thomas.cli.parity_support import (
    utc_iso as _utc_iso,
)
from thomas.core.config import AppConfig


@click.group()
@click.pass_context
def message(ctx: click.Context) -> None:
    """Local message queue + delivery tracking."""
    _ = ctx


@message.command("send")
@click.option(
    "--channel",
    default="local",
    show_default=True,
    type=click.Choice(["local", "telegram", "discord", "slack"], case_sensitive=False),
)
@click.option("--target", default="", help="Target user/channel id.")
@click.option("--message", "message_text", required=True, help="Message body.")
@click.option("--deliver/--queue", default=False, show_default=True, help="Mark immediate delivery status.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def message_send(
    ctx: click.Context,
    channel: str,
    target: str,
    message_text: str,
    deliver: bool,
    as_json: bool,
) -> None:
    """Queue a message record."""
    config: AppConfig = ctx.obj["config"]
    rows = _load_messages(config)
    mid = f"msg_{int(time.time() * 1000)}_{secrets.token_hex(3)}"
    delivery: dict[str, Any] = {}
    status = "queued"
    if deliver:
        delivery = _send_channel_message(
            config,
            channel=str(channel).strip().lower(),
            target=str(target).strip(),
            text=str(message_text),
        )
        status = "delivered" if bool(delivery.get("ok")) else "failed"
    row = {
        "id": mid,
        "channel": str(channel).strip().lower(),
        "target": str(target).strip(),
        "text": str(message_text),
        "status": status,
        "delivery": delivery,
        "created_at": _utc_iso(),
        "updated_at": _utc_iso(),
    }
    rows.append(row)
    _save_messages(config, rows)
    payload = {"ok": bool((not deliver) or bool(delivery.get("ok"))), "message": row}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(f"queued id={mid} channel={row['channel']} target={row['target'] or '-'} status={row['status']}")
    if deliver and not bool(delivery.get("ok")):
        raise SystemExit(1)


@message.command("list")
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def message_list(ctx: click.Context, limit: int, as_json: bool) -> None:
    """List recent message records."""
    config: AppConfig = ctx.obj["config"]
    rows = _load_messages(config)
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    rows = rows[: max(1, int(limit))]
    payload = {"count": len(rows), "messages": rows}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Messages: {len(rows)}")
    for row in rows:
        click.echo(
            f"- {row.get('id')} | {row.get('channel')} | {row.get('target') or '-'} | "
            f"{row.get('status')} | {row.get('created_at')}"
        )


@message.command("mark-sent")
@click.argument("message_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def message_mark_sent(ctx: click.Context, message_id: str, as_json: bool) -> None:
    """Mark a queued message as delivered."""
    config: AppConfig = ctx.obj["config"]
    rows = _load_messages(config)
    target = str(message_id).strip()
    hit = False
    for row in rows:
        if str(row.get("id") or "") == target:
            row["status"] = "delivered"
            row["updated_at"] = _utc_iso()
            hit = True
            break
    if hit:
        _save_messages(config, rows)
    payload = {"ok": hit, "id": target}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if hit:
        click.echo(f"marked delivered: {target}")
    else:
        click.echo(f"message not found: {target}")
        raise SystemExit(1)


@message.command("retry")
@click.argument("message_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def message_retry(ctx: click.Context, message_id: str, as_json: bool) -> None:
    """Retry delivery for a queued/failed message."""
    config: AppConfig = ctx.obj["config"]
    rows = _load_messages(config)
    target = str(message_id).strip()
    found: dict[str, Any] | None = None
    for row in rows:
        if str(row.get("id") or "") == target:
            found = row
            break
    if found is None:
        payload = {"ok": False, "id": target, "error": "message_not_found"}
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            click.echo(f"message not found: {target}")
        raise SystemExit(1)

    delivery = _send_channel_message(
        config,
        channel=str(found.get("channel") or "local"),
        target=str(found.get("target") or ""),
        text=str(found.get("text") or ""),
    )
    found["delivery"] = delivery
    found["status"] = "delivered" if bool(delivery.get("ok")) else "failed"
    found["updated_at"] = _utc_iso()
    _save_messages(config, rows)
    payload = {"ok": bool(delivery.get("ok")), "id": target, "message": found}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(f"retried {target}: {found['status']}")
    if not bool(delivery.get("ok")):
        raise SystemExit(1)


@click.group(name="messages")
@click.pass_context
def messages(ctx: click.Context) -> None:
    """Message delivery compatibility commands."""
    _ = ctx


def _parse_message_meta(items: tuple[str, ...]) -> dict[str, str]:
    from thomas.messages.p074_message_integration_into_cli_group import InvalidMessageInputError

    out: dict[str, str] = {}
    for item in items:
        raw = str(item or "")
        if "=" not in raw:
            raise InvalidMessageInputError("Metadata must be key=value.", details={"value": raw})
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            raise InvalidMessageInputError("Metadata key cannot be empty.", details={"value": raw})
        out[key] = value
    return out


def _message_integration_exit_code(err: Exception) -> int:
    from thomas.messages.p074_message_integration_into_cli_group import (
        InvalidMessageInputError,
        MessageConfigError,
        MessageDeliveryError,
    )

    if isinstance(err, InvalidMessageInputError):
        return 2
    if isinstance(err, MessageConfigError):
        return 3
    if isinstance(err, MessageDeliveryError):
        return 4
    return 1


@messages.command("send")
@click.argument("text")
@click.option("--channel", required=True, help="Destination channel name.")
@click.option("--meta", "meta_items", multiple=True, help="Metadata key=value (repeatable).")
@click.option("--id", "message_id", default="", help="Optional explicit message id.")
@click.option("--webhook-url", default="", help="Override webhook URL.")
@click.option("--timeout", "timeout_seconds", type=float, default=None, help="HTTP timeout in seconds.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def messages_send(
    text: str,
    channel: str,
    meta_items: tuple[str, ...],
    message_id: str,
    webhook_url: str,
    timeout_seconds: float | None,
    as_json: bool,
) -> None:
    """
    Send a message using the P074 webhook-delivery contract.
    """
    from thomas.messages.p074_message_integration_into_cli_group import (
        MessageIntegrationError,
        MessageSendRequest,
        load_message_delivery_config,
        send_message,
    )

    try:
        metadata = _parse_message_meta(meta_items)
        config = load_message_delivery_config(
            webhook_url=(str(webhook_url).strip() or None),
            timeout_seconds=timeout_seconds,
        )
        result = send_message(
            MessageSendRequest(
                channel=str(channel or "").strip(),
                text=str(text or ""),
                metadata=metadata,
                message_id=(str(message_id or "").strip() or None),
            ),
            config,
        )
        payload = {"ok": True, "result": result.to_dict()}
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            click.echo(f"sent {result.message_id} -> {result.channel}")
    except MessageIntegrationError as e:
        payload = {"ok": False, "error": e.to_dict()}
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        else:
            click.echo(f"Error ({e.code}): {e}", err=True)
        raise SystemExit(_message_integration_exit_code(e))


register_pack_proxy_commands(
    message,
    package="thomas.cli.commands.messages",
    family_hint="message",
)
