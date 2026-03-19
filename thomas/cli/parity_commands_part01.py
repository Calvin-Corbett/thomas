"""Additional CLI command families for high-visibility OpenClaw parity."""

from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

import click

from thomas.cli.agents_runtime import (
    engine_snapshot as _engine_snapshot,
)
from thomas.cli.agents_runtime import (
    start_payload as _agents_start_payload,
)
from thomas.cli.agents_runtime import (
    status_payload as _agents_status_payload,
)
from thomas.cli.agents_runtime import (
    stop_payload as _agents_stop_payload,
)
from thomas.cli.pack_bridge import register_pack_proxy_commands
from thomas.cli.parity_gateway_support import (
    parse_json_file as _parse_json_file,
)
from thomas.cli.parity_support import (
    emit_json_or_text as _emit_json_or_text,
)
from thomas.cli.parity_support import (
    read_json as _read_json,
)
from thomas.cli.parity_support import (
    state_dir as _state_dir,
)
from thomas.cli.parity_support import (
    utc_iso as _utc_iso,
)
from thomas.cli.parity_support import (
    write_json as _write_json,
)
from thomas.core.config import AppConfig


@click.group()
@click.pass_context
def agents(ctx: click.Context) -> None:
    """Manage internal agent engines and role visibility."""
    _ = ctx


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
@click.option("--host", default=None, help="Override probe host.")
@click.option("--port", default=None, type=int, help="Override probe port.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def agents_status(ctx: click.Context, host: str | None, port: int | None, as_json: bool) -> None:
    """Show internal agent engine status."""
    config: AppConfig = ctx.obj["config"]
    payload = _agents_status_payload(config, host=host, port=port)
    source = str(payload.get("source") or "")
    engines = payload.get("engines")
    if not isinstance(engines, dict):
        engines = {}
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"running: {bool(payload.get('running', False))}")
    click.echo(f"source: {source}")
    gateway = payload.get("gateway_detached", {})
    if isinstance(gateway, dict):
        click.echo(f"gateway_url: {gateway.get('url')}")
        click.echo(f"gateway_process_running: {gateway.get('process_running')}")
        click.echo(f"gateway_healthy: {bool((gateway.get('probe') or {}).get('healthy', False))}")
    for name, row in engines.items():
        if isinstance(row, dict):
            click.echo(
                f"- {name}: running={bool(row.get('running', False))}, "
                f"cycles={int(row.get('cycles_completed', 0) or 0)}, "
                f"error={str(row.get('error') or '')}"
            )


@agents.command("start")
@click.option(
    "--detach/--in-process", default=True, show_default=True, help="Run detached via gateway for persistent runtime."
)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=8899, show_default=True, type=int)
@click.option("--auto-port/--strict-port", default=True, show_default=True)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def agents_start(
    ctx: click.Context,
    detach: bool,
    host: str,
    port: int,
    auto_port: bool,
    as_json: bool,
) -> None:
    """Start all internal background agent engines."""
    config: AppConfig = ctx.obj["config"]
    payload = _agents_start_payload(
        config,
        config_path=str(ctx.obj.get("config_path") or ""),
        detach=bool(detach),
        host=str(host),
        port=int(port),
        auto_port=bool(auto_port),
    )
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"ok: {bool(payload.get('ok', False))}")
    click.echo(f"mode: {payload.get('mode')}")
    if payload.get("mode") == "gateway_detached":
        click.echo(f"pid: {payload.get('pid')}")
        click.echo(f"url: {payload.get('url')}")
        click.echo(f"healthy: {payload.get('healthy')}")
    elif payload.get("ok"):
        started = payload.get("started", {})
        if isinstance(started, dict):
            for name, ok in started.items():
                click.echo(f"- {name}: {'started' if ok else 'failed'}")
    else:
        click.echo(f"error: {payload.get('error')}")


@agents.command("stop")
@click.option(
    "--detach/--in-process",
    default=True,
    show_default=True,
    help="Stop detached gateway runtime or in-process engines.",
)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def agents_stop(ctx: click.Context, detach: bool, as_json: bool) -> None:
    """Stop all internal background agent engines."""
    config: AppConfig = ctx.obj["config"]
    payload = _agents_stop_payload(config, detach=bool(detach))
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    click.echo(f"ok: {bool(payload.get('ok', False))}")
    click.echo(f"mode: {payload.get('mode')}")
    if payload.get("mode") == "gateway_detached":
        if "pid" in payload:
            click.echo(f"pid: {payload.get('pid')}")
        if "was_running" in payload:
            click.echo(f"was_running: {payload.get('was_running')}")
        if "killed" in payload:
            click.echo(f"killed: {payload.get('killed')}")
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


def _find_plugin(rows: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
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


@plugins.command("certify")
@click.option(
    "--required-capability",
    "required_capabilities",
    multiple=True,
    help="Required capability for certification (repeatable).",
)
@click.option(
    "--min-pass-rate",
    type=float,
    default=0.95,
    show_default=True,
    help="Minimum certification pass rate.",
)
@click.option("--strict", is_flag=True, help="Exit non-zero when certification fails.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def plugins_certify(
    required_capabilities: tuple[str, ...],
    min_pass_rate: float,
    strict: bool,
    as_json: bool,
) -> None:
    """Run extension certification with capability and pass-rate gates."""
    from thomas.plugins.certification import certify_extension_catalog

    payload = certify_extension_catalog(
        required_capabilities=list(required_capabilities or []),
        min_pass_rate=float(min_pass_rate),
    )
    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
        click.echo(f"result: {'ok' if payload.get('ok') else 'failed'}")
        click.echo(f"catalog: {payload.get('catalog_path')}")
        click.echo(f"total: {summary.get('total', 0)}")
        click.echo(f"certified: {summary.get('certified', 0)}")
        click.echo(f"uncertified: {summary.get('uncertified', 0)}")
        click.echo(f"pass_rate: {summary.get('pass_rate', 0.0)}")
        required = (
            payload.get("required_capabilities") if isinstance(payload.get("required_capabilities"), list) else []
        )
        click.echo("required_capabilities: " + ", ".join(str(x) for x in required))
    if strict and not bool(payload.get("ok")):
        raise SystemExit(1)


@plugins.command("update")
@click.option("--include-prereleases", is_flag=True, help="Consider prerelease versions when planning updates.")
@click.option(
    "--strict",
    is_flag=True,
    help="Exit non-zero when recommended updates or unknown versions are present.",
)
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.pass_context
def plugins_update(
    ctx: click.Context,
    include_prereleases: bool,
    strict: bool,
    as_json: bool,
) -> None:
    """Plan plugin updates using local install state + extension catalog."""
    from thomas.plugins.certification import build_plugin_update_plan_from_state

    config: AppConfig = ctx.obj["config"]
    rows = _load_plugins(config)
    payload = build_plugin_update_plan_from_state(rows, include_prereleases=bool(include_prereleases))

    summary = payload.get("summary") if isinstance(payload.get("summary"), dict) else {}
    actions = payload.get("actions") if isinstance(payload.get("actions"), list) else []
    recommended_updates = sum(1 for row in actions if bool((row or {}).get("recommended", False)))
    payload["recommended_updates"] = int(recommended_updates)

    if as_json:
        click.echo(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        click.echo(f"catalog_root: {payload.get('catalog_root', '')}")
        click.echo(f"total: {summary.get('total', 0)}")
        click.echo(f"update: {summary.get('update', 0)}")
        click.echo(f"up_to_date: {summary.get('up_to_date', 0)}")
        click.echo(f"unknown: {summary.get('unknown', 0)}")
        click.echo(f"recommended_updates: {recommended_updates}")
        for row in actions[:25]:
            click.echo(
                f"- {row.get('id')} | {row.get('status')} | "
                f"{row.get('current_version')} -> {row.get('latest_version')} | "
                f"recommended={bool(row.get('recommended', False))}"
            )
        if len(actions) > 25:
            click.echo(f"... {len(actions) - 25} more")

    if strict and (int(recommended_updates) > 0 or int(summary.get("unknown") or 0) > 0):
        raise SystemExit(1)


_PLUGIN_BOOTSTRAP_MODULES = (
    "thomas.cli.commands.plugins.p097_plugin_package_bootstrap",
    "thomas.cli.commands.plugins.p098_plugin_manifest_schema",
    "thomas.cli.commands.plugins.p100_plugin_discovery_scanner",
    "thomas.cli.commands.plugins.p101_plugin_enable_and_disable_state_store",
    "thomas.cli.commands.plugins.p102_plugin_install_from_local_path",
    "thomas.cli.commands.plugins.p103_plugin_uninstall_cleanup",
    "thomas.cli.commands.plugins.p104_plugin_update_planner",
    "thomas.cli.commands.plugins.p105_plugin_registry_core_model",
    "thomas.cli.commands.plugins.p106_plugin_command_registry_bridge",
    "thomas.cli.commands.plugins.p107_plugin_hook_types_contract",
    "thomas.cli.commands.plugins.p108_plugin_hook_runner_core",
    "thomas.cli.commands.plugins.p109_plugin_hook_before_model",
    "thomas.cli.commands.plugins.p110_plugin_hook_before_tool",
    "thomas.cli.commands.plugins.p111_plugin_hook_after_tool",
    "thomas.cli.commands.plugins.p112_plugin_hook_after_response",
    "thomas.cli.commands.plugins.p113_plugin_tool_provider_injection",
    "thomas.cli.commands.plugins.p114_plugin_service_lifecycle_manager",
    "thomas.cli.commands.plugins.p115_plugin_gateway_handler_registry",
    "thomas.cli.commands.plugins.p116_plugin_http_route_registry",
    "thomas.cli.commands.plugins.p117_plugin_config_schema_validator",
    "thomas.cli.commands.plugins.p118_plugin_diagnostics_collector",
    "thomas.cli.commands.plugins.p119_plugin_doctor_command",
    "thomas.cli.commands.plugins.p120_plugin_info_command",
    "thomas.cli.commands.plugins.p121_plugin_list_command_runtime_backed",
    "thomas.cli.commands.plugins.p122_plugin_lifecycle_commands_runtime_backed",
    "thomas.cli.commands.plugins.p123_sample_plugin_skeleton_extension",
)

register_pack_proxy_commands(
    plugins,
    package="thomas.cli.commands.plugins",
    family_hint="plugin",
    allowlisted_modules=_PLUGIN_BOOTSTRAP_MODULES,
)


@click.group()
@click.pass_context
def sandbox(ctx: click.Context) -> None:
    """Manage local sandbox execution and tests."""
    _ = ctx


def _resolve_code_input(code: str | None, file_path: str | None) -> str:
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
    code: str | None,
    file_path: str | None,
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
    code: str | None,
    file_path: str | None,
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
