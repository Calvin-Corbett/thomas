from __future__ import annotations

import json
import sys
import inspect
from dataclasses import dataclass
from typing import Any, Optional

import typer

from thomas.nodes.p052_nodes_cli_integration_and_parity_tests import (
    NodesCliIntegrationError,
    NodesCliRequest,
    fetch_nodes_sync,
    format_result_human,
    format_result_json,
    run_parity_tests_sync,
)

# Primary Typer app (some registries look specifically for an `app` attribute).
app = typer.Typer(
    help="Interact with Thomas nodes/devices and run parity checks for automation.",
    add_completion=False,
)

# Friendly alias.
nodes_app = app

CLI_NAMES = ("nodes", "devices")

__all__ = [
    "app",
    "nodes_app",
    "CLI_NAMES",
    "register_cli",
    "register",
    "get_parity_specs",
    "wire_into_cli",
]


def _emit(payload: str) -> None:
    typer.echo(payload)


def _emit_json(obj: Any) -> None:
    _emit(json.dumps(obj, sort_keys=True))


def _error_payload(err: NodesCliIntegrationError) -> dict[str, Any]:
    return {"ok": False, "error": err.to_dict()}


def _success_payload(result_json: str) -> str:
    # result_json is already a JSON string; wrap it deterministically.
    try:
        result_obj = json.loads(result_json)
    except Exception:
        result_obj = {"raw": result_json}
    return json.dumps({"ok": True, **result_obj}, sort_keys=True)


@app.command("list")
def list_nodes(
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Thomas server base URL."),
    nodes_path: Optional[str] = typer.Option(None, "--nodes-path", help="Override nodes endpoint path."),
    timeout_s: float = typer.Option(10.0, "--timeout", min=0.1, help="Request timeout (seconds)."),
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """List nodes/devices from the Thomas server."""
    try:
        result = fetch_nodes_sync(NodesCliRequest(base_url=base_url, nodes_path=nodes_path, timeout_s=timeout_s))
    except NodesCliIntegrationError as e:
        if json_mode:
            _emit_json(_error_payload(e))
        else:
            _emit(f"ERROR[{e.code}]: {e.message}")
        raise typer.Exit(code=2) from e

    if json_mode:
        _emit(_success_payload(format_result_json(result)))
    else:
        _emit(format_result_human(result))


@app.command("parity")
def parity_tests(
    base_url: Optional[str] = typer.Option(None, "--base-url", help="Thomas server base URL."),
    nodes_path: Optional[str] = typer.Option(None, "--nodes-path", help="Override nodes endpoint path."),
    timeout_s: float = typer.Option(10.0, "--timeout", min=0.1, help="Request timeout (seconds)."),
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Run parity checks for the nodes endpoint (schema + reachability)."""
    try:
        result = run_parity_tests_sync(NodesCliRequest(base_url=base_url, nodes_path=nodes_path, timeout_s=timeout_s))
    except NodesCliIntegrationError as e:
        if json_mode:
            _emit_json(_error_payload(e))
        else:
            _emit(f"ERROR[{e.code}]: {e.message}")
        raise typer.Exit(code=2) from e

    if json_mode:
        _emit(_success_payload(format_result_json(result)))
    else:
        _emit("OK")


@dataclass(frozen=True)
class CliHttpParitySpec:
    """Lightweight parity spec for registries/tests."""
    name: str
    cli: list[str]
    method: str
    path_hint: str


def get_parity_specs() -> list[dict[str, Any]]:
    """Expose parity specs in a registry-friendly shape.

    We intentionally keep this as a list of plain dicts so that tests/registries don't need
    to import dataclass types from this module.
    """
    specs = [
        CliHttpParitySpec(name="nodes_list", cli=["nodes", "list"], method="GET", path_hint="nodes/devices endpoint"),
        CliHttpParitySpec(name="nodes_parity", cli=["nodes", "parity"], method="GET", path_hint="nodes/devices endpoint"),
    ]
    return [spec.__dict__ for spec in specs]


def _register_typer(root_app: typer.Typer) -> None:
    for name in CLI_NAMES:
        try:
            root_app.add_typer(app, name=name)
        except Exception:
            # Avoid failing CLI import if another module already registered it.
            continue


def _register_click(root_group: Any) -> None:
    try:
        import click
        from typer.main import get_command
    except Exception:
        return

    if not isinstance(root_group, click.Group):
        return

    cmd = get_command(app)
    for name in CLI_NAMES:
        if name in root_group.commands:
            continue
        try:
            root_group.add_command(cmd, name=name)
        except Exception:
            continue


def register_cli(root: Any) -> None:
    """Register the nodes commands onto a root CLI object (Typer or click.Group)."""
    if isinstance(root, typer.Typer):
        _register_typer(root)
        return
    _register_click(root)


# Common alias used by some registries.
register = register_cli


# --- main.py integration hook (best effort, minimal footprint) ---

_PATCHES_INSTALLED = False
_ORIG_TYPER_INIT = None
_ORIG_CLICK_GROUP_INIT = None


def wire_into_cli() -> None:
    """Best-effort wiring into thomas.cli.main.

    We support two common CLI construction styles:
    - Typer root app: app = typer.Typer(); app.add_typer(...)
    - click root group: cli = click.Group(); cli.add_command(...)

    Since we cannot assume the variable name of the root object, we attempt:
    1) immediate registration if thomas.cli.main already exposes a root object
    2) a narrow init-hook on Typer/click Group that registers when constructed from thomas.cli.main

    The init-hooks are intentionally narrow: they only act when the caller module is thomas.cli.main.
    """
    global _PATCHES_INSTALLED, _ORIG_TYPER_INIT, _ORIG_CLICK_GROUP_INIT

    # 1) Attempt immediate registration if thomas.cli.main already has a root app/group.
    main_mod = sys.modules.get("thomas.cli.main")
    if main_mod is not None:
        for attr in ("app", "cli", "root_app", "typer_app"):
            root_obj = getattr(main_mod, attr, None)
            if isinstance(root_obj, typer.Typer):
                _register_typer(root_obj)
                break
            _register_click(root_obj)

    # 2) Install init-hooks exactly once per process.
    if _PATCHES_INSTALLED:
        return
    _PATCHES_INSTALLED = True

    if _ORIG_TYPER_INIT is None:
        _ORIG_TYPER_INIT = typer.Typer.__init__  # type: ignore[assignment]

        def _patched_typer_init(self: typer.Typer, *args: Any, **kwargs: Any) -> None:
            _ORIG_TYPER_INIT(self, *args, **kwargs)  # type: ignore[misc]
            try:
                frame = inspect.currentframe()
                caller = frame.f_back if frame else None
                caller_mod = (caller.f_globals.get("__name__") if caller else "") or ""
            finally:
                # break reference cycles
                del frame
                del caller

            if caller_mod == "thomas.cli.main" and not getattr(self, "_p052_nodes_registered", False):
                _register_typer(self)
                setattr(self, "_p052_nodes_registered", True)

        typer.Typer.__init__ = _patched_typer_init  # type: ignore[assignment]

    try:
        import click
    except Exception:
        return

    if _ORIG_CLICK_GROUP_INIT is None:
        _ORIG_CLICK_GROUP_INIT = click.Group.__init__  # type: ignore[assignment]

        def _patched_click_group_init(self: Any, *args: Any, **kwargs: Any) -> None:
            _ORIG_CLICK_GROUP_INIT(self, *args, **kwargs)  # type: ignore[misc]
            try:
                frame = inspect.currentframe()
                caller = frame.f_back if frame else None
                caller_mod = (caller.f_globals.get("__name__") if caller else "") or ""
            finally:
                del frame
                del caller

            if caller_mod == "thomas.cli.main" and not getattr(self, "_p052_nodes_registered", False):
                _register_click(self)
                setattr(self, "_p052_nodes_registered", True)

        click.Group.__init__ = _patched_click_group_init  # type: ignore[assignment]


# Wire on import so main.py can simply import this module, but keep this function callable too.
wire_into_cli()
