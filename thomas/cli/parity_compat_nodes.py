"""Node/nodes compatibility command family extracted from parity_compat."""

from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from pathlib import Path
from typing import Any, Optional

import click

from thomas.cli.pack_bridge import register_pack_proxy_commands


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

