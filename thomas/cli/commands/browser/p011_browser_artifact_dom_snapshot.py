"""thomas.cli.commands.browser.p011_browser_artifact_dom_snapshot

CLI command for P011: capture a DOM snapshot from the active browser session and
write it as an artifact.

Machine-readable output:
- --json emits a single JSON object to stdout.

This module is designed to be "drop-in" for different Thomas CLI wiring styles:
- When mounted as a Typer sub-app under the "browser" command group, it runs as
  `thomas browser artifact-dom-snapshot ...`.
- It also provides an argparse registration helper for legacy CLI wiring.
"""

from __future__ import annotations

from dataclasses import asdict
import importlib
import json
from pathlib import Path
from typing import Any, Optional

import typer

from thomas.browser.p011_browser_artifact_dom_snapshot import (
    BrowserArtifactDomSnapshotInput,
    BrowserDomSnapshotError,
    browser_artifact_dom_snapshot,
)

COMMAND_NAME = "artifact-dom-snapshot"
COMMAND_HELP = "Capture a DOM snapshot from the active browser and save it as an artifact."

# `invoke_without_command=True` makes this Typer app behave like a *single* command
# when mounted as a sub-app.
app = typer.Typer(add_completion=False, help=COMMAND_HELP, invoke_without_command=True)


def _resolve_active_browser() -> Any:
    """Best-effort resolver for an active browser session.

    The Thomas codebase can expose the active browser in different places
    depending on runtime mode. We probe a few plausible integration points.
    """

    candidates: list[tuple[str, str]] = [
        # CLI/live browser helpers
        ("thomas.cli.live_browser", "get_active_browser"),
        ("thomas.cli.live_browser", "get_browser"),
        ("thomas.cli.live_browser", "get_live_browser"),
        ("thomas.cli.live_browser", "resolve_browser"),
        ("thomas.cli.live_browser", "active_browser"),
        ("thomas.cli.live_browser", "browser"),
        # Tooling helpers
        ("thomas.tools.browser", "get_active_browser"),
        ("thomas.tools.browser", "get_browser"),
        ("thomas.tools.browser", "get_live_browser"),
        ("thomas.tools.browser", "active_browser"),
        ("thomas.tools.browser", "browser"),
    ]

    for mod_name, attr in candidates:
        try:
            mod = importlib.import_module(mod_name)
        except Exception:
            continue

        obj = getattr(mod, attr, None)
        if callable(obj):
            try:
                browser = obj()
            except TypeError:
                continue
            if browser is not None:
                return browser
        elif obj is not None:
            return obj

    raise BrowserDomSnapshotError(
        code="THOMAS_BROWSER_DOM_SNAPSHOT_MISSING_CONFIG",
        category="missing_config",
        message="No active browser session found. Start or attach a browser first.",
    )


def _emit(*, json_mode: bool, payload: dict[str, Any]) -> None:
    if json_mode:
        typer.echo(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        return

    if payload.get("ok"):
        typer.echo(payload.get("artifact_path", ""))
    else:
        typer.echo(f"{payload.get('error_code')}: {payload.get('message')}")


@app.callback()
def main(
    artifacts_dir: Optional[Path] = typer.Option(
        None,
        "--artifacts-dir",
        help="Directory to write the artifact file into (overrides config/env).",
    ),
    output_path: Optional[Path] = typer.Option(
        None,
        "--output",
        help="Explicit output file path (takes precedence over --artifacts-dir).",
    ),
    base_name: Optional[str] = typer.Option(
        None,
        "--base-name",
        help="Filename base used when generating an artifact name.",
    ),
    prefer_cdp: bool = typer.Option(
        True,
        "--prefer-cdp/--no-prefer-cdp",
        help="Prefer Chrome DevTools Protocol DOMSnapshot capture when available.",
    ),
    timeout_ms: int = typer.Option(
        5000,
        "--timeout-ms",
        help="Best-effort timeout for browser capture operations (milliseconds).",
    ),
    json_mode: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON to stdout.",
    ),
) -> None:
    """Capture and write a DOM snapshot artifact."""

    try:
        browser = _resolve_active_browser()
        req = BrowserArtifactDomSnapshotInput(
            artifacts_dir=str(artifacts_dir) if artifacts_dir is not None else None,
            output_path=str(output_path) if output_path is not None else None,
            base_name=base_name,
            prefer_cdp=prefer_cdp,
            timeout_ms=timeout_ms,
        )
        result = browser_artifact_dom_snapshot(browser, req)
        payload = {"ok": True, **asdict(result)}
        _emit(json_mode=json_mode, payload=payload)
    except BrowserDomSnapshotError as e:
        payload = {
            "ok": False,
            "error_code": e.code,
            "category": e.category,
            "message": e.message,
        }
        _emit(json_mode=json_mode, payload=payload)
        raise typer.Exit(code=2)
    except Exception:
        payload = {
            "ok": False,
            "error_code": "THOMAS_BROWSER_DOM_SNAPSHOT_EXTERNAL_FAILURE",
            "category": "external_failure",
            "message": "Unexpected failure while capturing DOM snapshot.",
        }
        _emit(json_mode=json_mode, payload=payload)
        raise typer.Exit(code=3)


# ---- Optional registration hooks ------------------------------------------


def register(target: Any) -> None:
    """Register this command into a parent CLI container.

    Supports both:
    - Typer apps (preferred): target.add_typer(app, name=COMMAND_NAME)
    - argparse subparsers: target.add_parser(...)
    """

    if hasattr(target, "add_typer"):
        try:
            target.add_typer(app, name=COMMAND_NAME)  # type: ignore[attr-defined]
            return
        except Exception:
            # Fall through to argparse registration.
            pass

    if hasattr(target, "add_parser"):
        register_argparse(target)
        return

    raise BrowserDomSnapshotError(
        code="THOMAS_BROWSER_DOM_SNAPSHOT_INVALID_INPUT",
        category="invalid_input",
        message="Unsupported CLI registration target for artifact-dom-snapshot.",
    )


def register_argparse(subparsers: Any) -> None:
    """Register argparse variant for legacy CLI wiring."""

    parser = subparsers.add_parser(COMMAND_NAME, help=COMMAND_HELP, description=COMMAND_HELP)
    parser.add_argument("--artifacts-dir", dest="artifacts_dir", default=None)
    parser.add_argument("--output", dest="output_path", default=None)
    parser.add_argument("--base-name", dest="base_name", default=None)
    parser.add_argument("--prefer-cdp", dest="prefer_cdp", action="store_true", default=True)
    parser.add_argument("--no-prefer-cdp", dest="prefer_cdp", action="store_false")
    parser.add_argument("--timeout-ms", dest="timeout_ms", type=int, default=5000)
    parser.add_argument("--json", dest="json_mode", action="store_true", default=False)
    parser.set_defaults(_thomas_run=run_from_argparse)


def run_from_argparse(args: Any) -> int:
    """Execute via argparse. Returns an exit code."""

    try:
        browser = _resolve_active_browser()
        req = BrowserArtifactDomSnapshotInput(
            artifacts_dir=args.artifacts_dir,
            output_path=args.output_path,
            base_name=args.base_name,
            prefer_cdp=bool(args.prefer_cdp),
            timeout_ms=int(args.timeout_ms),
        )
        result = browser_artifact_dom_snapshot(browser, req)
        payload = {"ok": True, **asdict(result)}
        _emit(json_mode=bool(args.json_mode), payload=payload)
        return 0
    except BrowserDomSnapshotError as e:
        payload = {
            "ok": False,
            "error_code": e.code,
            "category": e.category,
            "message": e.message,
        }
        _emit(json_mode=bool(args.json_mode), payload=payload)
        return 2
    except Exception:
        payload = {
            "ok": False,
            "error_code": "THOMAS_BROWSER_DOM_SNAPSHOT_EXTERNAL_FAILURE",
            "category": "external_failure",
            "message": "Unexpected failure while capturing DOM snapshot.",
        }
        _emit(json_mode=bool(args.json_mode), payload=payload)
        return 3
