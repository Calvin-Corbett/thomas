from __future__ import annotations

import json
from typing import Any

import click

from thomas.cli.pack_bridge import register_pack_proxy_commands
from thomas.core.config import AppConfig
from thomas.marketplace.channels._catalog import (
    CHANNEL_PROVIDER_NAMES as _CHANNEL_PROVIDER_NAMES,
)
from thomas.marketplace.channels._catalog import (
    PROVIDER_SPECS as _PROVIDER_SPECS,
)
from thomas.marketplace.channels._catalog import (
    load_channels_store as _load_channels_store,
)
from thomas.marketplace.channels._catalog import (
    local_validation_checks as _local_validation_checks,
)
from thomas.marketplace.channels._catalog import (
    mask_secret as _mask_secret,
)
from thomas.marketplace.channels._catalog import (
    now_utc_iso as _now_utc_iso,
)
from thomas.marketplace.channels._catalog import (
    provider_configured as _provider_configured,
)
from thomas.marketplace.channels._catalog import (
    provider_online_probe as _provider_online_probe,
)
from thomas.marketplace.channels._catalog import (
    resolve_provider_settings as _resolve_provider_settings,
)
from thomas.marketplace.channels._catalog import (
    save_channels_store as _save_channels_store,
)


def _channel_rows(config: AppConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in _CHANNEL_PROVIDER_NAMES:
        spec = _PROVIDER_SPECS[name]
        settings = _resolve_provider_settings(config, name)
        rows.append(
            {
                "name": name,
                "configured": _provider_configured(name, settings),
                "entrypoint": spec["entrypoint"],
                "notes": spec["notes"],
                "token_set": bool(settings.get("token")),
                "webhook_set": bool(settings.get("webhook")),
                "target_set": bool(settings.get("target")),
                "token_masked": _mask_secret(settings.get("token", "")),
                "webhook_masked": _mask_secret(settings.get("webhook", "")),
                "target_masked": _mask_secret(settings.get("target", "")),
                "env_keys": spec["env"],
            }
        )
    return rows


@click.group()
@click.pass_context
def channels(ctx: click.Context) -> None:
    """Channel integration status and helpers."""
    _ = ctx


@channels.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def channels_list(ctx: click.Context, as_json: bool) -> None:
    """List currently available channel integrations."""
    config: AppConfig = ctx.obj["config"]
    rows = _channel_rows(config)
    if as_json:
        click.echo(json.dumps({"channels": rows}, ensure_ascii=False, indent=2))
        return
    for row in rows:
        status = "configured" if row["configured"] else "not configured"
        click.echo(f"- {row['name']}: {status} (entrypoint: {row['entrypoint']})")


@channels.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def channels_status(ctx: click.Context, as_json: bool) -> None:
    """Show channel health summary."""
    config: AppConfig = ctx.obj["config"]
    rows = _channel_rows(config)
    data = {
        "channels_total": len(rows),
        "configured": int(sum(1 for row in rows if bool(row.get("configured")))),
        "details": rows,
    }
    if as_json:
        click.echo(json.dumps(data, ensure_ascii=False, indent=2))
        return
    click.echo(f"Configured channels: {data['configured']}/{data['channels_total']}")
    for row in data["details"]:
        state = "configured" if row["configured"] else "not configured"
        click.echo(f"- {row['name']}: {state} ({row['notes']})")


@channels.command("configure")
@click.option("--name", "name", required=True, type=click.Choice(list(_CHANNEL_PROVIDER_NAMES), case_sensitive=False))
@click.option("--token", "token", default="", help="Provider token (bot/api token).")
@click.option("--webhook", "webhook", default="", help="Provider webhook URL.")
@click.option("--target", "target", default="", help="Default chat/channel/phone-number target id.")
@click.option("--clear", "clear", is_flag=True, help="Clear saved provider settings.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def channels_configure(
    ctx: click.Context,
    name: str,
    token: str,
    webhook: str,
    target: str,
    clear: bool,
    as_json: bool,
) -> None:
    """Persist local channel provider settings (env vars still take precedence)."""
    config: AppConfig = ctx.obj["config"]
    provider = str(name).strip().lower()
    store = _load_channels_store(config)
    providers = store.get("providers")
    if not isinstance(providers, dict):
        providers = {}
        store["providers"] = providers

    row = providers.get(provider)
    if not isinstance(row, dict):
        row = {}
        providers[provider] = row

    if clear:
        row.clear()
        row["updated_at"] = _now_utc_iso()
    else:
        token_text = str(token or "").strip()
        webhook_text = str(webhook or "").strip()
        target_text = str(target or "").strip()
        if not any((token_text, webhook_text, target_text)):
            raise click.ClickException("Provide --token, --webhook, and/or --target, or use --clear.")
        if token_text:
            row["token"] = token_text
        if webhook_text:
            row["webhook"] = webhook_text
        if target_text:
            row["target"] = target_text
        row["updated_at"] = _now_utc_iso()

    _save_channels_store(config, store)
    resolved = _resolve_provider_settings(config, provider)
    payload = {
        "ok": True,
        "name": provider,
        "configured": _provider_configured(provider, resolved),
        "token_set": bool(resolved.get("token")),
        "webhook_set": bool(resolved.get("webhook")),
        "target_set": bool(resolved.get("target")),
        "token_masked": _mask_secret(resolved.get("token", "")),
        "webhook_masked": _mask_secret(resolved.get("webhook", "")),
        "target_masked": _mask_secret(resolved.get("target", "")),
        "env_precedence": True,
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Provider configured: {provider}")
    click.echo(f"- configured: {payload['configured']}")
    click.echo(f"- token_set: {payload['token_set']}")
    click.echo(f"- webhook_set: {payload['webhook_set']}")
    click.echo(f"- target_set: {payload['target_set']}")


@channels.command("test")
@click.option("--name", "name", required=True, type=click.Choice(list(_CHANNEL_PROVIDER_NAMES), case_sensitive=False))
@click.option("--online", "online", is_flag=True, help="Call provider health check to verify credentials.")
@click.option("--timeout", "timeout_s", default=5.0, show_default=True, type=float, help="Online probe timeout.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def channels_test(
    ctx: click.Context,
    name: str,
    online: bool,
    timeout_s: float,
    as_json: bool,
) -> None:
    """Validate channel configuration, optionally with online provider checks."""
    config: AppConfig = ctx.obj["config"]
    provider = str(name).strip().lower()
    resolved = _resolve_provider_settings(config, provider)
    checks = _local_validation_checks(provider, resolved)
    online_result: dict[str, Any] = {}
    if online:
        online_result = _provider_online_probe(provider, resolved, float(timeout_s))
        checks.append(
            {
                "check": "online_probe",
                "ok": bool(online_result.get("ok", False)),
                "detail": f"status={online_result.get('status', 0)}",
            }
        )

    ok = bool(all(bool(c.get("ok")) for c in checks))
    payload = {
        "ok": ok,
        "name": provider,
        "configured": _provider_configured(provider, resolved),
        "token_set": bool(resolved.get("token")),
        "webhook_set": bool(resolved.get("webhook")),
        "target_set": bool(resolved.get("target")),
        "checks": checks,
        "online": online_result if online else {},
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"{provider}: {'ok' if ok else 'failed'}")
    for row in checks:
        state = "ok" if bool(row.get("ok")) else "fail"
        click.echo(f"- {row.get('check')}: {state} ({row.get('detail')})")


register_pack_proxy_commands(
    channels,
    package="thomas.cli.commands.channel_ops",
    family_hint="channel",
)


app = channels


def register_channels_commands(cli: click.Group) -> None:
    if "channels" not in cli.commands:
        cli.add_command(channels)
