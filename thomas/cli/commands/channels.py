from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import click

from thomas.cli.pack_bridge import register_pack_proxy_commands
from thomas.core.config import AppConfig

_CHANNEL_PROVIDER_NAMES = ("telegram", "discord", "slack")


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _channels_config_path(config: AppConfig) -> Path:
    path = config.memory.root_path / ".thomas" / "channels.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_channels_store(config: AppConfig) -> dict[str, Any]:
    path = _channels_config_path(config)
    if not path.exists():
        return {"providers": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"providers": {}}
    if not isinstance(payload, dict):
        return {"providers": {}}
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        payload["providers"] = {}
    return payload


def _save_channels_store(config: AppConfig, payload: dict[str, Any]) -> None:
    path = _channels_config_path(config)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _mask_secret(value: str, *, keep: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= keep:
        return "*" * len(text)
    return ("*" * (len(text) - keep)) + text[-keep:]


def _provider_env_map(name: str) -> dict[str, str]:
    if name == "telegram":
        return {"token": "THOMAS_TELEGRAM_BOT_TOKEN"}
    if name == "discord":
        return {"token": "THOMAS_DISCORD_BOT_TOKEN", "webhook": "THOMAS_DISCORD_WEBHOOK_URL"}
    if name == "slack":
        return {"token": "THOMAS_SLACK_BOT_TOKEN", "webhook": "THOMAS_SLACK_WEBHOOK_URL"}
    return {}


def _resolve_provider_secrets(config: AppConfig, name: str) -> dict[str, str]:
    store = _load_channels_store(config)
    providers = store.get("providers", {})
    row = providers.get(name, {}) if isinstance(providers, dict) else {}
    if not isinstance(row, dict):
        row = {}
    env_map = _provider_env_map(name)

    def _resolve(field: str) -> str:
        env_key = env_map.get(field, "")
        env_val = str(os.environ.get(env_key) or "").strip() if env_key else ""
        if env_val:
            return env_val
        return str(row.get(field) or "").strip()

    return {"token": _resolve("token"), "webhook": _resolve("webhook")}


def _channel_rows(config: AppConfig) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for name in _CHANNEL_PROVIDER_NAMES:
        env_map = _provider_env_map(name)
        resolved = _resolve_provider_secrets(config, name)
        token = resolved.get("token", "")
        webhook = resolved.get("webhook", "")
        configured = bool(token or webhook)
        entrypoint = "thomas channels configure --name " + name
        if name == "telegram":
            entrypoint = "thomas telegram run"
        notes = {
            "telegram": "Set bot token via THOMAS_TELEGRAM_BOT_TOKEN or channels configure.",
            "discord": "Provide bot token and/or webhook URL.",
            "slack": "Provide bot token and/or webhook URL.",
        }.get(name, "")

        rows.append(
            {
                "name": name,
                "configured": configured,
                "entrypoint": entrypoint,
                "notes": notes,
                "token_set": bool(token),
                "webhook_set": bool(webhook),
                "token_masked": _mask_secret(token),
                "webhook_masked": _mask_secret(webhook),
                "env_keys": env_map,
            }
        )
    return rows


def _provider_online_probe(name: str, token: str, webhook: str, timeout_s: float) -> dict[str, Any]:
    def _json_get(url: str, headers: Optional[dict[str, str]] = None) -> dict[str, Any]:
        req = urllib.request.Request(url=url, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                status = int(getattr(resp, "status", 0) or 0)
                body = resp.read().decode("utf-8", errors="replace")
            payload: Any
            try:
                payload = json.loads(body) if body else {}
            except Exception:
                payload = {"raw": body[:300]}
            return {"ok": 200 <= status < 300, "status": status, "payload": payload}
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = ""
            payload: Any
            try:
                payload = json.loads(body) if body else {}
            except Exception:
                payload = {"raw": body[:300]}
            return {"ok": False, "status": int(getattr(e, "code", 0) or 0), "payload": payload}
        except Exception as e:
            return {"ok": False, "status": 0, "error": f"{type(e).__name__}: {e}"}

    if name == "telegram" and token:
        result = _json_get(f"https://api.telegram.org/bot{token}/getMe")
        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        provider_ok = bool(payload.get("ok") is True and isinstance(payload.get("result"), dict))
        result["provider_ok"] = provider_ok
        result["ok"] = bool(result.get("ok") and provider_ok)
        return result
    if name == "discord" and token:
        result = _json_get("https://discord.com/api/v10/users/@me", headers={"Authorization": f"Bot {token}"})
        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        provider_ok = bool(result.get("ok") and str(payload.get("id") or "").strip())
        result["provider_ok"] = provider_ok
        result["ok"] = provider_ok
        return result
    if name == "slack" and token:
        result = _json_get("https://slack.com/api/auth.test", headers={"Authorization": f"Bearer {token}"})
        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        provider_ok = bool(payload.get("ok") is True and str(payload.get("team_id") or "").strip())
        result["provider_ok"] = provider_ok
        result["ok"] = bool(result.get("ok") and provider_ok)
        return result
    if webhook:
        return _json_get(webhook)
    return {"ok": False, "status": 0, "error": "no token or webhook configured"}


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
@click.option("--clear", "clear", is_flag=True, help="Clear saved provider secrets.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def channels_configure(
    ctx: click.Context,
    name: str,
    token: str,
    webhook: str,
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
        row.pop("token", None)
        row.pop("webhook", None)
        row["updated_at"] = _now_utc_iso()
    else:
        token_text = str(token or "").strip()
        webhook_text = str(webhook or "").strip()
        if token_text:
            row["token"] = token_text
        if webhook_text:
            row["webhook"] = webhook_text
        if not token_text and not webhook_text:
            raise click.ClickException("Provide --token and/or --webhook, or use --clear.")
        row["updated_at"] = _now_utc_iso()

    _save_channels_store(config, store)
    resolved = _resolve_provider_secrets(config, provider)
    payload = {
        "ok": True,
        "name": provider,
        "token_set": bool(resolved.get("token")),
        "webhook_set": bool(resolved.get("webhook")),
        "token_masked": _mask_secret(resolved.get("token", "")),
        "webhook_masked": _mask_secret(resolved.get("webhook", "")),
        "env_precedence": True,
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Provider configured: {provider}")
    click.echo(f"- token_set: {payload['token_set']}")
    click.echo(f"- webhook_set: {payload['webhook_set']}")


@channels.command("test")
@click.option("--name", "name", required=True, type=click.Choice(list(_CHANNEL_PROVIDER_NAMES), case_sensitive=False))
@click.option("--online", "online", is_flag=True, help="Call provider API to verify token/webhook.")
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
    resolved = _resolve_provider_secrets(config, provider)
    token = str(resolved.get("token") or "").strip()
    webhook = str(resolved.get("webhook") or "").strip()
    configured = bool(token or webhook)

    checks: list[dict[str, Any]] = []
    checks.append({"check": "configured", "ok": configured, "detail": "token/webhook present" if configured else "not set"})
    if provider == "telegram" and token:
        checks.append({"check": "telegram_token_format", "ok": ":" in token, "detail": "must contain ':'"})
    if provider == "discord" and token:
        checks.append({"check": "discord_token_length", "ok": len(token) >= 20, "detail": "expected >= 20 chars"})
    if provider == "slack" and token:
        checks.append({"check": "slack_token_prefix", "ok": token.startswith("xox"), "detail": "expected token prefix xox*"})
    if webhook:
        checks.append({"check": "webhook_scheme", "ok": webhook.startswith("https://"), "detail": "expected https:// URL"})

    online_result: dict[str, Any] = {}
    if online:
        online_result = _provider_online_probe(provider, token, webhook, float(timeout_s))
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
        "configured": configured,
        "token_set": bool(token),
        "webhook_set": bool(webhook),
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


# Public alias used by tests and dynamic loaders.
app = channels


def register_channels_commands(cli: click.Group) -> None:
    if "channels" not in cli.commands:
        cli.add_command(channels)
