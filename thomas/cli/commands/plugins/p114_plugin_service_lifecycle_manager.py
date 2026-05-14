from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import typer

from thomas.plugins.p114_plugin_service_lifecycle_manager import (
    SERVICE_LIFECYCLE_REQUEST_SCHEMA,
    SERVICE_LIFECYCLE_RESPONSE_SCHEMA,
    InvalidInputError,
    LifecycleAction,
    MissingConfigError,
    PluginServiceLifecycleManager,
    ServiceLifecycleError,
    ServiceLifecycleRequest,
    apply_lifecycle_request,
    parse_lifecycle_request,
)

app = typer.Typer(help="Manage lifecycle of plugin-defined background services.")


def _resolve_manager(ctx: typer.Context) -> PluginServiceLifecycleManager:
    """Resolve the service manager from a CLI context object.

    The Thomas CLI typically populates `ctx.obj` with an application context.
    We keep this best-effort and dependency-free (duck-typing) so importing this
    module has no heavy side effects.
    """
    obj = getattr(ctx, "obj", None)
    if obj is None:
        raise MissingConfigError("No CLI context object is available (ctx.obj is missing).")

    # Allow ctx.obj to be a dict-like container.
    if isinstance(obj, dict):
        for key in ("plugin_service_manager", "service_manager", "services_manager"):
            candidate = obj.get(key)
            if candidate is None:
                continue
            if isinstance(candidate, PluginServiceLifecycleManager):
                return candidate
            if all(hasattr(candidate, name) for name in ("start", "stop", "list_status")):
                return candidate  # type: ignore[return-value]

    # Common attribute names a host app might provide.
    for attr in ("plugin_service_manager", "service_manager", "services_manager"):
        candidate = getattr(obj, attr, None)
        if candidate is None:
            continue
        if isinstance(candidate, PluginServiceLifecycleManager):
            return candidate
        if all(hasattr(candidate, name) for name in ("start", "stop", "list_status")):
            return candidate  # type: ignore[return-value]

    raise MissingConfigError("No plugin service manager found in CLI context.")


def _emit(payload: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(payload, sort_keys=True))
        return

    if payload.get("ok") is True:
        services = payload.get("services", [])
        if not services:
            typer.echo("No services.")
            return
        for s in services:
            typer.echo(f"{s.get('service_id')}: {s.get('state')}")
        return

    err = payload.get("error") or {}
    typer.echo(f"ERROR [{err.get('code')}]: {err.get('message')}")


def _fail(err: ServiceLifecycleError, *, json_mode: bool) -> None:
    _emit({"ok": False, "services": [], "error": err.to_dict()}, json_mode=json_mode)
    raise typer.Exit(code=2)


def _run(coro: Any) -> Any:
    # Typer commands run in sync context, so this is generally safe.
    return asyncio.run(coro)


@app.command("schema")
def schema(
    json_mode: bool = typer.Option(False, "--json", help="Emit schema as JSON."),
) -> None:
    """Print the machine-readable schema for lifecycle requests and responses."""
    payload = {"request": SERVICE_LIFECYCLE_REQUEST_SCHEMA, "response": SERVICE_LIFECYCLE_RESPONSE_SCHEMA}
    if json_mode:
        typer.echo(json.dumps(payload, sort_keys=True))
        return

    typer.echo("Request schema:")
    typer.echo(json.dumps(SERVICE_LIFECYCLE_REQUEST_SCHEMA, indent=2, sort_keys=True))
    typer.echo("\nResponse schema:")
    typer.echo(json.dumps(SERVICE_LIFECYCLE_RESPONSE_SCHEMA, indent=2, sort_keys=True))


@app.command("apply")
def apply(
    ctx: typer.Context,
    request_json: str | None = typer.Option(
        None,
        "--request",
        "-r",
        help="JSON request body (if omitted, reads from stdin).",
    ),
    json_mode: bool = typer.Option(True, "--json/--no-json", help="Emit machine-readable JSON output."),
) -> None:
    """Apply an arbitrary lifecycle request (automation-friendly).

    Reads a JSON object either from --request or stdin and returns a JSON response.
    """
    try:
        manager = _resolve_manager(ctx)

        raw = request_json
        if raw is None:
            raw = sys.stdin.read()
        if not raw or not raw.strip():
            raise InvalidInputError("No request provided.")

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise InvalidInputError("Request must be valid JSON.", details={"error": str(exc)}) from None

        if not isinstance(data, dict):
            raise InvalidInputError("Request JSON must be an object.", details={"type": type(data).__name__})

        req = parse_lifecycle_request(data)
        resp = _run(apply_lifecycle_request(manager, req))
        payload = resp.to_dict()
        _emit(payload, json_mode=json_mode)
        if not resp.ok:
            raise typer.Exit(code=2)
    except ServiceLifecycleError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("list")
def list_services(
    ctx: typer.Context,
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """List known services and their status."""
    try:
        manager = _resolve_manager(ctx)
        resp = _run(apply_lifecycle_request(manager, ServiceLifecycleRequest(action=LifecycleAction.LIST)))
        payload = resp.to_dict()
        _emit(payload, json_mode=json_mode)
        if not resp.ok:
            raise typer.Exit(code=2)
    except ServiceLifecycleError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("status")
def status(
    ctx: typer.Context,
    service_id: str | None = typer.Argument(None, help="Service id to query (omit for all)."),
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Get status for a service, or all services if service_id is omitted."""
    try:
        manager = _resolve_manager(ctx)
        req = (
            ServiceLifecycleRequest(action=LifecycleAction.STATUS, service_id=service_id)
            if service_id
            else ServiceLifecycleRequest(action=LifecycleAction.LIST)
        )
        resp = _run(apply_lifecycle_request(manager, req))
        payload = resp.to_dict()
        _emit(payload, json_mode=json_mode)
        if not resp.ok:
            raise typer.Exit(code=2)
    except ServiceLifecycleError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("start")
def start(
    ctx: typer.Context,
    service_id: str = typer.Argument(..., help="Service id to start."),
    timeout_s: float | None = typer.Option(None, "--timeout", min=0, help="Optional start timeout (seconds)."),
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Start a single service."""
    try:
        manager = _resolve_manager(ctx)
        req = ServiceLifecycleRequest(action=LifecycleAction.START, service_id=service_id, timeout_s=timeout_s)
        resp = _run(apply_lifecycle_request(manager, req))
        payload = resp.to_dict()
        _emit(payload, json_mode=json_mode)
        if not resp.ok:
            raise typer.Exit(code=2)
    except ServiceLifecycleError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("stop")
def stop(
    ctx: typer.Context,
    service_id: str = typer.Argument(..., help="Service id to stop."),
    timeout_s: float | None = typer.Option(None, "--timeout", min=0, help="Optional stop timeout (seconds)."),
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Stop a single service."""
    try:
        manager = _resolve_manager(ctx)
        req = ServiceLifecycleRequest(action=LifecycleAction.STOP, service_id=service_id, timeout_s=timeout_s)
        resp = _run(apply_lifecycle_request(manager, req))
        payload = resp.to_dict()
        _emit(payload, json_mode=json_mode)
        if not resp.ok:
            raise typer.Exit(code=2)
    except ServiceLifecycleError as exc:
        _fail(exc, json_mode=json_mode)


@app.command("restart")
def restart(
    ctx: typer.Context,
    service_id: str = typer.Argument(..., help="Service id to restart."),
    timeout_s: float | None = typer.Option(None, "--timeout", min=0, help="Optional stop/start timeout (seconds)."),
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Restart a single service."""
    try:
        manager = _resolve_manager(ctx)
        req = ServiceLifecycleRequest(action=LifecycleAction.RESTART, service_id=service_id, timeout_s=timeout_s)
        resp = _run(apply_lifecycle_request(manager, req))
        payload = resp.to_dict()
        _emit(payload, json_mode=json_mode)
        if not resp.ok:
            raise typer.Exit(code=2)
    except ServiceLifecycleError as exc:
        _fail(exc, json_mode=json_mode)


def register(parent_app: typer.Typer) -> None:  # pragma: no cover
    """Register this command group under a parent Typer app."""
    parent_app.add_typer(app, name="service-lifecycle")


# Provide a click.Command entrypoint for click-native callers/tests.
click_app = typer.main.get_command(app)

# Compatibility aliases for potential CLI discovery code.
APP = app
COMMAND = click_app

__all__ = ["app", "APP", "click_app", "COMMAND", "register"]
