"""
CLI command: browser p007-browser-action-wait-conditions

This command validates and plans "action + wait conditions" specs. It can also
execute the action+waits when a compatible browser driver is available.

Machine-readable output is supported via --json and --schema.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any

import typer

from thomas.browser.p007_browser_action_wait_conditions import (
    BrowserWaitFailureError,
    InvalidWaitConditionsError,
    MissingBrowserDriverError,
    action_with_waits_json_schema,
    action_with_waits_result_json_schema,
    error_to_dict,
    execute_action_with_waits,
    plan_action_with_waits,
    plan_to_dict,
    spec_from_json,
)

COMMAND_NAME = "p007-browser-action-wait-conditions"


def _load_spec_text(spec: str | None, spec_file: Path | None) -> str:
    if spec and spec_file:
        raise InvalidWaitConditionsError("Provide only one of --spec or --spec-file")

    if spec_file is not None:
        try:
            return spec_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            raise InvalidWaitConditionsError(f"Spec file not found: {spec_file}")
        except OSError:
            raise InvalidWaitConditionsError(f"Unable to read spec file: {spec_file}")

    if spec is not None:
        if spec == "-":
            # Read raw JSON spec from stdin.
            return sys.stdin.read()

        # Allow "@path.json" shorthand.
        if spec.startswith("@") and len(spec) > 1:
            return _load_spec_text(None, Path(spec[1:]))

        return spec

    # If nothing was provided, try stdin (useful for automation pipelines).
    if not sys.stdin.isatty():
        text = sys.stdin.read()
        if text.strip():
            return text

    raise InvalidWaitConditionsError("Either --spec or --spec-file is required")


def _emit(result: dict[str, Any], *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return

    # Human-friendly output (kept intentionally minimal for parity tests).
    if result.get("ok"):
        if "input_schema" in result:
            typer.echo("JSON Schema:")
            typer.echo(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
            return

        action = result.get("plan", {}).get("action", {})
        waits = result.get("plan", {}).get("waits", [])
        typer.echo(f"Action: {action.get('method')} {action.get('args')}")
        typer.echo(f"Waits:  {len(waits)}")
        for idx, w in enumerate(waits):
            typer.echo(f"  {idx + 1}. {w.get('method')} args={w.get('args')} kwargs={w.get('kwargs')}")
    else:
        err = result.get("error", {})
        typer.echo(f"Error ({err.get('code')}): {err.get('message')}", err=True)


def _get_page_from_thomas() -> Any:
    """
    Best-effort lookup for a live browser page from the Thomas codebase.

    This intentionally avoids hard dependency on a specific helper name.
    """
    try:
        mod = importlib.import_module("thomas.tools.browser")
    except ImportError:
        raise MissingBrowserDriverError(
            "Browser execution requires a configured driver; run with --dry-run for validation-only"
        )

    # Common helper names across different codebases.
    candidates = [
        "get_page",
        "get_current_page",
        "get_active_page",
        "get_browser_page",
        "page",
    ]
    for name in candidates:
        fn = getattr(mod, name, None)
        if callable(fn):
            page = fn()
            if page is not None:
                return page

    # Sometimes the module exposes a singleton object with a `.page` attribute.
    for name in ["browser", "live_browser", "session", "client"]:
        obj = getattr(mod, name, None)
        page = getattr(obj, "page", None) if obj is not None else None
        if page is not None:
            return page

    raise MissingBrowserDriverError(
        "Browser execution requires a configured driver; no page provider was found in thomas.tools.browser"
    )


def _run(
    spec_text: str | None,
    *,
    dry_run: bool,
    json_mode: bool,
    schema: bool,
) -> int:
    """
    Returns process exit code:
      - 0: success
      - 2: invalid input
      - 1: external/browser failure
    """
    try:
        if schema:
            payload = {
                "ok": True,
                "input_schema": action_with_waits_json_schema(),
                "output_schema": action_with_waits_result_json_schema(),
            }
            _emit(payload, json_mode=json_mode)
            return 0

        if spec_text is None:
            raise InvalidWaitConditionsError("Either --spec or --spec-file is required")

        parsed = spec_from_json(spec_text)
        plan = plan_action_with_waits(parsed)
        payload: dict[str, Any] = {"ok": True, "plan": plan_to_dict(plan)}

        if dry_run:
            _emit(payload, json_mode=json_mode)
            return 0

        page = _get_page_from_thomas()
        execute_action_with_waits(page, parsed)

        payload["executed"] = True
        _emit(payload, json_mode=json_mode)
        return 0

    except InvalidWaitConditionsError as e:
        payload = {"ok": False, "error": error_to_dict(e)}
        _emit(payload, json_mode=json_mode)
        return 2
    except (MissingBrowserDriverError, BrowserWaitFailureError) as e:
        payload = {"ok": False, "error": error_to_dict(e)}
        _emit(payload, json_mode=json_mode)
        return 1


def register_typer(app_obj: typer.Typer) -> None:
    """
    Register the command into a Typer app (idempotent).
    """
    # Prevent double-registration if auto-discovery imports this module multiple times.
    if any(c.name == COMMAND_NAME for c in getattr(app_obj, "registered_commands", [])):
        return

    @app_obj.command(COMMAND_NAME)
    def p007_browser_action_wait_conditions(
        spec: str | None = typer.Option(None, "--spec", help="JSON spec string, @path.json, or '-' for stdin"),
        spec_file: Path | None = typer.Option(None, "--spec-file", exists=False, dir_okay=False, path_type=Path),
        dry_run: bool = typer.Option(True, "--dry-run/--execute", help="Validate+plan only (default) or execute"),
        json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON"),
        schema: bool = typer.Option(False, "--schema", help="Emit JSON schema for automation"),
    ) -> None:
        """
        Validate and (optionally) execute a browser action with explicit wait conditions.
        """
        if schema:
            raise typer.Exit(code=_run(None, dry_run=True, json_mode=json_mode, schema=True))

        spec_text = _load_spec_text(spec, spec_file)
        raise typer.Exit(code=_run(spec_text, dry_run=dry_run, json_mode=json_mode, schema=False))


# Standalone Typer app (fallback for environments that import this module directly).
app = typer.Typer(add_completion=False, help="Browser wait-condition utilities (P007).")
register_typer(app)


# Argparse compatibility hook (some Thomas CLI wiring uses argparse-style registration).
def register(subparsers: Any) -> None:  # pragma: no cover
    """
    Register this command into an argparse subparser collection.

    The host CLI may call this by convention during module discovery.
    """

    parser = subparsers.add_parser(
        COMMAND_NAME,
        help="Validate/execute a browser action with explicit wait conditions (P007).",
    )
    parser.add_argument("--spec", type=str, default=None, help="JSON spec string, @path.json, or '-' for stdin")
    parser.add_argument("--spec-file", type=Path, default=None, help="Path to JSON spec file")
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Validate+plan only (default).",
    )
    parser.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="Execute action+waits (requires configured browser driver).",
    )
    parser.add_argument("--json", dest="json_mode", action="store_true", help="Emit machine-readable JSON")
    parser.add_argument("--schema", action="store_true", help="Emit JSON schema for automation")

    def _handler(args: argparse.Namespace) -> int:
        if args.schema:
            return _run(None, dry_run=True, json_mode=args.json_mode, schema=True)
        spec_text = _load_spec_text(args.spec, args.spec_file)
        return _run(spec_text, dry_run=args.dry_run, json_mode=args.json_mode, schema=False)

    # Common conventions used by various argparse CLIs.
    parser.set_defaults(func=_handler, handler=_handler, run=_handler)


# If the shared browser Typer app exists, register into it.
try:  # pragma: no cover
    from thomas.cli.commands.browser import app as _browser_app  # type: ignore

    if _browser_app is not app:
        register_typer(_browser_app)
except ImportError:
    pass


def main(argv: list[str] | None = None) -> int:
    """Pack-proxy runtime entrypoint."""
    parser = argparse.ArgumentParser(
        prog="browser action-wait-conditions",
        description="Validate/execute browser action specs with wait conditions.",
    )
    parser.add_argument("--spec", type=str, default=None, help="JSON spec string, @path.json, or '-' for stdin")
    parser.add_argument("--spec-file", type=Path, default=None, help="Path to JSON spec file")
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="Validate+plan only (default).",
    )
    parser.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="Execute action+waits (requires configured browser driver).",
    )
    parser.add_argument("--json", dest="json_mode", action="store_true", default=False)
    parser.add_argument("--schema", action="store_true", default=False)
    try:
        args = parser.parse_args(list(argv or []))
    except SystemExit as exc:
        return int(exc.code or 0)

    if bool(args.schema):
        return _run(None, dry_run=True, json_mode=bool(args.json_mode), schema=True)

    try:
        spec_text = _load_spec_text(args.spec, args.spec_file)
    except InvalidWaitConditionsError as exc:
        payload = {
            "ok": False,
            "error": error_to_dict(exc),
            "input_schema": action_with_waits_json_schema(),
            "output_schema": action_with_waits_result_json_schema(),
        }
        _emit(payload, json_mode=bool(args.json_mode))
        return 2
    except Exception as exc:  # pragma: no cover
        payload = {
            "ok": False,
            "error": {"code": "external_failure", "message": str(exc), "details": {"type": type(exc).__name__}},
            "input_schema": action_with_waits_json_schema(),
            "output_schema": action_with_waits_result_json_schema(),
        }
        _emit(payload, json_mode=bool(args.json_mode))
        return 1
    return _run(spec_text, dry_run=bool(args.dry_run), json_mode=bool(args.json_mode), schema=False)
