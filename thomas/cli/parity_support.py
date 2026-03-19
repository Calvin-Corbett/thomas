"""Shared helper functions for thomas.cli.parity_compat."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import click

from thomas.core.config import AppConfig
from thomas.skills import discover_native_skill_roots, discover_native_skills, read_skill_bundle


def utc_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def state_dir(config: AppConfig) -> Path:
    path = config.memory.root_path / ".thomas" / "cli"
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ImportError:
        return default


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def tail_file(path: Path, lines: int) -> str:
    if not path.exists():
        return ""
    data = path.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join(data[-max(1, int(lines)) :])


def gateway_state_file(config: AppConfig) -> Path:
    return state_dir(config) / "gateway_state.json"


def gateway_log_file(config: AppConfig) -> Path:
    return state_dir(config) / "gateway.log"


def load_gateway_state(config: AppConfig) -> dict[str, Any]:
    payload = read_json(gateway_state_file(config), {})
    return payload if isinstance(payload, dict) else {}


def load_devices(config: AppConfig) -> list[dict[str, Any]]:
    state = load_gateway_state(config)
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


def emit_json_or_text(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for key, value in payload.items():
        click.echo(f"{key}: {value}")


def forward_main_cli(ctx: click.Context, args: list[str]) -> int:
    cmd = [sys.executable, "-m", "thomas.cli.main"]
    config_path = str((ctx.obj or {}).get("config_path") or "").strip()
    if config_path:
        cmd.extend(["-c", config_path])
    cmd.extend([str(a) for a in args])
    done = subprocess.run(cmd, check=False)
    return int(done.returncode or 0)


def messages_store_path(config: AppConfig) -> Path:
    return state_dir(config) / "messages.json"


def mcp_registry_path(config: AppConfig) -> Path:
    return state_dir(config) / "mcp_servers.json"


def load_mcp_registry(config: AppConfig) -> list[dict[str, Any]]:
    payload = read_json(mcp_registry_path(config), {"servers": []})
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


def save_mcp_registry(config: AppConfig, rows: list[dict[str, Any]]) -> None:
    write_json(mcp_registry_path(config), {"servers": rows, "updated_at": utc_iso()})


def find_mcp_server(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    target = str(name or "").strip().lower()
    if not target:
        return None
    for row in rows:
        if str((row or {}).get("name") or "").strip().lower() == target:
            return row
    return None


def token_store_path(config: AppConfig) -> Path:
    return state_dir(config) / "tokens.json"


def load_token_store(config: AppConfig) -> dict[str, Any]:
    payload = read_json(token_store_path(config), {})
    return payload if isinstance(payload, dict) else {}


def save_token_store(config: AppConfig, payload: dict[str, Any]) -> None:
    write_json(token_store_path(config), payload)


def skills_state_path(config: AppConfig) -> Path:
    return state_dir(config) / "skills.json"


def normalize_skill_name(value: str) -> str:
    return str(value or "").strip().lower()


def skill_row_key(name: str, path: str) -> str:
    return f"{normalize_skill_name(name)}::{str(path or '').strip().lower()}"



def read_skill_description(skill_md: Path) -> str:
    bundle = read_skill_bundle(skill_md.parent, source_root=skill_md.parent.parent, origin='native')
    if bundle is None:
        return ''
    return str(bundle.description or '')


def discover_skill_roots(config: AppConfig, *, include_root: str = '') -> list[Path]:
    _ = config
    roots = [path for path, _origin in discover_native_skill_roots(cwd=Path.cwd())]
    include_root_text = str(include_root or '').strip()
    if include_root_text:
        roots.append(Path(include_root_text).expanduser())

    unique: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except (OSError, FileNotFoundError):
            resolved = root
        key = str(resolved).lower()
        if key in seen:
            continue
        seen.add(key)
        if resolved.exists() and resolved.is_dir():
            unique.append(resolved)
    return unique


def discover_skills(config: AppConfig, *, include_root: str = '') -> tuple[list[dict[str, Any]], list[str]]:
    _ = config
    rows: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    bundles, roots = discover_native_skills(cwd=Path.cwd())

    for bundle in bundles:
        path_text = str(bundle.path)
        path_key = path_text.lower()
        if path_key in seen_paths:
            continue
        seen_paths.add(path_key)
        rows.append(
            {
                'name': bundle.name,
                'path': path_text,
                'skill_file': str(bundle.skill_file),
                'source_root': str(bundle.source_root),
                'description': str(bundle.description or ''),
                'origin': str(bundle.origin or ''),
            }
        )

    include_root_text = str(include_root or '').strip()
    if include_root_text:
        extra_root = Path(include_root_text).expanduser()
        try:
            resolved = extra_root.resolve()
        except (OSError, FileNotFoundError):
            resolved = extra_root
        if resolved.exists() and resolved.is_dir() and str(resolved) not in roots:
            roots.append(str(resolved))
            try:
                skill_files = list(resolved.rglob('SKILL.md'))
            except (OSError, FileNotFoundError):
                skill_files = []
            for skill_md in skill_files:
                bundle = read_skill_bundle(skill_md.parent, source_root=resolved, origin='extra')
                if bundle is None:
                    continue
                path_text = str(bundle.path)
                path_key = path_text.lower()
                if path_key in seen_paths:
                    continue
                seen_paths.add(path_key)
                rows.append(
                    {
                        'name': bundle.name,
                        'path': path_text,
                        'skill_file': str(bundle.skill_file),
                        'source_root': str(bundle.source_root),
                        'description': str(bundle.description or ''),
                        'origin': str(bundle.origin or ''),
                    }
                )

    rows.sort(key=lambda row: str(row.get('name') or '').lower())
    return rows, [str(root) for root in roots]


def load_skills_state(config: AppConfig) -> dict[str, Any]:
    payload = read_json(skills_state_path(config), {})
    if not isinstance(payload, dict):
        payload = {}
    rows = payload.get("skills")
    pinned = payload.get("pinned")
    usage = payload.get("usage")
    sync = payload.get("sync")
    return {
        "skills": [dict(row) for row in rows] if isinstance(rows, list) else [],
        "pinned": [str(x) for x in pinned if str(x).strip()] if isinstance(pinned, list) else [],
        "usage": dict(usage) if isinstance(usage, dict) else {},
        "sync": dict(sync) if isinstance(sync, dict) else {},
        "updated_at": str(payload.get("updated_at") or ""),
    }


def save_skills_state(config: AppConfig, state: dict[str, Any]) -> None:
    payload = {
        "skills": [dict(row) for row in (state.get("skills") or []) if isinstance(row, dict)],
        "pinned": sorted({str(x).strip().lower() for x in (state.get("pinned") or []) if str(x).strip()}),
        "usage": dict(state.get("usage") or {}),
        "sync": dict(state.get("sync") or {}),
        "updated_at": utc_iso(),
    }
    write_json(skills_state_path(config), payload)


def annotate_skill_rows(state: dict[str, Any]) -> None:
    rows = state.get("skills") or []
    pinned = {str(x).strip().lower() for x in (state.get("pinned") or []) if str(x).strip()}
    usage = state.get("usage") or {}
    if not isinstance(rows, list):
        return
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        path = str(row.get("path") or "").strip()
        usage_key = skill_row_key(name, path)
        usage_row = usage.get(usage_key) if isinstance(usage, dict) else {}
        if not isinstance(usage_row, dict):
            usage_row = {}
        row["pinned"] = normalize_skill_name(name) in pinned
        row["run_count"] = int(usage_row.get("run_count") or 0)
        row["last_used_at"] = str(usage_row.get("last_used_at") or "")


def skill_conflicts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_name: dict[str, list[str]] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or "").strip()
        path = str(row.get("path") or "").strip()
        if not name or not path:
            continue
        by_name.setdefault(name.lower(), []).append(path)

    conflicts: list[dict[str, Any]] = []
    for key, paths in sorted(by_name.items(), key=lambda item: item[0]):
        unique = sorted({str(p) for p in paths if str(p).strip()})
        if len(unique) <= 1:
            continue
        conflicts.append(
            {
                "name": key,
                "count": len(unique),
                "paths": unique,
            }
        )
    return conflicts


def skills_sync_state(config: AppConfig, *, include_root: str = "") -> dict[str, Any]:
    state = load_skills_state(config)
    discovered, roots = discover_skills(config, include_root=include_root)
    usage = dict(state.get("usage") or {})
    pinned = sorted({str(x).strip().lower() for x in (state.get("pinned") or []) if str(x).strip()})

    rows: list[dict[str, Any]] = []
    for row in discovered:
        name = str(row.get("name") or "").strip()
        path = str(row.get("path") or "").strip()
        usage_key = skill_row_key(name, path)
        usage_row = usage.get(usage_key)
        if not isinstance(usage_row, dict):
            usage_row = {}
        rows.append(
            {
                **row,
                "pinned": normalize_skill_name(name) in set(pinned),
                "run_count": int(usage_row.get("run_count") or 0),
                "last_used_at": str(usage_row.get("last_used_at") or ""),
            }
        )

    state["skills"] = rows
    state["pinned"] = pinned
    state["usage"] = usage
    state["sync"] = {
        "last_sync_at": utc_iso(),
        "roots": roots,
        "discovered_count": len(rows),
    }
    save_skills_state(config, state)
    return state


def skills_find_rows(state: dict[str, Any], name: str) -> list[dict[str, Any]]:
    target = normalize_skill_name(name)
    if not target:
        return []
    rows = state.get("skills")
    if not isinstance(rows, list):
        return []
    return [row for row in rows if isinstance(row, dict) and normalize_skill_name(str(row.get("name") or "")) == target]


def mark_skill_usage(state: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    usage = dict(state.get("usage") or {})
    now = utc_iso()
    for row in rows:
        name = str(row.get("name") or "").strip()
        path = str(row.get("path") or "").strip()
        if not name or not path:
            continue
        key = skill_row_key(name, path)
        current = usage.get(key)
        if not isinstance(current, dict):
            current = {}
        current["run_count"] = int(current.get("run_count") or 0) + 1
        current["last_used_at"] = now
        usage[key] = current
    state["usage"] = usage
    annotate_skill_rows(state)


def mask_secret(value: str) -> str:
    token = str(value or "")
    if not token:
        return ""
    if len(token) <= 8:
        return "*" * len(token)
    return f"{token[:4]}...{token[-4:]}"


def load_messages(config: AppConfig) -> list[dict[str, Any]]:
    payload = read_json(messages_store_path(config), {"messages": []})
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


def save_messages(config: AppConfig, rows: list[dict[str, Any]]) -> None:
    write_json(messages_store_path(config), {"messages": rows, "updated_at": utc_iso()})


def provider_env_map(name: str) -> dict[str, str]:
    if name == "telegram":
        return {"token": "THOMAS_TELEGRAM_BOT_TOKEN"}
    if name == "discord":
        return {"token": "THOMAS_DISCORD_BOT_TOKEN", "webhook": "THOMAS_DISCORD_WEBHOOK_URL"}
    if name == "slack":
        return {"token": "THOMAS_SLACK_BOT_TOKEN", "webhook": "THOMAS_SLACK_WEBHOOK_URL"}
    return {}


def resolve_provider_secrets(config: AppConfig, name: str) -> dict[str, str]:
    from thomas.cli.commands.channels import _load_channels_store

    store = _load_channels_store(config)
    providers = store.get("providers", {})
    row = providers.get(name, {}) if isinstance(providers, dict) else {}
    if not isinstance(row, dict):
        row = {}
    env_map = provider_env_map(name)

    def _resolve(field: str) -> str:
        env_key = env_map.get(field, "")
        env_val = str(os.environ.get(env_key) or "").strip() if env_key else ""
        if env_val:
            return env_val
        return str(row.get(field) or "").strip()

    return {"token": _resolve("token"), "webhook": _resolve("webhook")}


def http_post_json(
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout_s: float = 8.0,
) -> dict[str, Any]:
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
        except json.JSONDecodeError:
            parsed = {"raw": raw[:2000]}
        return {"ok": 200 <= status < 300, "status": status, "payload": parsed}
    except urllib.error.HTTPError as e:
        body_text = ""
        try:
            body_text = e.read().decode("utf-8", errors="replace")
        except json.JSONDecodeError:
            body_text = ""
        parsed: Any
        try:
            parsed = json.loads(body_text) if body_text else {}
        except json.JSONDecodeError:
            parsed = {"raw": body_text[:2000]}
        return {"ok": False, "status": int(getattr(e, "code", 0) or 0), "payload": parsed, "error": str(e)}
    except Exception as e:
        return {"ok": False, "status": 0, "payload": {}, "error": f"{type(e).__name__}: {e}"}


def send_channel_message(
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

    secrets_row = resolve_provider_secrets(config, provider)
    token = str(secrets_row.get("token") or "").strip()
    webhook = str(secrets_row.get("webhook") or "").strip()
    target_text = str(target or "").strip()
    body_text = str(text or "")

    if provider == "telegram":
        if not token:
            return {"ok": False, "status": 0, "provider": provider, "error": "telegram token missing"}
        if not target_text:
            return {"ok": False, "status": 0, "provider": provider, "error": "telegram target chat id required"}
        res = http_post_json(
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
            res = http_post_json(url, {"content": body_text}, timeout_s=timeout_s)
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
            res = http_post_json(
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
            res = http_post_json(webhook, {"text": body_text}, timeout_s=timeout_s)
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
        if token:
            return {
                "ok": False,
                "status": 0,
                "provider": provider,
                "error": "slack token configured but chat.postMessage API flow is not wired; set webhook instead",
            }
        return {"ok": False, "status": 0, "provider": provider, "error": "slack webhook required"}

    return {"ok": False, "status": 0, "provider": provider, "error": f"unsupported channel: {provider}"}


def compat_emit(command: str, action: str, note: str, target: str, as_json: bool, ctx: click.Context) -> None:
    payload: dict[str, Any] = {
        "command": command,
        "action": action,
        "note": note,
        "target": target,
        "timestamp_utc": utc_iso(),
    }
    if command == "directory" and action == "list":
        config: AppConfig = ctx.obj["config"]
        payload["count"] = len(load_devices(config))
    if command == "memory" and action == "status":
        config = ctx.obj["config"]
        root = config.memory.root_path / ".thomas"
        payload["root"] = str(root)
        payload["chat_files"] = len(list((root / "chats").glob("*.json"))) if (root / "chats").exists() else 0
    if command == "security" and action == "audit":
        from thomas.security.security_audit import run_security_audit

        repo_root = (
            Path(target).expanduser().resolve() if str(target or "").strip() else Path(__file__).resolve().parents[2]
        )
        audit = run_security_audit(repo_root, include_incident_drill=False)
        payload["ok"] = bool(audit.get("ok", False))
        payload["summary"] = audit.get("summary", {})
        payload["checks"] = audit.get("checks", {})
        payload["repo_root"] = str(audit.get("repo_root") or repo_root)
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"{command} {action}: {note}")
    if target:
        click.echo(f"- target: {target}")
    if "count" in payload:
        click.echo(f"- count: {payload['count']}")
    if "ok" in payload:
        click.echo(f"- ok: {bool(payload.get('ok'))}")
    summary = payload.get("summary")
    if isinstance(summary, dict):
        for key in ("check_count", "error_count", "warning_count"):
            if key in summary:
                click.echo(f"- {key}: {summary.get(key)}")
        failing = summary.get("failing_checks")
        if isinstance(failing, list) and failing:
            click.echo(f"- failing_checks: {', '.join(str(x) for x in failing)}")


def compat_action(command: str, action: str, note: str) -> click.Command:
    @click.command(name=action)
    @click.argument("target", required=False, default="")
    @click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
    @click.pass_context
    def _cmd(ctx: click.Context, target: str, as_json: bool) -> None:
        compat_emit(command, action, note, str(target or "").strip(), as_json, ctx)

    return _cmd


def compat_group(name: str, actions: list[tuple[str, str]]) -> click.Group:
    @click.group(name=name)
    @click.pass_context
    def _group(ctx: click.Context) -> None:
        _ = ctx

    for action, note in actions:
        _group.add_command(compat_action(name, action, note))
    return _group


def forward_passthrough(ctx: click.Context, base_args: list[str], extra_args: tuple[Any, ...]) -> None:
    args = [str(x) for x in base_args]
    args.extend(str(x) for x in extra_args)
    rc = forward_main_cli(ctx, args)
    if rc != 0:
        raise SystemExit(rc)


__all__ = [
    "annotate_skill_rows",
    "compat_action",
    "compat_emit",
    "compat_group",
    "discover_skills",
    "emit_json_or_text",
    "find_mcp_server",
    "forward_main_cli",
    "forward_passthrough",
    "gateway_log_file",
    "gateway_state_file",
    "load_devices",
    "load_gateway_state",
    "load_mcp_registry",
    "load_messages",
    "load_skills_state",
    "load_token_store",
    "mark_skill_usage",
    "mask_secret",
    "mcp_registry_path",
    "messages_store_path",
    "normalize_skill_name",
    "read_json",
    "save_mcp_registry",
    "save_messages",
    "save_skills_state",
    "save_token_store",
    "send_channel_message",
    "skill_conflicts",
    "skill_row_key",
    "skills_find_rows",
    "skills_state_path",
    "skills_sync_state",
    "state_dir",
    "tail_file",
    "token_store_path",
    "utc_iso",
    "write_json",
]
