"""CLI: browser lifecycle (start/stop/restart).

Thomas already has browser tooling; this adds explicit lifecycle management commands.

Commands:
- start
- stop
- restart

Automation:
- --json emits machine-readable JSON payloads.
"""

from __future__ import annotations

import json
from typing import Any, Optional

import typer

from thomas.browser.p020_browser_lifecycle_start_stop_restart import (
    BrowserLifecycleError,
    BrowserLifecycleRequest,
    run_browser_lifecycle,
)

app = typer.Typer(help="Manage the browser lifecycle (start/stop/restart).")

_REGISTERED_ON_PARENT = False


def register(parent_app: typer.Typer) -> None:
    """Register start/stop/restart onto an existing `thomas browser` Typer app.

    Some Thomas CLI setups build a browser group app and let submodules attach
    commands via a `register()` hook.
    """

    global _REGISTERED_ON_PARENT
    if _REGISTERED_ON_PARENT:
        return

    # Try to detect existing command names to avoid duplicate registration.
    existing_names: set[str] = set()
    for cmd in getattr(parent_app, "registered_commands", []) or []:
        name = getattr(cmd, "name", None)
        if isinstance(name, str):
            existing_names.add(name)

    for name, fn in (
        ("start", start_cmd),
        ("stop", stop_cmd),
        ("restart", restart_cmd),
    ):
        if name in existing_names:
            continue
        parent_app.command(name)(fn)  # noqa: B026 - Typer decorator style

    _REGISTERED_ON_PARENT = True


# ---- Internal helpers ---------------------------------------------------------


def _emit(payload: Any, *, as_json: bool) -> None:
    if as_json:
        typer.echo(json.dumps(payload, sort_keys=True))
        return

    # Human-friendly output.
    if isinstance(payload, dict) and payload.get("ok") is False and "error" in payload:
        err = payload.get("error")
        if isinstance(err, dict):
            typer.echo(f"{err.get('code')}: {err.get('message')}", err=True)
        else:
            typer.echo(str(err), err=True)
        return

    if isinstance(payload, dict) and payload.get("ok") is True:
        typer.echo(str(payload.get("state")))
        return

    typer.echo(str(payload))


def _run(action: str, *, json_output: bool, timeout_seconds: Optional[float]) -> None:
    try:
        result = run_browser_lifecycle(
            BrowserLifecycleRequest(action=action, timeout_seconds=timeout_seconds)
        )
        _emit(
            result.to_dict() if json_output else {"ok": True, "state": result.state},
            as_json=json_output,
        )
    except BrowserLifecycleError as err:
        _emit(
            err.to_dict()
            if json_output
            else {"ok": False, "error": {"code": err.code, "message": err.message}},
            as_json=json_output,
        )
        raise typer.Exit(code=1) from None


@app.command("start")
def start_cmd(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output.",
    ),
    timeout_seconds: Optional[float] = typer.Option(
        None,
        "--timeout",
        min=0.0,
        help="Optional operation timeout in seconds.",
    ),
) -> None:
    """Start the browser process (idempotent if already running)."""

    _run("start", json_output=json_output, timeout_seconds=timeout_seconds)


@app.command("stop")
def stop_cmd(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output.",
    ),
    timeout_seconds: Optional[float] = typer.Option(
        None,
        "--timeout",
        min=0.0,
        help="Optional operation timeout in seconds.",
    ),
) -> None:
    """Stop the browser process (idempotent if already stopped)."""

    _run("stop", json_output=json_output, timeout_seconds=timeout_seconds)


@app.command("restart")
def restart_cmd(
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output.",
    ),
    timeout_seconds: Optional[float] = typer.Option(
        None,
        "--timeout",
        min=0.0,
        help="Optional operation timeout in seconds.",
    ),
) -> None:
    """Restart the browser process."""

    _run("restart", json_output=json_output, timeout_seconds=timeout_seconds)


# Best-effort auto-registration for codebases that import modules for side effects.
try:  # pragma: no cover
    from thomas.cli.commands import browser as _browser_pkg

    for name in ("app", "browser_app", "typer_app"):
        _parent = getattr(_browser_pkg, name, None)
        if _parent is not None and isinstance(_parent, typer.Typer):
            register(_parent)
            break
except Exception:
    # If the surrounding CLI isn't available (or uses a different pattern),
    # the module still works as a standalone Typer app.
    pass
