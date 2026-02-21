from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, Optional, Sequence

from thomas.browser.p018_browser_tab_management import (
    BrowserTabManagementError,
    InvalidTabRequestError,
    TabBackend,
    TabBackendError,
    TabConfigError,
    TabManagementRequest,
    TabManagementResponse,
    TabNotFoundError,
    coerce_tab_backend,
    manage_tabs,
)

# Thomas-native command name (used by discovery systems that mount modules dynamically).
COMMAND = "tabs"


def build_parser(subparsers: argparse._SubParsersAction) -> argparse.ArgumentParser:
    """Register the `tabs` command on an argparse subparser collection.

    Some Thomas deployments use argparse-based command routing; others use Typer.
    This module supports both styles.
    """
    parser = subparsers.add_parser(
        COMMAND,
        help="Manage browser tabs (list/open/activate/close).",
        description="Manage browser tabs (list/open/activate/close).",
    )
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    parser.add_argument(
        "action",
        choices=["list", "open", "activate", "close", "close_all", "close_others"],
        help="Tab action to perform.",
    )
    parser.add_argument("--id", dest="tab_id", default=None, help="Target tab id.")
    parser.add_argument("--index", dest="tab_index", type=int, default=None, help="Target tab index (0-based).")
    parser.add_argument("--url", dest="url", default=None, help="URL to open (open action only).")
    parser.add_argument(
        "--no-activate",
        dest="activate",
        action="store_false",
        help="Do not activate the opened tab (open action only).",
    )
    parser.set_defaults(_thomas_handler=_run_from_argparse)
    return parser


def _run_from_argparse(args: argparse.Namespace, *, backend: Any = None) -> int:
    request = TabManagementRequest(
        action=args.action,
        tab_id=args.tab_id,
        tab_index=args.tab_index,
        url=args.url,
        activate=bool(getattr(args, "activate", True)),
    )
    return _execute_request(request, backend=backend, json_output=bool(args.json))


def _execute_request(request: TabManagementRequest, *, backend: Any, json_output: bool) -> int:
    try:
        tab_backend: Optional[TabBackend]
        if backend is None:
            tab_backend = None
        else:
            tab_backend = coerce_tab_backend(backend)

        response = manage_tabs(request, tab_backend)
        _emit_response(response, json_output=json_output)
        return 0
    except (InvalidTabRequestError, TabNotFoundError, TabConfigError) as exc:
        _emit_error(exc, json_output=json_output)
        return 2
    except TabBackendError as exc:
        _emit_error(exc, json_output=json_output)
        return 1
    except BrowserTabManagementError as exc:
        _emit_error(exc, json_output=json_output)
        return 1


def _emit_response(response: TabManagementResponse, *, json_output: bool) -> None:
    if json_output:
        sys.stdout.write(json.dumps(response.to_dict(), sort_keys=True))
        sys.stdout.write("\n")
        return

    sys.stdout.write(f"Action: {response.action}\n")
    if response.affected_tab:
        sys.stdout.write(f"Affected tab: {response.affected_tab.index} ({response.affected_tab.id})\n")
    if response.closed_tab_ids:
        sys.stdout.write(f"Closed: {', '.join(response.closed_tab_ids)}\n")
    for tab in response.tabs:
        marker = "*" if tab.active else " "
        title = tab.title or ""
        url = tab.url or ""
        sys.stdout.write(f"{marker} [{tab.index}] {title} {url} ({tab.id})\n")


def _emit_error(error: BrowserTabManagementError, *, json_output: bool) -> None:
    payload: Dict[str, Any] = error.to_dict()
    if json_output:
        sys.stdout.write(json.dumps(payload, sort_keys=True))
        sys.stdout.write("\n")
        return

    sys.stderr.write(f"Error ({error.code}): {error.message}\n")
    if error.details:
        sys.stderr.write(json.dumps(error.details, sort_keys=True))
        sys.stderr.write("\n")


def main(argv: Optional[Sequence[str]] = None, *, backend: Any = None) -> int:
    """Standalone entrypoint for local execution/tests.

    In the full Thomas CLI, this module is imported and registered under the parent
    `browser` command/group. This wrapper exists so unit tests can exercise routing
    without needing the entire CLI stack.
    """
    parser = argparse.ArgumentParser(prog="thomas browser")
    subparsers = parser.add_subparsers(dest="command", required=True)
    _ = build_parser(subparsers)
    args = parser.parse_args(argv)

    handler = getattr(args, "_thomas_handler", None)
    if handler is None:
        raise RuntimeError("No handler configured for parsed command.")

    return handler(args, backend=backend)


# ---- Typer integration -----------------------------------------------------------

try:
    import typer
except Exception:  # pragma: no cover
    typer = None  # type: ignore[assignment]


def _ctx_backend(ctx: "typer.Context") -> Any:  # type: ignore[name-defined]
    """Retrieve a backend injected by the parent Thomas CLI (if any)."""
    try:
        obj = ctx.obj
        if isinstance(obj, dict):
            # A few reasonable key guesses for different CLI wiring styles.
            for key in ("tab_backend", "browser_backend", "live_browser", "browser", "backend"):
                if key in obj:
                    return obj.get(key)
    except Exception:
        pass
    return None


if typer is not None:
    app = typer.Typer(help="Manage browser tabs (list/open/activate/close).")

    @app.callback()
    def _callback(
        ctx: typer.Context,
        json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    ) -> None:
        ctx.ensure_object(dict)
        ctx.obj["json"] = json_output

    def _json(ctx: typer.Context) -> bool:
        try:
            return bool(ctx.obj.get("json", False))
        except Exception:
            return False

    @app.command("list")
    def _list(ctx: typer.Context) -> None:
        request = TabManagementRequest(action="list")
        raise typer.Exit(_execute_request(request, backend=_ctx_backend(ctx), json_output=_json(ctx)))

    @app.command("open")
    def _open(
        ctx: typer.Context,
        url: Optional[str] = typer.Option(None, "--url", help="URL to open."),
        activate: bool = typer.Option(True, "--activate/--no-activate", help="Whether to activate the new tab."),
    ) -> None:
        request = TabManagementRequest(action="open", url=url, activate=activate)
        raise typer.Exit(_execute_request(request, backend=_ctx_backend(ctx), json_output=_json(ctx)))

    @app.command("activate")
    def _activate(
        ctx: typer.Context,
        tab_id: Optional[str] = typer.Option(None, "--id", help="Tab id."),
        tab_index: Optional[int] = typer.Option(None, "--index", help="Tab index (0-based)."),
    ) -> None:
        request = TabManagementRequest(action="activate", tab_id=tab_id, tab_index=tab_index)
        raise typer.Exit(_execute_request(request, backend=_ctx_backend(ctx), json_output=_json(ctx)))

    @app.command("close")
    def _close(
        ctx: typer.Context,
        tab_id: Optional[str] = typer.Option(None, "--id", help="Tab id."),
        tab_index: Optional[int] = typer.Option(None, "--index", help="Tab index (0-based)."),
    ) -> None:
        request = TabManagementRequest(action="close", tab_id=tab_id, tab_index=tab_index)
        raise typer.Exit(_execute_request(request, backend=_ctx_backend(ctx), json_output=_json(ctx)))

    @app.command("close-all")
    def _close_all(ctx: typer.Context) -> None:
        request = TabManagementRequest(action="close_all")
        raise typer.Exit(_execute_request(request, backend=_ctx_backend(ctx), json_output=_json(ctx)))

    @app.command("close-others")
    def _close_others(
        ctx: typer.Context,
        tab_id: Optional[str] = typer.Option(None, "--id", help="Tab id to keep."),
        tab_index: Optional[int] = typer.Option(None, "--index", help="Tab index (0-based) to keep."),
    ) -> None:
        request = TabManagementRequest(action="close_others", tab_id=tab_id, tab_index=tab_index)
        raise typer.Exit(_execute_request(request, backend=_ctx_backend(ctx), json_output=_json(ctx)))


def register(parent_app: Any) -> None:
    """Optional hook for CLI auto-registration systems.

    If the Thomas CLI loader looks for a `register(parent_app)` function, this will
    mount this module under `tabs`.
    """
    if typer is None:
        return
    try:
        parent_app.add_typer(app, name=COMMAND)  # type: ignore[attr-defined]
    except Exception:
        # If mounting fails, we keep quiet; the parent CLI may use a different pattern.
        return
