"""Additional CLI command families for high-visibility OpenClaw parity."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import signal
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import click

from thomas.cli.pack_bridge import register_pack_proxy_commands
from thomas.core.config import AppConfig


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


def _parse_json_file(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _is_pid_running(pid: int) -> bool:
    if int(pid) <= 0:
        return False
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {int(pid)}"],
            capture_output=True,
            text=True,
            check=False,
        )
        text = str(out.stdout or "").lower()
        if "no tasks are running" in text:
            return False
        return str(int(pid)) in text
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def _kill_pid(pid: int) -> bool:
    if int(pid) <= 0:
        return False
    if os.name == "nt":
        out = subprocess.run(
            ["taskkill", "/PID", str(int(pid)), "/T", "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        return int(out.returncode or 1) == 0
    try:
        os.kill(int(pid), signal.SIGTERM)
        return True
    except Exception:
        return False


def _port_in_use(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, int(port)), timeout=0.35):
            return True
    except OSError:
        return False


def _find_free_port(host: str, preferred: int, max_offset: int = 25) -> Optional[int]:
    for candidate in range(int(preferred), int(preferred) + int(max_offset) + 1):
        if not _port_in_use(host, candidate):
            return candidate
    return None


def _resolve_bind_port(host: str, port: int, auto_port: bool) -> int:
    selected = int(port)
    if _port_in_use(host, selected):
        if not auto_port:
            raise click.ClickException(
                f"Port {selected} is busy. Re-run with --auto-port or choose a different --port."
            )
        free_port = _find_free_port(host, selected)
        if free_port is None:
            raise click.ClickException(f"No free port found in range {selected}..{selected + 25}.")
        click.echo(f"Port {selected} is busy; auto-selecting {free_port}.")
        selected = int(free_port)
    return selected


def _http_get_json(url: str, timeout_s: float = 2.0, token: str = "") -> dict[str, Any]:
    headers = {}
    token_val = str(token or "").strip()
    if token_val:
        headers["Authorization"] = f"Bearer {token_val}"
    req = urllib.request.Request(url=url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = int(getattr(resp, "status", 0) or 0)
            body = resp.read().decode("utf-8", errors="replace")
        payload: Any
        try:
            payload = json.loads(body)
        except Exception:
            payload = {"raw": body[:2000]}
        return {"ok": True, "status": status, "payload": payload}
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
            payload = {"raw": body[:2000]}
        return {"ok": False, "status": int(getattr(e, "code", 0) or 0), "error": str(e), "payload": payload}
    except Exception as e:
        return {"ok": False, "status": 0, "error": f"{type(e).__name__}: {e}", "payload": {}}


def _probe_gateway(host: str, port: int, *, token: str = "") -> dict[str, Any]:
    base = f"http://{host}:{int(port)}"
    tcp_ok = _port_in_use(host, int(port))
    version = _http_get_json(f"{base}/api/version", token=token)
    models = _http_get_json(f"{base}/api/models", token=token)
    engines = _http_get_json(f"{base}/api/engines", token=token)
    healthy = bool(tcp_ok and (version.get("ok") or models.get("ok")))
    return {
        "host": host,
        "port": int(port),
        "base_url": base,
        "tcp_open": bool(tcp_ok),
        "version": version,
        "models": models,
        "engines": engines,
        "healthy": healthy,
    }


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


def _save_gateway_state(config: AppConfig, payload: dict[str, Any]) -> None:
    _write_json(_gateway_state_file(config), payload)


def _clear_gateway_state(config: AppConfig) -> None:
    path = _gateway_state_file(config)
    if path.exists():
        path.unlink(missing_ok=True)


def _active_gateway_target(config: AppConfig, host: Optional[str], port: Optional[int]) -> tuple[str, int, dict[str, Any]]:
    state = _load_gateway_state(config)
    state_host = str(state.get("host") or "").strip()
    state_port_raw = state.get("port")
    state_port = int(state_port_raw) if isinstance(state_port_raw, int) else 0
    if host:
        use_host = str(host).strip()
    elif state_host:
        use_host = state_host
    else:
        use_host = "127.0.0.1"
    if port is not None:
        use_port = int(port)
    elif state_port > 0:
        use_port = int(state_port)
    else:
        use_port = 8899
    return use_host, use_port, state


def _emit_json_or_text(payload: dict[str, Any], as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for key, value in payload.items():
        click.echo(f"{key}: {value}")


@click.group()
@click.pass_context
def agents(ctx: click.Context) -> None:
    """Manage internal agent engines and role visibility."""
    _ = ctx


def _engine_snapshot() -> dict[str, Any]:
    try:
        from thomas.core.engine_manager import get_engine_manager

        manager = get_engine_manager()
        payload = manager.status()
        if isinstance(payload, dict):
            return payload
        return {"running": False, "error": "invalid engine status payload", "engines": {}}
    except Exception as e:
        return {"running": False, "error": f"{type(e).__name__}: {e}", "engines": {}}


@agents.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def agents_list(as_json: bool) -> None:
    """List built-in role agents and background engine agents."""
    engine = _engine_snapshot()
    role_agents = [
        {"id": "planner", "kind": "swarm_role", "description": "Builds task graph plans."},
        {"id": "coder", "kind": "swarm_role", "description": "Implements code/task changes."},
        {"id": "tester", "kind": "swarm_role", "description": "Validates output and regressions."},
        {"id": "reviewer", "kind": "swarm_role", "description": "Synthesizes final response."},
    ]
    payload = {"roles": role_agents, "engines": engine}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo("Role agents:")
    for row in role_agents:
        click.echo(f"- {row['id']} ({row['kind']}): {row['description']}")
    click.echo(f"Background engines running: {bool(engine.get('running', False))}")
    engines = engine.get("engines")
    if isinstance(engines, dict):
        for name, row in engines.items():
            running = bool((row or {}).get("running", False)) if isinstance(row, dict) else False
            state = "running" if running else "stopped"
            click.echo(f"- {name}: {state}")


@agents.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def agents_status(as_json: bool) -> None:
    """Show internal agent engine status."""
    payload = _engine_snapshot()
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"manager_running: {bool(payload.get('running', False))}")
    engines = payload.get("engines")
    if isinstance(engines, dict):
        for name, row in engines.items():
            if isinstance(row, dict):
                click.echo(
                    f"- {name}: running={bool(row.get('running', False))}, "
                    f"cycles={int(row.get('cycles_completed', 0) or 0)}, "
                    f"error={str(row.get('error') or '')}"
                )
    err = str(payload.get("error") or "").strip()
    if err:
        click.echo(f"error: {err}")


@agents.command("start")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def agents_start(as_json: bool) -> None:
    """Start all internal background agent engines."""
    try:
        from thomas.core.engine_manager import get_engine_manager

        manager = get_engine_manager()
        result = manager.start_all()
        payload = {"ok": True, "started": result, "status": manager.status()}
    except Exception as e:
        payload = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"ok: {bool(payload.get('ok', False))}")
    if payload.get("ok"):
        started = payload.get("started", {})
        if isinstance(started, dict):
            for name, ok in started.items():
                click.echo(f"- {name}: {'started' if ok else 'failed'}")
    else:
        click.echo(f"error: {payload.get('error')}")


@agents.command("stop")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def agents_stop(as_json: bool) -> None:
    """Stop all internal background agent engines."""
    try:
        from thomas.core.engine_manager import get_engine_manager

        manager = get_engine_manager()
        manager.stop_all()
        payload = {"ok": True, "status": manager.status()}
    except Exception as e:
        payload = {"ok": False, "error": f"{type(e).__name__}: {e}"}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"ok: {bool(payload.get('ok', False))}")
    if not payload.get("ok"):
        click.echo(f"error: {payload.get('error')}")


@click.group()
@click.pass_context
def devices(ctx: click.Context) -> None:
    """Manage local device pairing records and access tokens."""
    _ = ctx


def _devices_file(config: AppConfig) -> Path:
    return _state_dir(config) / "devices.json"


def _load_devices(config: AppConfig) -> list[dict[str, Any]]:
    payload = _read_json(_devices_file(config), {"devices": []})
    if not isinstance(payload, dict):
        return []
    rows = payload.get("devices")
    return rows if isinstance(rows, list) else []


def _save_devices(config: AppConfig, devices_rows: list[dict[str, Any]]) -> None:
    _write_json(_devices_file(config), {"devices": devices_rows, "updated_at": _utc_iso()})


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token).encode("utf-8")).hexdigest()


@devices.command("list")
@click.option("--show-revoked", is_flag=True, help="Include revoked devices.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def devices_list(ctx: click.Context, show_revoked: bool, as_json: bool) -> None:
    """List paired devices."""
    config: AppConfig = ctx.obj["config"]
    rows = _load_devices(config)
    out = []
    for row in rows:
        if not show_revoked and bool(row.get("revoked", False)):
            continue
        out.append(
            {
                "id": str(row.get("id") or ""),
                "name": str(row.get("name") or ""),
                "kind": str(row.get("kind") or "unknown"),
                "revoked": bool(row.get("revoked", False)),
                "created_at": str(row.get("created_at") or ""),
                "last_seen_at": str(row.get("last_seen_at") or ""),
            }
        )
    payload = {"count": len(out), "devices": out}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Devices: {len(out)}")
    for row in out:
        status = "revoked" if row["revoked"] else "active"
        click.echo(
            f"- {row['id']} | {row['name']} | kind={row['kind']} | {status} | "
            f"created={row['created_at']} | last_seen={row['last_seen_at']}"
        )


@devices.command("pair")
@click.option("--name", required=True, help="Human label for this device.")
@click.option(
    "--kind",
    type=click.Choice(["desktop", "mobile", "cli", "service"], case_sensitive=False),
    default="cli",
    show_default=True,
)
@click.option("--token-bytes", default=24, type=int, show_default=True, help="Token entropy size.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def devices_pair(ctx: click.Context, name: str, kind: str, token_bytes: int, as_json: bool) -> None:
    """Create a paired device record and return a token (shown once)."""
    config: AppConfig = ctx.obj["config"]
    rows = _load_devices(config)
    now = _utc_iso()
    device_id = f"dev_{secrets.token_hex(6)}"
    token = secrets.token_urlsafe(max(16, int(token_bytes)))
    row = {
        "id": device_id,
        "name": str(name).strip(),
        "kind": str(kind).strip().lower(),
        "revoked": False,
        "token_hash": _token_hash(token),
        "created_at": now,
        "last_seen_at": now,
    }
    rows.append(row)
    _save_devices(config, rows)
    payload = {
        "ok": True,
        "device": {
            "id": row["id"],
            "name": row["name"],
            "kind": row["kind"],
            "revoked": row["revoked"],
            "created_at": row["created_at"],
        },
        "token": token,
        "warning": "Store this token now; only its hash is persisted.",
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Paired device: {row['id']} ({row['name']}, {row['kind']})")
    click.echo(f"Token: {token}")
    click.echo("Store this token now; only its hash is persisted.")


@devices.command("revoke")
@click.argument("device_id")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def devices_revoke(ctx: click.Context, device_id: str, as_json: bool) -> None:
    """Revoke a paired device token."""
    config: AppConfig = ctx.obj["config"]
    rows = _load_devices(config)
    hit = False
    now = _utc_iso()
    for row in rows:
        if str(row.get("id") or "") == str(device_id).strip():
            row["revoked"] = True
            row["last_seen_at"] = now
            hit = True
            break
    if hit:
        _save_devices(config, rows)
    payload = {"ok": hit, "device_id": str(device_id).strip()}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if hit:
        click.echo(f"Revoked device: {device_id}")
    else:
        click.echo(f"Device not found: {device_id}")
        raise SystemExit(1)


@devices.command("verify")
@click.argument("device_id")
@click.option("--token", required=True, help="Device token to verify.")
@click.option("--touch", is_flag=True, help="Update last_seen_at if verification succeeds.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def devices_verify(ctx: click.Context, device_id: str, token: str, touch: bool, as_json: bool) -> None:
    """Verify a token against a paired device."""
    config: AppConfig = ctx.obj["config"]
    rows = _load_devices(config)
    expected = _token_hash(token)
    ok = False
    revoked = False
    for row in rows:
        if str(row.get("id") or "") != str(device_id).strip():
            continue
        revoked = bool(row.get("revoked", False))
        if not revoked and str(row.get("token_hash") or "") == expected:
            ok = True
            if touch:
                row["last_seen_at"] = _utc_iso()
        break
    if ok and touch:
        _save_devices(config, rows)
    payload = {"ok": ok, "device_id": str(device_id).strip(), "revoked": revoked}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"valid: {ok}")
    click.echo(f"revoked: {revoked}")


@devices.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def devices_status(ctx: click.Context, as_json: bool) -> None:
    """Show paired device counts and health summary."""
    config: AppConfig = ctx.obj["config"]
    rows = _load_devices(config)
    total = len(rows)
    revoked = sum(1 for row in rows if bool(row.get("revoked", False)))
    active = max(0, total - revoked)
    payload = {"total": total, "active": active, "revoked": revoked}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"total: {total}")
    click.echo(f"active: {active}")
    click.echo(f"revoked: {revoked}")


@click.group()
@click.pass_context
def plugins(ctx: click.Context) -> None:
    """Manage local plugin manifests and enablement."""
    _ = ctx


def _plugins_file(config: AppConfig) -> Path:
    return _state_dir(config) / "plugins.json"


def _load_plugins(config: AppConfig) -> list[dict[str, Any]]:
    payload = _read_json(_plugins_file(config), {"plugins": []})
    if not isinstance(payload, dict):
        return []
    rows = payload.get("plugins")
    return rows if isinstance(rows, list) else []


def _save_plugins(config: AppConfig, rows: list[dict[str, Any]]) -> None:
    _write_json(_plugins_file(config), {"plugins": rows, "updated_at": _utc_iso()})


def _find_plugin(rows: list[dict[str, Any]], name: str) -> Optional[dict[str, Any]]:
    target = str(name).strip().lower()
    for row in rows:
        if str(row.get("name") or "").strip().lower() == target:
            return row
    return None


@plugins.command("list")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def plugins_list(ctx: click.Context, as_json: bool) -> None:
    """List installed plugin manifests."""
    config: AppConfig = ctx.obj["config"]
    rows = _load_plugins(config)
    payload_rows = [
        {
            "name": str(row.get("name") or ""),
            "path": str(row.get("path") or ""),
            "enabled": bool(row.get("enabled", False)),
            "installed_at": str(row.get("installed_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
        }
        for row in rows
    ]
    payload = {"count": len(payload_rows), "plugins": payload_rows}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Plugins: {len(payload_rows)}")
    for row in payload_rows:
        state = "enabled" if row["enabled"] else "disabled"
        click.echo(
            f"- {row['name']} | {state} | path={row['path']} | "
            f"installed={row['installed_at']} | updated={row['updated_at']}"
        )


@plugins.command("install")
@click.option("--name", required=True, help="Plugin name.")
@click.option("--path", "plugin_path", required=True, help="Plugin file or directory path.")
@click.option("--enable/--disable", default=True, show_default=True, help="Initial plugin state.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def plugins_install(
    ctx: click.Context,
    name: str,
    plugin_path: str,
    enable: bool,
    as_json: bool,
) -> None:
    """Install or update a plugin manifest entry."""
    config: AppConfig = ctx.obj["config"]
    resolved = Path(plugin_path).expanduser().resolve()
    if not resolved.exists():
        raise click.ClickException(f"Plugin path does not exist: {resolved}")

    rows = _load_plugins(config)
    now = _utc_iso()
    existing = _find_plugin(rows, name)
    if existing is None:
        existing = {
            "name": str(name).strip(),
            "path": str(resolved),
            "enabled": bool(enable),
            "installed_at": now,
            "updated_at": now,
        }
        rows.append(existing)
    else:
        existing["path"] = str(resolved)
        existing["enabled"] = bool(enable)
        existing["updated_at"] = now
    _save_plugins(config, rows)
    payload = {"ok": True, "plugin": existing}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    state = "enabled" if bool(existing.get("enabled", False)) else "disabled"
    click.echo(f"Plugin saved: {existing.get('name')} ({state})")


@plugins.command("uninstall")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def plugins_uninstall(ctx: click.Context, name: str, as_json: bool) -> None:
    """Uninstall a plugin manifest entry."""
    config: AppConfig = ctx.obj["config"]
    rows = _load_plugins(config)
    before = len(rows)
    rows = [row for row in rows if str(row.get("name") or "").strip().lower() != str(name).strip().lower()]
    hit = len(rows) != before
    if hit:
        _save_plugins(config, rows)
    payload = {"ok": hit, "name": str(name).strip()}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    if hit:
        click.echo(f"Plugin removed: {name}")
    else:
        click.echo(f"Plugin not found: {name}")
        raise SystemExit(1)


@plugins.command("enable")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def plugins_enable(ctx: click.Context, name: str, as_json: bool) -> None:
    """Enable a plugin."""
    _plugins_set_enabled(ctx, name=name, enabled=True, as_json=as_json)


@plugins.command("disable")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def plugins_disable(ctx: click.Context, name: str, as_json: bool) -> None:
    """Disable a plugin."""
    _plugins_set_enabled(ctx, name=name, enabled=False, as_json=as_json)


def _plugins_set_enabled(ctx: click.Context, *, name: str, enabled: bool, as_json: bool) -> None:
    config: AppConfig = ctx.obj["config"]
    rows = _load_plugins(config)
    row = _find_plugin(rows, name)
    if row is None:
        payload = {"ok": False, "error": f"plugin not found: {name}"}
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            raise SystemExit(1)
        raise click.ClickException(str(payload["error"]))
    row["enabled"] = bool(enabled)
    row["updated_at"] = _utc_iso()
    _save_plugins(config, rows)
    payload = {"ok": True, "plugin": row}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Plugin {row.get('name')} set to {'enabled' if enabled else 'disabled'}.")


@plugins.command("show")
@click.argument("name")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def plugins_show(ctx: click.Context, name: str, as_json: bool) -> None:
    """Show one plugin manifest entry."""
    config: AppConfig = ctx.obj["config"]
    rows = _load_plugins(config)
    row = _find_plugin(rows, name)
    if row is None:
        raise click.ClickException(f"Plugin not found: {name}")
    payload = dict(row)
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    for key in ("name", "path", "enabled", "installed_at", "updated_at"):
        click.echo(f"{key}: {payload.get(key)}")


@plugins.command("extension-catalog")
@click.option("--strict", is_flag=True, help="Exit non-zero when any extension pack is invalid.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def plugins_extension_catalog(strict: bool, as_json: bool) -> None:
    """Validate and inspect extension-pack catalog integration."""
    from thomas.plugins.extension_catalog_runtime import validate_extension_catalog

    payload = validate_extension_catalog()
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(f"root: {payload.get('root')}")
        click.echo(f"total: {payload.get('total')}")
        click.echo(f"valid: {payload.get('valid')}")
        click.echo(f"invalid: {payload.get('invalid')}")
        packs = payload.get("packs") if isinstance(payload.get("packs"), list) else []
        for row in packs[:25]:
            state = "valid" if bool(row.get("valid")) else "invalid"
            click.echo(f"- {row.get('id')} | {state}")
        if len(packs) > 25:
            click.echo(f"... {len(packs) - 25} more")

    if strict and int(payload.get("invalid") or 0) > 0:
        raise SystemExit(1)


register_pack_proxy_commands(
    plugins,
    package="thomas.cli.commands.plugins",
    family_hint="plugin",
)


@click.group()
@click.pass_context
def sandbox(ctx: click.Context) -> None:
    """Manage local sandbox execution and tests."""
    _ = ctx


def _resolve_code_input(code: Optional[str], file_path: Optional[str]) -> str:
    code_text = str(code or "").strip()
    file_text = str(file_path or "").strip()
    if code_text and file_text:
        raise click.ClickException("Specify either --code or --file, not both.")
    if file_text:
        path = Path(file_text).expanduser().resolve()
        if not path.exists():
            raise click.ClickException(f"File not found: {path}")
        return path.read_text(encoding="utf-8-sig")
    if code_text:
        return code_text
    raise click.ClickException("Provide sandbox code with --code or --file.")


@sandbox.command("status")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def sandbox_status(as_json: bool) -> None:
    """Show sandbox backend and runtime limits."""
    from thomas.tools import sandbox as sb

    payload = {
        "backend_mode": str(getattr(sb, "SANDBOX_BACKEND", "auto")),
        "runs_dir": str(getattr(sb, "RUNS_DIR", "")),
        "max_timeout_seconds": int(getattr(sb, "MAX_TIMEOUT", 30)),
        "max_code_bytes": int(getattr(sb, "MAX_CODE_BYTES", 0)),
        "stdout_head_bytes": int(getattr(sb, "STDOUT_HEAD", 0)),
        "stdout_tail_bytes": int(getattr(sb, "STDOUT_TAIL", 0)),
        "stderr_head_bytes": int(getattr(sb, "STDERR_HEAD", 0)),
        "stderr_tail_bytes": int(getattr(sb, "STDERR_TAIL", 0)),
    }
    _emit_json_or_text(payload, as_json=as_json)


@sandbox.command("run")
@click.option("--code", help="Inline Python code to execute.")
@click.option("--file", "file_path", help="Path to Python file to execute.")
@click.option("--timeout", "timeout_seconds", default=10, type=int, show_default=True)
@click.option("--allow-network", is_flag=True, help="Allow network access for this run.")
@click.option("--package", "packages", multiple=True, help="Extra package requirement (repeatable).")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def sandbox_run_cmd(
    code: Optional[str],
    file_path: Optional[str],
    timeout_seconds: int,
    allow_network: bool,
    packages: tuple[str, ...],
    as_json: bool,
) -> None:
    """Run Python code in the sandbox."""
    from thomas.tools.sandbox import sandbox_run

    source = _resolve_code_input(code, file_path)
    result = sandbox_run(
        code=source,
        timeout_seconds=int(timeout_seconds),
        allow_network=bool(allow_network),
        packages=[str(p).strip() for p in packages if str(p).strip()],
    )
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    click.echo(f"backend: {result.get('backend')}")
    click.echo(f"duration_ms: {result.get('duration_ms')}")
    click.echo(f"run_id: {result.get('run_id')}")
    err = str(result.get("error") or "").strip()
    if err:
        click.echo(f"error: {err}")
    stdout = str(result.get("stdout") or "")
    stderr = str(result.get("stderr") or "")
    ret = str(result.get("return_value") or "")
    if stdout:
        click.echo("stdout:")
        click.echo(stdout)
    if stderr:
        click.echo("stderr:")
        click.echo(stderr)
    if ret:
        click.echo(f"return_value: {ret}")


@sandbox.command("test")
@click.option("--code", help="Inline Python code to execute.")
@click.option("--file", "file_path", help="Path to Python file to execute.")
@click.option("--cases-file", required=True, help="JSON file with test cases [{input, expected}, ...].")
@click.option("--timeout", "timeout_seconds", default=10, type=int, show_default=True)
@click.option("--allow-network", is_flag=True, help="Allow network access for this run.")
@click.option("--package", "packages", multiple=True, help="Extra package requirement (repeatable).")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def sandbox_test_cmd(
    code: Optional[str],
    file_path: Optional[str],
    cases_file: str,
    timeout_seconds: int,
    allow_network: bool,
    packages: tuple[str, ...],
    as_json: bool,
) -> None:
    """Run snippet tests in the sandbox."""
    from thomas.tools.sandbox import sandbox_test_snippet

    source = _resolve_code_input(code, file_path)
    path = Path(cases_file).expanduser().resolve()
    if not path.exists():
        raise click.ClickException(f"Cases file not found: {path}")
    payload = _parse_json_file(path)
    if not isinstance(payload, list):
        raise click.ClickException("cases-file must contain a JSON array.")
    result = sandbox_test_snippet(
        code=source,
        test_cases=payload,
        timeout_seconds=int(timeout_seconds),
        allow_network=bool(allow_network),
        packages=[str(p).strip() for p in packages if str(p).strip()],
    )
    if as_json:
        click.echo(json.dumps(result, ensure_ascii=False, indent=2))
        return
    summary = result.get("summary", {})
    click.echo(f"total: {summary.get('total', 0)}")
    click.echo(f"passed: {summary.get('passed', 0)}")
    click.echo(f"failed: {summary.get('failed', 0)}")


@click.group()
@click.pass_context
def gateway(ctx: click.Context) -> None:
    """Run and inspect the local Thomas gateway server lifecycle."""
    _ = ctx


def _gateway_spawn(
    *,
    config_path: str,
    host: str,
    port: int,
    log_path: Path,
) -> subprocess.Popen[Any]:
    cmd: list[str] = [sys.executable, "-m", "thomas.cli.main"]
    cfg = str(config_path or "").strip()
    if cfg:
        cmd.extend(["-c", cfg])
    cmd.extend(["serve", "--host", str(host), "--port", str(int(port)), "--strict-port"])

    log_path.parent.mkdir(parents=True, exist_ok=True)
    out = log_path.open("a", encoding="utf-8")
    creationflags = 0
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "DETACHED_PROCESS", 0)) | int(
            getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        )
    return subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=out,
        stderr=out,
        close_fds=True,
        creationflags=creationflags,
    )


@gateway.command("run")
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8899, show_default=True, type=int)
@click.option("--auto-port/--strict-port", default=True, show_default=True)
@click.option("--detach/--foreground", default=True, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def gateway_run(
    ctx: click.Context,
    host: str,
    port: int,
    auto_port: bool,
    detach: bool,
    as_json: bool,
) -> None:
    """Start the gateway server."""
    config: AppConfig = ctx.obj["config"]
    selected_port = _resolve_bind_port(host, int(port), bool(auto_port))

    if not detach:
        from thomas.server.app import serve as serve_app

        serve_app(config, host=host, port=selected_port)
        return

    state = _load_gateway_state(config)
    prior_pid = int(state.get("pid") or 0) if str(state.get("pid") or "").strip() else 0
    if prior_pid > 0 and _is_pid_running(prior_pid):
        payload = {
            "ok": True,
            "already_running": True,
            "pid": prior_pid,
            "host": str(state.get("host") or host),
            "port": int(state.get("port") or selected_port),
            "url": f"http://{state.get('host', host)}:{int(state.get('port', selected_port))}/",
        }
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        click.echo(f"Gateway already running (pid={payload['pid']}) at {payload['url']}")
        return

    cfg_path = str(ctx.obj.get("config_path") or "").strip()
    if not cfg_path:
        cfg_path = str(os.environ.get("THOMAS_CONFIG") or "").strip()
    log_path = _gateway_log_file(config)
    proc = _gateway_spawn(config_path=cfg_path, host=host, port=selected_port, log_path=log_path)
    time.sleep(1.2)
    running = _is_pid_running(int(proc.pid))
    probe = _probe_gateway(host, selected_port, token=config.server.api_token)
    payload = {
        "ok": bool(running),
        "pid": int(proc.pid),
        "host": host,
        "port": int(selected_port),
        "url": f"http://{host}:{int(selected_port)}/",
        "log_file": str(log_path),
        "healthy": bool(probe.get("healthy", False)),
    }
    if running:
        _save_gateway_state(
            config,
            {
                "pid": int(proc.pid),
                "host": host,
                "port": int(selected_port),
                "started_at": _utc_iso(),
                "log_file": str(log_path),
            },
        )
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"Gateway pid: {payload['pid']}")
    click.echo(f"URL: {payload['url']}")
    click.echo(f"Healthy: {payload['healthy']}")
    click.echo(f"Log: {payload['log_file']}")


@gateway.command("status")
@click.option("--host", default=None, help="Override probe host.")
@click.option("--port", default=None, type=int, help="Override probe port.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def gateway_status(ctx: click.Context, host: Optional[str], port: Optional[int], as_json: bool) -> None:
    """Show gateway process + API health status."""
    config: AppConfig = ctx.obj["config"]
    use_host, use_port, state = _active_gateway_target(config, host, port)
    pid = int(state.get("pid") or 0) if str(state.get("pid") or "").strip() else 0
    process_running = bool(pid > 0 and _is_pid_running(pid))
    probe = _probe_gateway(use_host, use_port, token=config.server.api_token)
    payload = {
        "pid": pid,
        "process_running": process_running,
        "host": use_host,
        "port": int(use_port),
        "url": f"http://{use_host}:{int(use_port)}/",
        "state_file": str(_gateway_state_file(config)),
        "log_file": str(state.get("log_file") or _gateway_log_file(config)),
        "probe": probe,
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"pid: {pid}")
    click.echo(f"process_running: {process_running}")
    click.echo(f"url: {payload['url']}")
    click.echo(f"tcp_open: {probe.get('tcp_open')}")
    click.echo(f"healthy: {probe.get('healthy')}")
    version = probe.get("version", {})
    models = probe.get("models", {})
    engines = probe.get("engines", {})
    click.echo(f"/api/version: ok={version.get('ok')} status={version.get('status')}")
    click.echo(f"/api/models: ok={models.get('ok')} status={models.get('status')}")
    click.echo(f"/api/engines: ok={engines.get('ok')} status={engines.get('status')}")


@gateway.command("stop")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def gateway_stop(ctx: click.Context, as_json: bool) -> None:
    """Stop the detached gateway process."""
    config: AppConfig = ctx.obj["config"]
    state = _load_gateway_state(config)
    pid = int(state.get("pid") or 0) if str(state.get("pid") or "").strip() else 0
    if pid <= 0:
        payload = {"ok": False, "error": "no gateway pid in state", "state_file": str(_gateway_state_file(config))}
        if as_json:
            click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
            return
        raise click.ClickException(str(payload["error"]))
    running = _is_pid_running(pid)
    killed = False
    if running:
        killed = _kill_pid(pid)
        if not killed and not _is_pid_running(pid):
            killed = True
    _clear_gateway_state(config)
    payload = {"ok": bool((not _is_pid_running(pid)) and ((not running) or killed)), "pid": pid, "was_running": running, "killed": killed}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"pid: {pid}")
    click.echo(f"was_running: {running}")
    click.echo(f"killed: {killed}")
    click.echo(f"ok: {payload['ok']}")


@gateway.command("logs")
@click.option("--lines", default=120, show_default=True, type=int, help="Number of tail lines.")
@click.pass_context
def gateway_logs(ctx: click.Context, lines: int) -> None:
    """Print recent gateway log lines."""
    config: AppConfig = ctx.obj["config"]
    state = _load_gateway_state(config)
    log_file = Path(str(state.get("log_file") or _gateway_log_file(config)))
    if not log_file.exists():
        raise click.ClickException(f"Gateway log file not found: {log_file}")
    tail = _tail_file(log_file, lines=max(1, int(lines)))
    click.echo(tail)


@gateway.command("url")
@click.option("--host", default=None, help="Override host.")
@click.option("--port", default=None, type=int, help="Override port.")
@click.pass_context
def gateway_url(ctx: click.Context, host: Optional[str], port: Optional[int]) -> None:
    """Print gateway UI URL."""
    config: AppConfig = ctx.obj["config"]
    use_host, use_port, _state = _active_gateway_target(config, host, port)
    click.echo(f"http://{use_host}:{int(use_port)}/")


register_pack_proxy_commands(
    gateway,
    package="thomas.cli.commands.gateway",
    family_hint="gateway",
)


@click.command(name="dashboard")
@click.option("--open/--print-only", default=True, show_default=True, help="Open the UI in your browser.")
@click.option("--host", default=None, help="Override host.")
@click.option("--port", default=None, type=int, help="Override port.")
@click.pass_context
def dashboard(ctx: click.Context, open: bool, host: Optional[str], port: Optional[int]) -> None:
    """Open the local dashboard UI."""
    config: AppConfig = ctx.obj["config"]
    use_host, use_port, _state = _active_gateway_target(config, host, port)
    url = f"http://{use_host}:{int(use_port)}/"
    if open:
        try:
            webbrowser.open(url, new=2)
        except Exception as e:
            click.echo(f"Failed to open browser: {type(e).__name__}: {e}", err=True)
    click.echo(url)


@click.command(name="health")
@click.option("--host", default=None, help="Override host.")
@click.option("--port", default=None, type=int, help="Override port.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def health_cmd(ctx: click.Context, host: Optional[str], port: Optional[int], as_json: bool) -> None:
    """Fetch gateway health details."""
    config: AppConfig = ctx.obj["config"]
    use_host, use_port, _state = _active_gateway_target(config, host, port)
    payload = _probe_gateway(use_host, use_port, token=config.server.api_token)
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"url: {payload.get('base_url')}")
    click.echo(f"healthy: {payload.get('healthy')}")
    click.echo(f"tcp_open: {payload.get('tcp_open')}")
    version = payload.get("version", {})
    models = payload.get("models", {})
    engines = payload.get("engines", {})
    click.echo(f"/api/version -> ok={version.get('ok')} status={version.get('status')}")
    click.echo(f"/api/models -> ok={models.get('ok')} status={models.get('status')}")
    click.echo(f"/api/engines -> ok={engines.get('ok')} status={engines.get('status')}")


def _sessions_count(config: AppConfig) -> int:
    root = config.memory.root_path / ".thomas" / "chats"
    if not root.exists():
        return 0
    return len(list(root.glob("*.json")))


@click.command(name="status")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def status_cmd(ctx: click.Context, as_json: bool) -> None:
    """Show top-level Thomas status summary."""
    config: AppConfig = ctx.obj["config"]
    channel_store = _read_json(config.memory.root_path / ".thomas" / "channels.json", {"providers": {}})
    providers = channel_store.get("providers", {}) if isinstance(channel_store, dict) else {}
    if not isinstance(providers, dict):
        providers = {}

    def _provider_configured(name: str, token_env: str, webhook_env: str = "") -> bool:
        token = str(os.environ.get(token_env) or "").strip()
        webhook = str(os.environ.get(webhook_env) or "").strip() if webhook_env else ""
        row = providers.get(name, {})
        if isinstance(row, dict):
            token = token or str(row.get("token") or "").strip()
            webhook = webhook or str(row.get("webhook") or "").strip()
        return bool(token or webhook)

    cfg_telegram = _provider_configured("telegram", "THOMAS_TELEGRAM_BOT_TOKEN")
    cfg_discord = _provider_configured("discord", "THOMAS_DISCORD_BOT_TOKEN", "THOMAS_DISCORD_WEBHOOK_URL")
    cfg_slack = _provider_configured("slack", "THOMAS_SLACK_BOT_TOKEN", "THOMAS_SLACK_WEBHOOK_URL")
    channels_payload = {"telegram_configured": bool(cfg_telegram), "discord_configured": bool(cfg_discord), "slack_configured": bool(cfg_slack), "configured_count": int(bool(cfg_telegram)) + int(bool(cfg_discord)) + int(bool(cfg_slack)), "total_count": 3}
    host, port, state = _active_gateway_target(config, None, None)
    pid = int(state.get("pid") or 0) if str(state.get("pid") or "").strip() else 0
    process_running = bool(pid > 0 and _is_pid_running(pid))
    probe = _probe_gateway(host, port, token=config.server.api_token)
    payload = {
        "models": {"count": len(config.models), "default": str(config.default_model or "")},
        "channels": channels_payload,
        "gateway": {"pid": pid, "process_running": process_running, "url": f"http://{host}:{int(port)}/", "healthy": bool(probe.get("healthy", False))},
        "sessions": {"count": _sessions_count(config)},
        "quality": {"enabled": bool(config.quality.enabled), "enforce": bool(config.quality.enforce), "require_verification_for_coding": bool(config.quality.require_verification_for_coding), "require_tests_for_code_edits": bool(config.quality.require_tests_for_code_edits), "require_monolith_guard_for_coding": bool(config.quality.require_monolith_guard_for_coding)},
    }
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"models: {payload['models']['count']} (default={payload['models']['default']})")
    click.echo(f"channels: {payload['channels']['configured_count']}/{payload['channels']['total_count']} configured")
    click.echo(f"gateway: running={payload['gateway']['process_running']}, healthy={payload['gateway']['healthy']}, url={payload['gateway']['url']}")
    click.echo(f"sessions: {payload['sessions']['count']}")
    click.echo(f"quality: enabled={payload['quality']['enabled']}, enforce={payload['quality']['enforce']}, verify={payload['quality']['require_verification_for_coding']}, tests={payload['quality']['require_tests_for_code_edits']}, monolith_guard={payload['quality']['require_monolith_guard_for_coding']}")


def register_parity_commands(cli: click.Group) -> None:
    """Register parity command families on the main CLI group."""
    from thomas.cli.parity_compat import register_compat_commands

    commands = [
        agents,
        devices,
        sandbox,
        plugins,
        gateway,
        dashboard,
        status_cmd,
        health_cmd,
    ]
    for cmd in commands:
        name = str(getattr(cmd, "name", "") or "").strip()
        if not name:
            continue
        if name in cli.commands:
            continue
        cli.add_command(cmd)

    register_compat_commands(cli)
