"""Executable OpenClaw-compatible alias commands for Thomas CLI."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import click

from thomas.cli.pack_bridge import register_pack_proxy_commands
from thomas.core.config import AppConfig, load_config


def _utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _state_dir(config: AppConfig) -> Path:
    path = config.memory.root_path / ".thomas" / "cli"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _tail_file(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    data = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(data[-max(1, int(lines)) :])


def _gateway_state_file(config: AppConfig) -> Path:
    return _state_dir(config) / "gateway_state.json"


def _gateway_log_file(config: AppConfig) -> Path:
    return _state_dir(config) / "gateway.log"


def _load_gateway_state(config: AppConfig) -> dict[str, Any]:
    payload = _read_json(_gateway_state_file(config), {})
    return payload if isinstance(payload, dict) else {}


def _load_devices(config: AppConfig) -> list[dict[str, Any]]:
    state = _load_gateway_state(config)
    rows = state.get("devices")
    if isinstance(rows, list):
        out: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, dict):
                out.append(dict(row))
        return out

    rows = state.get("paired_devices")
    if isinstance(rows, list):
        out = []
        for row in rows:
            if isinstance(row, dict):
                out.append(dict(row))
        return out

    return []


def _emit_json_or_text(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for key, value in payload.items():
        click.echo(f"{key}: {value}")


def _forward_main_cli(ctx: click.Context, args: list[str]) -> int:
    cmd = [sys.executable, "-m", "thomas.cli.main"]
    config_path = str((ctx.obj or {}).get("config_path") or "").strip()
    if config_path:
        cmd.extend(["-c", config_path])
    cmd.extend([str(a) for a in args])
    done = subprocess.run(cmd, check=False)
    return int(done.returncode or 0)


def _messages_store_path(config: AppConfig) -> Path:
    return _state_dir(config) / "messages.json"


def _mcp_registry_path(config: AppConfig) -> Path:
    return _state_dir(config) / "mcp_servers.json"


def _load_mcp_registry(config: AppConfig) -> list[dict[str, Any]]:
    payload = _read_json(_mcp_registry_path(config), {"servers": []})
    if not isinstance(payload, dict):
        return []
    rows = payload.get("servers")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(dict(row))
    return out


def _save_mcp_registry(config: AppConfig, rows: list[dict[str, Any]]) -> None:
    _write_json(_mcp_registry_path(config), {"servers": rows, "updated_at": _utc_iso()})


def _find_mcp_server(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    target = str(name or "").strip().lower()
    if not target:
        return None
    for row in rows:
        if str((row or {}).get("name") or "").strip().lower() == target:
            return row
    return None


def _token_store_path(config: AppConfig) -> Path:
    return _state_dir(config) / "tokens.json"


def _load_token_store(config: AppConfig) -> dict[str, Any]:
    payload = _read_json(_token_store_path(config), {})
    return payload if isinstance(payload, dict) else {}


def _save_token_store(config: AppConfig, payload: dict[str, Any]) -> None:
    _write_json(_token_store_path(config), payload)


def _mask_secret(value: str) -> str:
    token = str(value or "")
    if not token:
        return ""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def _load_messages(config: AppConfig) -> list[dict[str, Any]]:
    payload = _read_json(_messages_store_path(config), {"messages": []})
    if not isinstance(payload, dict):
        return []
    rows = payload.get("messages")
    if not isinstance(rows, list):
        return []
    out: list[dict[str, Any]] = []
    for row in rows:
        if isinstance(row, dict):
            out.append(dict(row))
    return out


def _save_messages(config: AppConfig, rows: list[dict[str, Any]]) -> None:
    _write_json(_messages_store_path(config), {"messages": rows, "updated_at": _utc_iso()})


def _provider_env_map(name: str) -> dict[str, str]:
    if name == "telegram":
        return {"token": "THOMAS_TELEGRAM_BOT_TOKEN"}
    if name == "discord":
        return {"token": "THOMAS_DISCORD_BOT_TOKEN", "webhook": "THOMAS_DISCORD_WEBHOOK_URL"}
    if name == "slack":
        return {"token": "THOMAS_SLACK_BOT_TOKEN", "webhook": "THOMAS_SLACK_WEBHOOK_URL"}
    return {}


def _resolve_provider_secrets(config: AppConfig, name: str) -> dict[str, str]:
    from thomas.cli.commands.channels import _load_channels_store  # local import to avoid circular startup cost

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


def _http_post_json(url: str, payload: dict[str, Any], *, headers: dict[str, str] | None = None, timeout_s: float = 8.0) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url=url, data=body, method="POST", headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=float(timeout_s)) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            raw = resp.read().decode("utf-8", errors="replace")
        parsed: Any
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {"raw": raw[:2000]}
        return {"ok": 200 <= status < 300, "status": status, "payload": parsed}
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")
        except Exception:
            body_text = ""
        parsed: Any
        try:
            parsed = json.loads(body_text) if body_text else {}
        except Exception:
            parsed = {"raw": body_text[:2000]}
        return {"ok": False, "status": int(getattr(e, "code", 0) or 0), "payload": parsed, "error": str(e)}
    except Exception as e:
        return {"ok": False, "status": 0, "payload": {}, "error": f"{type(e).__name__}: {e}"}


def _send_channel_message(
    config: AppConfig,
    *,
    channel: str,
    target: str,
    text: str,
    timeout_s: float = 8.0,
) -> dict[str, Any]:
    provider = str(channel or "").strip().lower()
    if provider == "local":
        return {"ok": True, "status": 0, "provider": provider, "delivery": "local_noop", "message_id": ""}

    secrets_row = _resolve_provider_secrets(config, provider)
    token = str(secrets_row.get("token") or "").strip()
    webhook = str(secrets_row.get("webhook") or "").strip()
    target_text = str(target or "").strip()
    body_text = str(text or "")

    if provider == "telegram":
        if not token:
            return {"ok": False, "status": 0, "provider": provider, "error": "telegram token missing"}
        if not target_text:
            return {"ok": False, "status": 0, "provider": provider, "error": "telegram target chat id required"}
        res = _http_post_json(
            f"https://api.telegram.org/bot{token}/sendMessage",
            {"chat_id": target_text, "text": body_text},
            timeout_s=timeout_s,
        )
        payload = res.get("payload") if isinstance(res.get("payload"), dict) else {}
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        provider_ok = bool(payload.get("ok") is True and result)
        return {
            "ok": bool(res.get("ok") and provider_ok),
            "status": int(res.get("status") or 0),
            "provider": provider,
            "message_id": str(result.get("message_id") or ""),
            "payload": payload,
            "error": str(res.get("error") or ""),
        }

    if provider == "discord":
        if webhook:
            url = webhook
            if "wait=true" not in url:
                joiner = "&" if "?" in url else "?"
                url = f"{url}{joiner}wait=true"
            res = _http_post_json(url, {"content": body_text}, timeout_s=timeout_s)
            payload = res.get("payload") if isinstance(res.get("payload"), dict) else {}
            provider_ok = bool(res.get("ok") and str(payload.get("id") or "").strip())
            return {
                "ok": provider_ok,
                "status": int(res.get("status") or 0),
                "provider": provider,
                "message_id": str(payload.get("id") or ""),
                "payload": payload,
                "error": str(res.get("error") or ""),
            }
        if token and target_text:
            res = _http_post_json(
                f"https://discord.com/api/v10/channels/{target_text}/messages",
                {"content": body_text},
                headers={"Authorization": f"Bot {token}"},
                timeout_s=timeout_s,
            )
            payload = res.get("payload") if isinstance(res.get("payload"), dict) else {}
            provider_ok = bool(res.get("ok") and str(payload.get("id") or "").strip())
            return {
                "ok": provider_ok,
                "status": int(res.get("status") or 0),
                "provider": provider,
                "message_id": str(payload.get("id") or ""),
                "payload": payload,
                "error": str(res.get("error") or ""),
            }
        return {"ok": False, "status": 0, "provider": provider, "error": "discord webhook or token+target required"}

    if provider == "slack":
        if webhook:
            res = _http_post_json(webhook, {"text": body_text}, timeout_s=timeout_s)
            payload = res.get("payload") if isinstance(res.get("payload"), dict) else {}
            provider_ok = bool(res.get("ok"))
            return {
                "ok": provider_ok,
                "status": int(res.get("status") or 0),
                "provider": provider,
                "message_id": str(payload.get("ts") or ""),
                "payload": payload,
                "error": str(res.get("error") or ""),
            }
        if token and target_text:
            res = _http_post_json(
                "https://slack.com/api/chat.postMessage",
                {"channel": target_text, "text": body_text},
                headers={"Authorization": f"Bearer {token}"},
                timeout_s=timeout_s,
            )
            payload = res.get("payload") if isinstance(res.get("payload"), dict) else {}
            provider_ok = bool(payload.get("ok") is True and str(payload.get("ts") or "").strip())
            return {
                "ok": bool(res.get("ok") and provider_ok),
                "status": int(res.get("status") or 0),
                "provider": provider,
                "message_id": str(payload.get("ts") or ""),
                "payload": payload,
                "error": str(res.get("error") or ""),
            }
        return {"ok": False, "status": 0, "provider": provider, "error": "slack webhook or token+target required"}

    return {"ok": False, "status": 0, "provider": provider, "error": f"unsupported channel: {provider}"}


@click.group(name="help", invoke_without_command=True)
@click.pass_context
def help_cmd(ctx: click.Context) -> None:
    """Display CLI help."""
    if ctx.invoked_subcommand is not None:
        return
    root = ctx.find_root()
    click.echo(root.command.get_help(root))


_HELP_TOPICS: tuple[str, ...] = (
    "acp",
    "agent",
    "agents",
    "approvals",
    "browser",
    "channels",
    "clawbot",
    "completion",
    "config",
    "configure",
    "cron",
    "daemon",
    "dashboard",
    "devices",
    "directory",
    "dns",
    "docs",
    "doctor",
    "gateway",
    "health",
    "help",
    "hooks",
    "logs",
    "memory",
    "message",
    "models",
    "node",
    "nodes",
    "onboard",
    "pairing",
    "plugins",
    "qr",
    "reset",
    "sandbox",
    "security",
    "sessions",
    "setup",
    "skills",
    "status",
    "system",
    "tui",
    "uninstall",
    "update",
    "webhooks",
)


def _help_topic(topic: str) -> click.Command:
    @click.command(name=topic)
    @click.pass_context
    def _cmd(ctx: click.Context) -> None:
        rc = _forward_main_cli(ctx, [topic, "--help"])
        if rc != 0:
            raise SystemExit(rc)

    return _cmd


for _topic_name in _HELP_TOPICS:
    help_cmd.add_command(_help_topic(_topic_name))


@click.command(name="logs")
@click.option("--lines", default=120, show_default=True, type=int, help="Number of tail lines.")
@click.pass_context
def logs_cmd(ctx: click.Context, lines: int) -> None:
    """Tail local gateway logs."""
    config: AppConfig = ctx.obj["config"]
    state = _load_gateway_state(config)
    log_file = Path(str(state.get("log_file") or _gateway_log_file(config)))
    if not log_file.exists():
        click.echo(f"(no gateway log file at {log_file})")
        return
    click.echo(_tail_file(log_file, lines=max(1, int(lines))))


@click.command(name="agent")
@click.argument("prompt")
@click.option("-m", "--model", "model_name", default="", help="Model profile (forwards to `thomas chat`).")
@click.option("--autonomy-level", type=click.IntRange(1, 4), default=3, show_default=True)
@click.option("--token-economy", type=click.Choice(["cheap", "optimal", "max"], case_sensitive=False), default="")
@click.pass_context
def agent_cmd(
    ctx: click.Context,
    prompt: str,
    model_name: str,
    autonomy_level: int,
    token_economy: str,
) -> None:
    """Run one agent turn (compat wrapper over `thomas chat`)."""
    args = ["chat", str(prompt)]
    if str(model_name or "").strip():
        args.extend(["--model", str(model_name).strip()])
    args.extend(["--autonomy-level", str(int(autonomy_level))])
    if str(token_economy or "").strip():
        args.extend(["--token-economy", str(token_economy).strip().lower()])
    rc = _forward_main_cli(ctx, args)
    if rc != 0:
        raise SystemExit(rc)


@click.group()
@click.pass_context
def browser(ctx: click.Context) -> None:
    """Browser helpers and smoke checks."""
    _ = ctx


@browser.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def browser_status(as_json: bool) -> None:
    """Show local browser tool availability."""
    chrome = shutil.which("chrome") or shutil.which("msedge") or shutil.which("chromium")
    playwright = shutil.which("playwright") or shutil.which("playwright-cli")
    payload = {
        "chrome_path": str(chrome or ""),
        "playwright_path": str(playwright or ""),
        "browser_ready": bool(chrome or playwright),
    }
    _emit_json_or_text(payload, as_json=as_json)


@browser.command("open")
@click.argument("url", required=False)
@click.option("--url", "url_opt", default="", help="URL to open (overrides positional URL).")
@click.option("--config", "config_path", default="", help="Optional browser config path.")
@click.option("--timeout", "timeout_s", default=None, type=float, help="Optional timeout in seconds.")
@click.option("--dry-run", is_flag=True, help="Validate request without opening a browser.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--json-schema", "as_schema", is_flag=True, help="Print JSON output schema and exit.")
def browser_open(
    url: Optional[str],
    url_opt: str,
    config_path: str,
    timeout_s: Optional[float],
    dry_run: bool,
    as_json: bool,
    as_schema: bool,
) -> None:
    """Open a URL via the Thomas browser integration surface (P026)."""
    from thomas.browser.p026_browser_integration_into_top_level_cli import (
        BrowserOpenRequest,
        open_url,
        result_json_schema,
    )

    if as_schema:
        click.echo(json.dumps(result_json_schema(), ensure_ascii=False, indent=2))
        return

    target = str(url_opt or "").strip() or (str(url or "").strip() if url else "")
    result = open_url(
        BrowserOpenRequest(
            url=(target or None),
            config_path=(str(config_path).strip() or None),
            timeout_s=timeout_s,
            dry_run=bool(dry_run),
        )
    )

    if as_json:
        click.echo(result.to_json())
    else:
        if result.ok:
            click.echo(f"{result.message}: {result.url}")
        elif result.error is not None:
            click.echo(f"{result.error.kind}: {result.error.message}", err=True)
        else:
            click.echo(f"error: {result.message}", err=True)

    if result.ok:
        return

    kind = str(getattr(result.error, "kind", "internal_error") or "internal_error")
    code_map = {
        "invalid_input": 2,
        "missing_config": 2,
        "external_failure": 1,
        "internal_error": 1,
    }
    raise SystemExit(int(code_map.get(kind, 1)))


@browser.command("smoke")
@click.option("--url", default="https://example.com", show_default=True)
@click.option("--expected-text", default="Example Domain", show_default=True)
@click.option("--timeout", "timeout_s", default=45.0, show_default=True, type=float)
@click.option("--max-actions", default=6, show_default=True, type=int)
@click.pass_context
def browser_smoke(
    ctx: click.Context,
    url: str,
    expected_text: str,
    timeout_s: float,
    max_actions: int,
) -> None:
    """Forward to live browser smoke workflow."""
    rc = _forward_main_cli(
        ctx,
        [
            "live-browser-smoke",
            "--url",
            str(url),
            "--expected-text",
            str(expected_text),
            "--timeout",
            str(float(timeout_s)),
            "--max-actions",
            str(int(max_actions)),
        ],
    )
    if rc != 0:
        raise SystemExit(rc)


@browser.group("workflows")
def browser_workflows() -> None:
    """Inspect production browser workflow profiles."""


@browser_workflows.command("list")
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def browser_workflows_list(limit: int, as_json: bool) -> None:
    from thomas.browser.workflow_runtime import list_profiles

    rows = list_profiles()
    rows = rows[: max(1, int(limit))]
    payload = {"count": len(rows), "profiles": rows}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Workflow profiles: {len(rows)}")
    for row in rows:
        click.echo(
            f"- {row.get('profile_id')} | category={row.get('category')} | "
            f"risk={row.get('risk_tier')} | timeout_ms={row.get('timeout_ms')}"
        )


@browser_workflows.command("show")
@click.argument("profile_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def browser_workflows_show(profile_id: str, as_json: bool) -> None:
    from thomas.browser.workflow_runtime import load_profile

    row = load_profile(str(profile_id))
    if row is None:
        raise click.ClickException(f"workflow profile not found: {profile_id}")
    if as_json:
        click.echo(json.dumps(row, ensure_ascii=False, indent=2))
        return
    click.echo(f"profile_id: {row.get('profile_id')}")
    click.echo(f"title: {row.get('title')}")
    click.echo(f"category: {row.get('category')}")
    click.echo(f"risk_tier: {row.get('risk_tier')}")
    click.echo(f"required_signals: {', '.join(str(x) for x in (row.get('required_signals') or []))}")


@browser.group("workflow-cases")
def browser_workflow_cases() -> None:
    """Inspect and validate production browser workflow corpus cases."""


@browser_workflow_cases.command("list")
@click.option("--limit", default=20, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def browser_workflow_cases_list(limit: int, as_json: bool) -> None:
    from thomas.browser.workflow_runtime import list_case_files

    rows = [p.name for p in list_case_files(limit=max(1, int(limit)))]
    payload = {"count": len(rows), "cases": rows}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Workflow cases: {len(rows)}")
    for row in rows:
        click.echo(f"- {row}")


@browser_workflow_cases.command("show")
@click.argument("case_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def browser_workflow_cases_show(case_id: str, as_json: bool) -> None:
    from thomas.browser.workflow_runtime import load_case

    payload = load_case(str(case_id))
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"workflow_id: {payload.get('workflow_id')}")
    click.echo(f"title: {payload.get('title')}")
    click.echo(f"category: {payload.get('category')}")
    click.echo(f"steps: {len(payload.get('steps') or [])}")
    click.echo(f"assertions: {len(payload.get('assertions') or [])}")


@browser_workflow_cases.command("validate")
@click.argument("case_id", required=False, default="")
@click.option("--limit", default=0, type=int, show_default=True, help="When no case_id is given, validate first N cases (0 = all).")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def browser_workflow_cases_validate(case_id: str, limit: int, as_json: bool) -> None:
    from thomas.browser.workflow_runtime import load_case, validate_case_payload, validate_corpus

    target = str(case_id or "").strip()
    if target:
        payload = load_case(target)
        ok, errors = validate_case_payload(payload)
        out = {
            "target": target,
            "ok": bool(ok),
            "errors": errors,
            "workflow_id": payload.get("workflow_id"),
        }
        if as_json:
            click.echo(json.dumps(out, ensure_ascii=False, indent=2))
        else:
            click.echo(f"target: {target}")
            click.echo(f"ok: {bool(ok)}")
            if errors:
                for row in errors[:20]:
                    click.echo(f"- {row}")
        if not ok:
            raise SystemExit(1)
        return

    summary = validate_corpus(limit=(None if int(limit) <= 0 else int(limit)))
    if as_json:
        click.echo(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        click.echo(f"corpus_root: {summary.get('root')}")
        click.echo(f"total: {summary.get('total')}")
        click.echo(f"valid: {summary.get('valid')}")
        click.echo(f"invalid: {summary.get('invalid')}")
    if int(summary.get("invalid") or 0) > 0:
        raise SystemExit(1)


register_pack_proxy_commands(
    browser,
    package="thomas.cli.commands.browser",
    family_hint="browser",
)


@click.group(name="node", invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def node(ctx: click.Context, as_json: bool) -> None:
    """Node host lifecycle helpers."""
    if ctx.invoked_subcommand is not None:
        return
    available = sorted(ctx.command.commands.keys()) if isinstance(ctx.command, click.Group) else []
    payload = {
        "command": "node",
        "compatibility": "mapped",
        "equivalents": ["gateway", "nodes"],
        "subcommands": available,
        "note": "Node lifecycle is available via `node install`; runtime actions are under `nodes`.",
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(ctx.get_help())


@node.command("install")
@click.option("--host", default=None, help="Gateway host.")
@click.option("--port", type=int, default=None, help="Gateway port.")
@click.option("--tls/--no-tls", default=False, show_default=True, help="Use TLS for gateway connection.")
@click.option("--tls-fingerprint", default=None, help="Expected gateway TLS certificate fingerprint (sha256).")
@click.option("--node-id", default=None, help="Optional explicit node id.")
@click.option("--display-name", default=None, help="Optional human-readable node name.")
@click.option("--runtime", default="python", show_default=True, help="Node runtime.")
@click.option("--force", is_flag=True, help="Overwrite existing install metadata.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def node_install(
    host: Optional[str],
    port: Optional[int],
    tls: bool,
    tls_fingerprint: Optional[str],
    node_id: Optional[str],
    display_name: Optional[str],
    runtime: str,
    force: bool,
    as_json: bool,
) -> None:
    """Install local node host config/service files (P031)."""
    from thomas.nodes.p031_node_command_install import (
        NodeInstallError,
        NodeInstallRequest,
        install_node_command,
        render_install_error_json,
        render_install_result_human,
    )

    req = NodeInstallRequest(
        host=host,
        port=port,
        tls=bool(tls),
        tls_fingerprint=tls_fingerprint,
        node_id=node_id,
        display_name=display_name,
        runtime=str(runtime or "python"),
        force=bool(force),
    )
    try:
        result = install_node_command(req)
    except NodeInstallError as e:
        if as_json:
            click.echo(json.dumps(render_install_error_json(e), ensure_ascii=False, indent=2))
        else:
            click.echo(f"ERROR[{e.code}]: {e}", err=True)
        raise SystemExit(1)

    if as_json:
        click.echo(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        click.echo(render_install_result_human(result))


register_pack_proxy_commands(
    node,
    package="thomas.cli.commands.nodes",
    family_hint="node",
    include_prefix="node_",
)


@click.group(name="nodes", invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def nodes(ctx: click.Context, as_json: bool) -> None:
    """Remote node action helpers."""
    if ctx.invoked_subcommand is not None:
        return
    available = sorted(ctx.command.commands.keys()) if isinstance(ctx.command, click.Group) else []
    payload = {
        "command": "nodes",
        "compatibility": "mapped",
        "equivalents": ["devices"],
        "subcommands": available,
        "note": "Use `nodes location` and `nodes pending-approvals`; pair/manage local agents under `devices`.",
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(ctx.get_help())


def _resolve_node_registry() -> dict[str, str]:
    inline = str(os.environ.get("THOMAS_NODE_REGISTRY") or "").strip()
    if inline:
        try:
            payload = json.loads(inline)
            if isinstance(payload, dict):
                out: dict[str, str] = {}
                for key, val in payload.items():
                    if isinstance(val, str) and val.strip():
                        out[str(key)] = val.strip()
                    elif isinstance(val, dict):
                        url = str(val.get("url") or "").strip()
                        if url:
                            out[str(key)] = url
                if out:
                    return out
        except Exception:
            pass

    candidates: list[Path] = []
    env_file = str(os.environ.get("THOMAS_NODE_REGISTRY_FILE") or "").strip()
    if env_file:
        candidates.append(Path(env_file))
    candidates.append(Path.home() / ".thomas" / "nodes.json")

    for path in candidates:
        try:
            if not path.exists() or not path.is_file():
                continue
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                out: dict[str, str] = {}
                for key, val in payload.items():
                    if isinstance(val, str) and val.strip():
                        out[str(key)] = val.strip()
                    elif isinstance(val, dict):
                        url = str(val.get("url") or "").strip()
                        if url:
                            out[str(key)] = url
                if out:
                    return out
        except Exception:
            continue
    return {}


def _resolve_node_endpoint(node_ref: str) -> str:
    ref = str(node_ref or "").strip()
    if not ref:
        raise RuntimeError("node is required")
    if ref.startswith("http://") or ref.startswith("https://"):
        return ref.rstrip("/")
    registry = _resolve_node_registry()
    endpoint = str(registry.get(ref) or "").strip()
    if not endpoint:
        raise RuntimeError(f"Unknown node '{ref}' (set THOMAS_NODE_REGISTRY or THOMAS_NODE_REGISTRY_FILE)")
    if not (endpoint.startswith("http://") or endpoint.startswith("https://")):
        raise RuntimeError(f"Invalid endpoint for node '{ref}': {endpoint}")
    return endpoint.rstrip("/")


def _node_auth_headers() -> dict[str, str]:
    token = str(os.environ.get("THOMAS_NODE_AUTH_TOKEN") or "").strip()
    if not token:
        return {}
    header = str(os.environ.get("THOMAS_NODE_AUTH_HEADER") or "Authorization").strip() or "Authorization"
    scheme = str(os.environ.get("THOMAS_NODE_AUTH_SCHEME") or "Bearer").strip()
    value = f"{scheme} {token}".strip() if scheme else token
    return {header: value}


def _invoke_node_action_http(
    *,
    node: str,
    command: str,
    params: dict[str, Any],
    timeout_ms: Optional[int],
    idempotency_key: Optional[str],
) -> dict[str, Any]:
    endpoint = _resolve_node_endpoint(node)
    action_path = str(os.environ.get("THOMAS_NODE_INVOKE_PATH") or "/actions/invoke").strip() or "/actions/invoke"
    if not action_path.startswith("/"):
        action_path = "/" + action_path
    url = endpoint + action_path

    payload: dict[str, Any] = {"action": str(command), "payload": dict(params or {})}
    if str(idempotency_key or "").strip():
        payload["request_id"] = str(idempotency_key).strip()

    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    headers.update(_node_auth_headers())
    req = urllib.request.Request(url=url, data=body, method="POST", headers=headers)

    timeout_s = max(0.1, float((timeout_ms or 30000) / 1000.0))
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        if not raw.strip():
            return {"ok": True}
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
        return {"ok": True, "result": parsed}


@nodes.command("location")
@click.option("--node", "node_id", required=True, help="Node id or explicit node URL.")
@click.option(
    "--accuracy",
    default="balanced",
    show_default=True,
    type=click.Choice(["coarse", "balanced", "precise"], case_sensitive=False),
)
@click.option(
    "--max-age",
    "max_age_ms",
    default=15000,
    show_default=True,
    type=int,
    help="Maximum acceptable cached location age in milliseconds.",
)
@click.option(
    "--location-timeout",
    "location_timeout_ms",
    default=10000,
    show_default=True,
    type=int,
    help="Device-side location timeout in milliseconds.",
)
@click.option("--invoke-timeout", "invoke_timeout_ms", default=None, type=int, help="Gateway invoke timeout in milliseconds.")
@click.option("--idempotency-key", default="", help="Optional idempotency key for node invoke.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def nodes_location(
    node_id: str,
    accuracy: str,
    max_age_ms: int,
    location_timeout_ms: int,
    invoke_timeout_ms: Optional[int],
    idempotency_key: str,
    as_json: bool,
) -> None:
    """Get a node's location using the P044 action contract."""
    from thomas.nodes.p044_nodes_location_action import (
        NodesLocationActionError,
        NodesLocationActionInput,
        get_node_location,
    )

    class _Invoker:
        def node_invoke(
            self,
            node: str,
            command: str,
            params: Optional[dict[str, Any]] = None,
            *,
            timeout_ms: Optional[int] = None,
            idempotency_key: Optional[str] = None,
        ) -> dict[str, Any]:
            return _invoke_node_action_http(
                node=node,
                command=command,
                params=dict(params or {}),
                timeout_ms=timeout_ms,
                idempotency_key=idempotency_key,
            )

    try:
        result = asyncio.run(
            get_node_location(
                NodesLocationActionInput(
                    node=str(node_id),
                    accuracy=str(accuracy).strip().lower(),
                    max_age_ms=int(max_age_ms),
                    location_timeout_ms=int(location_timeout_ms),
                    invoke_timeout_ms=invoke_timeout_ms,
                    idempotency_key=(str(idempotency_key).strip() or None),
                ),
                invoker=_Invoker(),
            )
        )
    except NodesLocationActionError as e:
        payload = {"ok": False, "error": e.to_dict()}
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            click.echo(f"ERROR[{e.code}]: {e.message}", err=True)
        raise SystemExit(1)
    except Exception as e:
        payload = {
            "ok": False,
            "error": {
                "code": "internal_error",
                "message": "Unhandled nodes location error",
                "details": {"exception": type(e).__name__},
            },
        }
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            click.echo(f"ERROR[internal_error]: {type(e).__name__}", err=True)
        raise SystemExit(1)

    payload = {"ok": True, "result": result.to_dict()}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    parts = [f"{result.lat:.6f},{result.lon:.6f}"]
    if result.accuracy_meters is not None:
        parts.append(f"+-{result.accuracy_meters:g}m")
    if result.timestamp:
        parts.append(f"@ {result.timestamp}")
    if result.source:
        parts.append(f"({result.source})")
    click.echo(" ".join(parts))


@nodes.command("pending-approvals")
@click.option("--state-dir", default="", help="Override Thomas state directory.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def nodes_pending_approvals(state_dir: str, as_json: bool) -> None:
    """List pending node approval requests (P046)."""
    from thomas.nodes.p046_nodes_pending_approvals import (
        ERROR_CONFIG_MISSING,
        ERROR_INVALID_INPUT,
        NodesPendingApprovalsError,
        NodesPendingApprovalsInput,
        nodes_pending_approvals as _nodes_pending_approvals,
    )

    try:
        result = _nodes_pending_approvals(
            NodesPendingApprovalsInput(state_dir=(str(state_dir).strip() or None))
        )
        payload = {"ok": True, **result.to_dict()}
    except NodesPendingApprovalsError as exc:
        payload = {
            "ok": False,
            "error": {
                "code": getattr(exc, "code", "UNKNOWN"),
                "message": str(exc),
                "details": getattr(exc, "details", {}),
            },
        }
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            click.echo(f"ERROR {payload['error']['code']}: {payload['error']['message']}", err=True)
        if str(getattr(exc, "code", "")) in (ERROR_INVALID_INPUT, ERROR_CONFIG_MISSING):
            raise SystemExit(2)
        raise SystemExit(3)

    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    approvals = payload.get("approvals") or []
    if not approvals:
        click.echo("No nodes are pending approval.")
        return

    headers = ["node_id", "requested_at", "requested_by", "reason"]
    rows = [[str((row or {}).get(h) or "") for h in headers] for row in approvals]
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))

    def _fmt(values: list[str]) -> str:
        return "  ".join(val.ljust(widths[idx]) for idx, val in enumerate(values))

    click.echo(_fmt(headers))
    click.echo(_fmt(["-" * w for w in widths]))
    for row in rows:
        click.echo(_fmt(row))


register_pack_proxy_commands(
    nodes,
    package="thomas.cli.commands.nodes",
    family_hint="nodes",
    include_prefix="nodes_",
)


@click.group()
@click.pass_context
def message(ctx: click.Context) -> None:
    """Local message queue + delivery tracking."""
    _ = ctx


@message.command("send")
@click.option("--channel", default="local", show_default=True, type=click.Choice(["local", "telegram", "discord", "slack"], case_sensitive=False))
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


def _compat_emit(command: str, action: str, note: str, target: str, as_json: bool, ctx: click.Context) -> None:
    payload: dict[str, Any] = {
        "command": command,
        "action": action,
        "note": note,
        "target": target,
        "timestamp_utc": _utc_iso(),
    }
    if command == "directory" and action == "list":
        config: AppConfig = ctx.obj["config"]
        payload["count"] = len(_load_devices(config))
    if command == "memory" and action == "status":
        config = ctx.obj["config"]
        root = config.memory.root_path / ".thomas"
        payload["root"] = str(root)
        payload["chat_files"] = len(list((root / "chats").glob("*.json"))) if (root / "chats").exists() else 0
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"{command} {action}: {note}")
    if target:
        click.echo(f"- target: {target}")
    if "count" in payload:
        click.echo(f"- count: {payload['count']}")


def _compat_action(command: str, action: str, note: str) -> click.Command:
    @click.command(name=action)
    @click.argument("target", required=False, default="")
    @click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
    @click.pass_context
    def _cmd(ctx: click.Context, target: str, as_json: bool) -> None:
        _compat_emit(command, action, note, str(target or "").strip(), as_json, ctx)

    return _cmd


def _compat_group(name: str, actions: list[tuple[str, str]]) -> click.Group:
    @click.group(name=name)
    @click.pass_context
    def _group(ctx: click.Context) -> None:
        _ = ctx

    for action, note in actions:
        _group.add_command(_compat_action(name, action, note))
    return _group


def _forward_passthrough(ctx: click.Context, base_args: list[str], extra_args: tuple[Any, ...]) -> None:
    args = [str(x) for x in base_args]
    args.extend(str(x) for x in extra_args)
    rc = _forward_main_cli(ctx, args)
    if rc != 0:
        raise SystemExit(rc)


@click.group(name="acp")
@click.pass_context
def acp(ctx: click.Context) -> None:
    """ACP bridge compatibility workflows."""
    _ = ctx


@acp.command(
    "client",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def acp_client(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Open an interactive client flow (maps to repl/chat)."""
    extras = [str(x) for x in args]
    if extras:
        _forward_passthrough(ctx, ["chat", " ".join(extras)], ())
        return
    _forward_passthrough(ctx, ["repl"], ())


@acp.command(
    "bridge",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def acp_bridge(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Start ACP bridge compatibility mode (maps to gateway run)."""
    _forward_passthrough(ctx, ["gateway", "run"], args)


@click.group(name="clawbot")
@click.pass_context
def clawbot(ctx: click.Context) -> None:
    """Legacy clawbot compatibility commands."""
    _ = ctx


@clawbot.command(
    "chat",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def clawbot_chat(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Run clawbot chat compatibility mode (maps to chat)."""
    prompt = " ".join(str(x) for x in args).strip()
    if not prompt:
        raise click.ClickException("clawbot chat requires a prompt.")
    _forward_passthrough(ctx, ["chat", prompt], ())


@clawbot.command(
    "qr",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def clawbot_qr(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Generate pairing QR compatibility flow (maps to qr)."""
    _forward_passthrough(ctx, ["qr"], args)


@click.group(name="daemon")
@click.pass_context
def daemon(ctx: click.Context) -> None:
    """Gateway daemon lifecycle compatibility commands."""
    _ = ctx


@daemon.command("install", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_install(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "install"], args)


@daemon.command("restart", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_restart(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "restart"], args)


@daemon.command("start", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_start(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "start"], args)


@daemon.command("status", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_status(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "status"], args)


@daemon.command("stop", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_stop(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "stop"], args)


@daemon.command("uninstall", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_uninstall(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "uninstall"], args)


@daemon.command("logs", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def daemon_logs(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "logs"], args)


@click.group(name="dns")
@click.pass_context
def dns(ctx: click.Context) -> None:
    """DNS/discovery compatibility commands."""
    _ = ctx


@dns.command("setup", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def dns_setup(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "discover"], args)


@dns.command("status", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def dns_status(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["gateway", "status"], args)


@click.group(name="hooks")
@click.pass_context
def hooks(ctx: click.Context) -> None:
    """Hook compatibility commands backed by plugin controls."""
    _ = ctx


@hooks.command("check", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_check(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "doctor"], args)


@hooks.command("disable", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_disable(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "disable"], args)


@hooks.command("enable", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_enable(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "enable"], args)


@hooks.command("info", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_info(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "info"], args)


@hooks.command("install", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_install(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "install"], args)


@hooks.command("list", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_list(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "list"], args)


@hooks.command("update", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def hooks_update(ctx: click.Context, args: tuple[Any, ...]) -> None:
    _forward_passthrough(ctx, ["plugins", "update-planner"], args)
memory = _compat_group(
    "memory",
    [
        ("status", "Memory store is available."),
        ("list", "List memory snapshots."),
        ("search", "Search memory snapshots."),
        ("compact", "Compaction hook is wired."),
    ],
)
system = _compat_group(
    "system",
    [
        ("status", "System command family is active."),
        ("health", "Health endpoints are reachable through gateway commands."),
        ("doctor", "Use `doctor` for full diagnostics."),
        ("env", "Environment variable presence map."),
    ],
)
approvals = _compat_group(
    "approvals",
    [
        ("list", "Approval queue is exposed through nodes pending-approvals."),
        ("status", "Approval workflow is wired."),
        ("approve", "Use node action commands for execution-level approvals."),
        ("reject", "Use node action commands for execution-level rejections."),
    ],
)
directory = _compat_group(
    "directory",
    [
        ("list", "Directory view is backed by paired devices."),
        ("add", "Use devices pair for durable entries."),
        ("remove", "Use devices revoke/remove flows for durable records."),
    ],
)
pairing = _compat_group(
    "pairing",
    [
        ("start", "Use devices pair --name <name> for full pairing."),
        ("status", "Pairing support is active through devices commands."),
        ("reset", "Revoke old tokens and re-run devices pair."),
    ],
)
skills = _compat_group(
    "skills",
    [
        ("list", "Skill docs are available through local AGENTS/skill files."),
        ("show", "Skill resolution is environment-managed."),
        ("sync", "Skill sync is a no-op in compatibility mode."),
    ],
)
security = _compat_group(
    "security",
    [
        ("status", "Security posture is enforced by guardrail scripts."),
        ("scan", "Use dedicated security skills/scripts for deep analysis."),
    ],
)
update = _compat_group(
    "update",
    [
        ("check", "Use doppelganger + release hygiene checks for full verification."),
        ("apply", "Use doppelganger rollout commands for real apply operations."),
    ],
)


@click.command(name="completion")
@click.argument("shell", required=False)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def completion_cmd(shell: Optional[str], as_json: bool) -> None:
    """Print shell-completion bootstrap instructions for Thomas CLI."""
    requested = str(shell or "").strip().lower()
    if requested in {"pwsh", "powershell"}:
        requested = "powershell"
    supported = {"bash", "zsh", "fish", "powershell"}
    if requested and requested not in supported:
        raise click.ClickException(f"Unsupported shell '{requested}'. Choose one of: {', '.join(sorted(supported))}.")

    default_shell = "powershell" if os.name == "nt" else "bash"
    target_shell = requested or default_shell
    mode = {
        "bash": "bash_source",
        "zsh": "zsh_source",
        "fish": "fish_source",
        "powershell": "powershell_source",
    }[target_shell]
    if target_shell == "powershell":
        command = f"$env:_THOMAS_COMPLETE='{mode}'; python -m thomas"
    else:
        command = f"_THOMAS_COMPLETE={mode} python -m thomas"

    payload = {
        "command": "completion",
        "shell": target_shell,
        "env_var": "_THOMAS_COMPLETE",
        "mode": mode,
        "generate_command": command,
        "note": "Run the command and append output to your shell profile to enable tab completion.",
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    click.echo(f"shell: {target_shell}")
    click.echo("generate completion script:")
    click.echo(f"  {command}")
    click.echo("note: append the output to your shell profile to persist completion.")


@click.command(name="qr", context_settings={"ignore_unknown_options": True, "allow_extra_args": True})
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def qr_cmd(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Generate a device pairing token (compat wrapper over `devices pair`)."""
    extras = [str(x) for x in args]
    has_name = any(item == "--name" or item.startswith("--name=") for item in extras)
    if not has_name:
        extras.extend(["--name", f"qr-{int(time.time())}"])
    _forward_passthrough(ctx, ["devices", "pair"], tuple(extras))


@click.command(
    name="plugin",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def plugin_cmd(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Claude-style singular plugin alias (maps to `plugins ...`)."""
    extras = [str(x) for x in args]
    if not extras:
        extras = ["--help"]
    _forward_passthrough(ctx, ["plugins"], tuple(extras))


@click.group(name="mcp", invoke_without_command=True)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def mcp(ctx: click.Context, as_json: bool) -> None:
    """Manage MCP server registry entries for compatibility workflows."""
    if ctx.invoked_subcommand is not None:
        return
    config: AppConfig = ctx.obj["config"]
    rows = _load_mcp_registry(config)
    payload = {
        "count": len(rows),
        "servers": rows,
        "state_file": str(_mcp_registry_path(config)),
        "note": "Use `mcp serve` to run the local Thomas gateway host.",
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"MCP servers: {len(rows)}")
    for row in rows:
        click.echo(
            f"- {row.get('name')} | transport={row.get('transport')} | "
            f"enabled={bool(row.get('enabled', True))}"
        )
    click.echo(f"State file: {payload['state_file']}")


@mcp.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def mcp_list(ctx: click.Context, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    rows = _load_mcp_registry(config)
    payload = {"count": len(rows), "servers": rows}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"MCP servers: {len(rows)}")
    for row in rows:
        click.echo(
            f"- {row.get('name')} | transport={row.get('transport')} | "
            f"enabled={bool(row.get('enabled', True))}"
        )


@mcp.command("add")
@click.argument("name")
@click.option(
    "--transport",
    type=click.Choice(["stdio", "sse", "http"], case_sensitive=False),
    default="stdio",
    show_default=True,
)
@click.option("--command", "command_value", default="", help="Executable for stdio transport.")
@click.option("--arg", "command_args", multiple=True, help="Repeatable arg for --command.")
@click.option("--url", default="", help="Server URL for sse/http transport.")
@click.option("--env", "env_pairs", multiple=True, help="Environment pair KEY=VALUE (repeatable).")
@click.option("--enable/--disable", default=True, show_default=True, help="Initial enabled state.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def mcp_add(
    ctx: click.Context,
    name: str,
    transport: str,
    command_value: str,
    command_args: tuple[str, ...],
    url: str,
    env_pairs: tuple[str, ...],
    enable: bool,
    as_json: bool,
) -> None:
    config: AppConfig = ctx.obj["config"]
    target = str(name or "").strip()
    if not target:
        raise click.ClickException("name is required")

    chosen_transport = str(transport or "stdio").strip().lower()
    command_text = str(command_value or "").strip()
    url_text = str(url or "").strip()
    if chosen_transport == "stdio" and not command_text and url_text:
        chosen_transport = "sse"
    if chosen_transport == "stdio" and not command_text:
        raise click.ClickException("--command is required for stdio transport.")
    if chosen_transport in {"sse", "http"} and not url_text:
        raise click.ClickException("--url is required for sse/http transport.")

    env_map: dict[str, str] = {}
    for pair in env_pairs:
        key, sep, value = str(pair).partition("=")
        if not sep or not key.strip():
            raise click.ClickException(f"Invalid --env entry: {pair!r}. Use KEY=VALUE.")
        env_map[key.strip()] = value

    rows = _load_mcp_registry(config)
    now = _utc_iso()
    row = _find_mcp_server(rows, target)
    payload_row = {
        "name": target,
        "transport": chosen_transport,
        "command": command_text,
        "args": [str(x) for x in command_args],
        "url": url_text,
        "env": env_map,
        "enabled": bool(enable),
        "updated_at": now,
    }
    if row is None:
        payload_row["created_at"] = now
        rows.append(payload_row)
        stored = payload_row
    else:
        row.update(payload_row)
        row.setdefault("created_at", now)
        stored = row
    _save_mcp_registry(config, rows)
    payload = {"ok": True, "server": stored}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(
        f"Saved MCP server: {stored.get('name')} "
        f"(transport={stored.get('transport')}, enabled={bool(stored.get('enabled', True))})"
    )


@mcp.command("get")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def mcp_get(ctx: click.Context, name: str, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    rows = _load_mcp_registry(config)
    row = _find_mcp_server(rows, name)
    if row is None:
        raise click.ClickException(f"MCP server not found: {name}")
    if as_json:
        click.echo(json.dumps(row, ensure_ascii=False, indent=2))
        return
    for key in ("name", "transport", "command", "args", "url", "enabled", "created_at", "updated_at"):
        click.echo(f"{key}: {row.get(key)}")


@mcp.command("remove")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def mcp_remove(ctx: click.Context, name: str, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    rows = _load_mcp_registry(config)
    target = str(name or "").strip().lower()
    kept = [row for row in rows if str((row or {}).get("name") or "").strip().lower() != target]
    removed = len(kept) != len(rows)
    if removed:
        _save_mcp_registry(config, kept)
    payload = {"ok": removed, "name": str(name or "").strip()}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if removed:
        click.echo(f"Removed MCP server: {name}")
    else:
        click.echo(f"MCP server not found: {name}")
        raise SystemExit(1)


@mcp.command(
    "serve",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def mcp_serve(ctx: click.Context, args: tuple[Any, ...]) -> None:
    """Compatibility alias for running the Thomas gateway host."""
    _forward_passthrough(ctx, ["gateway", "run"], args)


@click.command(
    name="install",
    context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
)
@click.option("--compat-json", "compat_json", is_flag=True, help="Print compatibility mapping JSON and exit.")
@click.argument("args", nargs=-1, type=click.UNPROCESSED)
@click.pass_context
def install_cmd(ctx: click.Context, compat_json: bool, args: tuple[Any, ...]) -> None:
    """Claude-style install alias that maps to Thomas setup/plugin/gateway installs."""
    payload = {
        "command": "install",
        "compatibility": "mapped",
        "equivalents": ["setup", "plugins install", "gateway install"],
        "note": "Use `install plugins ...` or `install gateway ...`; bare `install` runs setup diagnostics.",
    }
    if compat_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    extras = [str(x) for x in args]
    if not extras:
        _forward_passthrough(ctx, ["setup"], ())
        return

    topic = str(extras[0] or "").strip().lower()
    tail = tuple(extras[1:])
    if topic in {"plugin", "plugins"}:
        _forward_passthrough(ctx, ["plugins", "install"], tail)
        return
    if topic in {"gateway", "daemon", "service"}:
        _forward_passthrough(ctx, ["gateway", "install"], tail)
        return

    raise click.ClickException(
        "Unsupported install target. Use one of: `install`, `install plugins ...`, `install gateway ...`."
    )


@click.command(name="setup-token")
@click.option(
    "--provider",
    default="anthropic",
    show_default=True,
    type=click.Choice(["anthropic", "openai", "gateway", "codex"], case_sensitive=False),
)
@click.option("--token", default="", help="Token value. If omitted, reads env or prompts securely.")
@click.option("--print-env", is_flag=True, help="Print shell snippet to set the environment variable.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def setup_token_cmd(
    ctx: click.Context,
    provider: str,
    token: str,
    print_env: bool,
    as_json: bool,
) -> None:
    """Set up provider token metadata for compatibility workflows."""
    config: AppConfig = ctx.obj["config"]
    provider_name = str(provider or "").strip().lower()
    env_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "openai": "OPENAI_API_KEY",
        "gateway": "THOMAS_GATEWAY_API_KEY",
        "codex": "OPENAI_API_KEY",
    }
    env_key = env_map[provider_name]

    resolved = str(token or os.environ.get(env_key) or "").strip()
    if not resolved:
        resolved = str(
            click.prompt(
                f"Enter token for {provider_name} ({env_key})",
                default="",
                show_default=False,
                hide_input=True,
            )
        ).strip()
    if not resolved:
        raise click.ClickException("Token is required.")

    os.environ[env_key] = resolved
    store = _load_token_store(config)
    rows = store.get("tokens")
    if not isinstance(rows, dict):
        rows = {}
    rows[provider_name] = {
        "provider": provider_name,
        "env_key": env_key,
        "token_masked": _mask_secret(resolved),
        "token_sha256": hashlib.sha256(resolved.encode("utf-8")).hexdigest(),
        "updated_at": _utc_iso(),
    }
    store["tokens"] = rows
    store["updated_at"] = _utc_iso()
    _save_token_store(config, store)

    env_command = (
        f"$env:{env_key}='<paste-token>'"
        if os.name == "nt"
        else f"export {env_key}='<paste-token>'"
    )
    payload = {
        "ok": True,
        "provider": provider_name,
        "env_key": env_key,
        "token_masked": _mask_secret(resolved),
        "state_file": str(_token_store_path(config)),
        "env_command": env_command if print_env else "",
        "note": (
            "codex also supports browser login via `thomas codex login`."
            if provider_name == "codex"
            else "Token is set for this process; persist in your shell profile for future sessions."
        ),
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Token configured for {provider_name} ({env_key}).")
    click.echo(f"State file: {payload['state_file']}")
    if print_env:
        click.echo(f"Shell snippet: {env_command}")


def _compat_payload(name: str, equivalents: list[str], note: str) -> dict[str, Any]:
    return {
        "command": name,
        "compatibility": "partial",
        "equivalents": equivalents,
        "note": note,
    }


def _compat_command(
    name: str,
    *,
    equivalents: list[str],
    note: str,
    forward_to: list[str] | None = None,
) -> click.Command:
    if forward_to:
        @click.command(
            name=name,
            context_settings={"ignore_unknown_options": True, "allow_extra_args": True},
        )
        @click.option("--compat-json", "compat_json", is_flag=True, help="Print compatibility mapping JSON and exit.")
        @click.argument("args", nargs=-1, type=click.UNPROCESSED)
        @click.pass_context
        def _cmd(ctx: click.Context, compat_json: bool, args: tuple[Any, ...]) -> None:
            payload = _compat_payload(name, equivalents, note)
            if compat_json:
                click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
                return
            passthrough = list(forward_to)
            passthrough.extend(str(x) for x in args)
            rc = _forward_main_cli(ctx, passthrough)
            if rc != 0:
                raise SystemExit(rc)

        return _cmd

    @click.command(name=name)
    @click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
    def _cmd(as_json: bool) -> None:
        payload = _compat_payload(name, equivalents, note)
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        click.echo(f"{name}: partial compatibility alias")
        click.echo(f"equivalents: {', '.join(equivalents)}")
        click.echo(f"note: {note}")

    return _cmd


def _compat_aliases() -> list[click.Command]:
    specs: list[tuple[str, list[str], str, list[str] | None]] = [
        ("approvals", ["agents status"], "Guardrails approval APIs are exposed via server endpoints.", None),
        ("configure", ["config show", "doctor"], "Use config + doctor for setup and diagnostics.", ["config"]),
        ("directory", ["devices list"], "Use device records for local peer inventory.", None),
        ("docs", ["library list"], "Use library and repo docs for local documentation search.", ["library", "list"]),
        ("memory", ["library", "sessions"], "Use library/sessions; memory APIs are on server routes.", None),
        ("onboard", ["doctor", "status"], "Use doctor + status for onboarding checks.", ["doctor"]),
        ("pairing", ["devices pair"], "Use devices pair/verify/revoke.", None),
        ("reset", ["gateway restart"], "Use gateway restart + doctor for reset flows.", ["gateway", "restart"]),
        ("security", ["boot-doctor", "status"], "Use boot doctor and policy guardrails for security posture.", None),
        ("setup", ["doctor"], "Use doctor for setup validation and fixes.", ["doctor"]),
        ("skills", ["library"], "Use library and rules-of-road docs for skill guidance.", None),
        ("system", ["status", "health"], "Use status + health for system overview.", None),
        ("tui", ["repl"], "Use repl for terminal interactive workflow.", ["repl"]),
        ("uninstall", ["gateway uninstall"], "Use gateway uninstall lifecycle commands.", ["gateway", "uninstall"]),
        ("update", ["doppelganger"], "Use doppelganger blue/green commands for upgrade lifecycle.", None),
    ]
    return [
        _compat_command(name, equivalents=equiv, note=note, forward_to=forward_to)
        for name, equiv, note, forward_to in specs
    ]


def register_compat_commands(cli: click.Group) -> None:
    commands = [
        help_cmd,
        logs_cmd,
        agent_cmd,
        completion_cmd,
        browser,
        node,
        nodes,
        message,
        messages,
        qr_cmd,
        plugin_cmd,
        mcp,
        install_cmd,
        setup_token_cmd,
        acp,
        clawbot,
        daemon,
        dns,
        hooks,
        memory,
        system,
        approvals,
        directory,
        pairing,
        skills,
        security,
        update,
    ]
    commands.extend(_compat_aliases())
    for cmd in commands:
        name = str(getattr(cmd, "name", "") or "").strip()
        if not name:
            continue
        if name in cli.commands:
            continue
        cli.add_command(cmd)


@click.group(name="app")
@click.option("-c", "--config", "config_path", type=click.Path(exists=False), default="")
@click.pass_context
def app(ctx: click.Context, config_path: str) -> None:
    """
    Standalone parity app used by integration tests and automation wrappers.
    """
    path = Path(config_path).expanduser() if str(config_path or "").strip() else None
    ctx.ensure_object(dict)
    ctx.obj["config"] = load_config(path)
    ctx.obj["config_path"] = str(path) if path is not None else ""


register_compat_commands(app)

