from __future__ import annotations

import json
import sys

import click


@click.group()
@click.pass_context
def webhooks(ctx: click.Context) -> None:
    """Manage webhook registrations, stats, and inbox."""
    _ = ctx


def _webhook_fail(e: Exception) -> None:
    detail = getattr(e, "detail", None)
    status = getattr(e, "status_code", None)
    if detail is None:
        detail = str(e)
    if status is not None:
        click.echo(f"Webhook error ({status}): {detail}", err=True)
    else:
        click.echo(f"Webhook error: {detail}", err=True)
    sys.exit(1)


@webhooks.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def webhooks_list(as_json: bool) -> None:
    """List registered webhooks."""
    from thomas.server.routes import webhooks as wh

    try:
        items = wh._STORE.list()
        rows = [
            {
                "id": r.id,
                "has_secret": bool(r.secret),
                "created_at": r.created_at,
                "rate_limit_per_min": int(r.rate_limit_per_min),
            }
            for r in items
        ]
    except Exception as e:
        _webhook_fail(e)
        return

    if as_json:
        click.echo(json.dumps({"count": len(rows), "webhooks": rows}, ensure_ascii=False, indent=2))
        return
    click.echo(f"Webhooks: {len(rows)}")
    for row in rows:
        secret = "yes" if row["has_secret"] else "no"
        click.echo(
            f"- {row['id']} | secret={secret} | rate_limit_per_min={row['rate_limit_per_min']} | created={row['created_at']}"
        )


@webhooks.command("show")
@click.argument("webhook_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def webhooks_show(webhook_id: str, as_json: bool) -> None:
    """Show one webhook registration."""
    from thomas.server.routes import webhooks as wh

    try:
        rec = wh._STORE.get(str(webhook_id).strip())
        if rec is None:
            click.echo(f"Webhook '{webhook_id}' not found.", err=True)
            sys.exit(1)
        stats = wh._STATS.get(f"generic:{rec.id}")
        payload = {
            "id": rec.id,
            "has_secret": bool(rec.secret),
            "goal_template": rec.goal_template,
            "created_at": rec.created_at,
            "rate_limit_per_min": int(rec.rate_limit_per_min),
            "stats": stats,
        }
    except Exception as e:
        _webhook_fail(e)
        return

    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"id: {payload['id']}")
    click.echo(f"has_secret: {payload['has_secret']}")
    click.echo(f"rate_limit_per_min: {payload['rate_limit_per_min']}")
    click.echo(f"created_at: {payload['created_at']}")
    click.echo(f"goal_template: {payload['goal_template']}")
    click.echo(f"stats: {payload['stats']}")


@webhooks.command("register")
@click.option("--id", "webhook_id", required=True, help="Webhook id.")
@click.option("--template", "goal_template", required=True, help="Goal template text.")
@click.option("--secret", default="", help="Optional webhook secret.")
@click.option("--rate-limit", "rate_limit_per_min", default=0, type=int, help="Rate limit per minute.")
@click.option("--upsert", is_flag=True, help="Update existing webhook if it exists.")
def webhooks_register(
    webhook_id: str,
    goal_template: str,
    secret: str,
    rate_limit_per_min: int,
    upsert: bool,
) -> None:
    """Register a webhook."""
    from thomas.server.routes import webhooks as wh

    try:
        rec = wh.WebhookRecord(
            id=str(webhook_id).strip(),
            secret=str(secret).strip() or None,
            goal_template=str(goal_template),
            created_at=wh._now_iso(),
            rate_limit_per_min=int(rate_limit_per_min or wh.DEFAULT_RATE_LIMIT_PER_MIN),
        )
        if upsert:
            wh._STORE.upsert(rec)
        else:
            wh._STORE.register(rec)
    except Exception as e:
        _webhook_fail(e)
        return

    action = "upserted" if upsert else "registered"
    click.echo(f"Webhook {action}: {rec.id}")


@webhooks.command("delete")
@click.argument("webhook_id")
def webhooks_delete(webhook_id: str) -> None:
    """Delete a webhook."""
    from thomas.server.routes import webhooks as wh

    try:
        wh._STORE.delete(str(webhook_id).strip())
    except Exception as e:
        _webhook_fail(e)
        return
    click.echo(f"Webhook deleted: {webhook_id}")


@webhooks.command("stats")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def webhooks_stats(as_json: bool) -> None:
    """Show webhook aggregate stats."""
    from thomas.server.routes import webhooks as wh

    try:
        payload = wh._STATS.all()
    except Exception as e:
        _webhook_fail(e)
        return

    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo("Webhook stats:")
    for key, val in payload.items():
        click.echo(f"- {key}: {val}")


@webhooks.command("inbox")
@click.option("--limit", default=25, show_default=True, type=int, help="Max inbox records.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def webhooks_inbox(limit: int, as_json: bool) -> None:
    """Show recent webhook inbox records."""
    from thomas.server.routes import webhooks as wh

    try:
        rows = wh._INBOX.tail(int(limit))
    except Exception as e:
        _webhook_fail(e)
        return

    if as_json:
        click.echo(json.dumps({"count": len(rows), "records": rows}, ensure_ascii=False, indent=2))
        return
    click.echo(f"Inbox records: {len(rows)}")
    for row in rows:
        eid = str(row.get("event_id") or "")
        provider = str(row.get("provider") or "")
        status = str(row.get("status") or "")
        goal_id = str(row.get("goal_id") or "-")
        received_at = str(row.get("received_at") or "")
        click.echo(f"- {received_at} | {provider} | {status} | goal={goal_id} | event={eid}")


def register_webhooks_commands(cli: click.Group) -> None:
    if "webhooks" not in cli.commands:
        cli.add_command(webhooks)

