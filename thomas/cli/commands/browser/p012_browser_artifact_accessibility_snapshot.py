"""CLI: capture an accessibility snapshot as a browser artifact.

This module is intentionally defensive about Thomas internals: it attempts to
resolve a live browser/page source from a handful of likely locations so the
command can operate across slightly different Thomas configurations.

It also exposes helper registration functions so the command can be wired into
either Typer- or argparse-style CLIs (depending on how the wider codebase is
structured).
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path
from typing import Any, Callable, Optional, Sequence

from thomas.browser.p012_browser_artifact_accessibility_snapshot import (
    AccessibilitySnapshotRequest,
    BrowserArtifactError,
    capture_accessibility_snapshot_artifact,
)

try:
    import typer  # type: ignore
except Exception:  # pragma: no cover
    typer = None  # type: ignore


_REGISTERED = False


def _echo(text: str) -> None:
    if typer is not None:
        typer.echo(text)
        return
    print(text)


def _emit(payload: dict, *, json_mode: bool) -> None:
    if json_mode:
        _echo(json.dumps(payload, indent=2, sort_keys=True))
        return

    # Human mode: print the one thing people usually want to pipe.
    if "artifact_path" in payload:
        _echo(str(payload["artifact_path"]))
        return

    _echo(json.dumps(payload, indent=2, sort_keys=True))


def run_accessibility_snapshot(
    *,
    artifact_dir: Optional[Path],
    name: str,
    interesting_only: bool,
    json_mode: bool,
) -> int:
    """Implementation entrypoint used by both Typer and argparse harnesses.

    Returns a process-like exit code:
    - 0: success
    - 2: invalid_input
    - 3: missing_config
    - 4: external_failure
    """

    try:
        source = _resolve_browser_source()
        req = AccessibilitySnapshotRequest(
            source=source,
            artifact_dir=artifact_dir,
            artifact_name=name,
            interesting_only=interesting_only,
        )
        result = capture_accessibility_snapshot_artifact(req)
    except BrowserArtifactError as e:
        _emit({"ok": False, "error": e.to_dict()}, json_mode=json_mode)
        return _exit_code_for_error(e.code)

    _emit({"ok": True, **result.to_dict()}, json_mode=json_mode)
    return 0


def _exit_code_for_error(code: str) -> int:
    return {
        "invalid_input": 2,
        "missing_config": 3,
        "external_failure": 4,
    }.get(code, 1)


def _resolve_browser_source() -> Any:
    """Resolve the live browser/page source.

    Deterministic failure: raises BrowserArtifactError(code="missing_config", ...)

    This uses duck-typing / best-effort discovery; it does not start browsers.
    """

    candidate_modules = (
        "thomas.cli.live_browser",
        "thomas.tools.browser",
        "thomas.tools.browser_tool",
    )

    candidate_callables: Sequence[str] = (
        # common names for "give me the current page"
        "get_live_page",
        "get_page",
        "get_current_page",
        "require_live_page",
        "require_page",
        # common names for "give me the browser wrapper"
        "get_live_browser",
        "get_browser",
        "get_current_browser",
        "require_live_browser",
        "require_browser",
    )

    candidate_vars: Sequence[str] = (
        "LIVE_PAGE",
        "live_page",
        "PAGE",
        "page",
        "LIVE_BROWSER",
        "live_browser",
        "BROWSER",
        "browser",
    )

    last_error: Exception | None = None

    for mod_name in candidate_modules:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:  # noqa: BLE001
            last_error = e
            continue

        found = _try_resolve_from_module(mod, candidate_callables, candidate_vars)
        if found is not None:
            return found

    details: dict = {"modules_tried": list(candidate_modules)}
    if last_error is not None:
        details["last_exception"] = last_error.__class__.__name__

    raise BrowserArtifactError(
        "missing_config",
        "No live browser session is available.",
        details=details,
    )


def _try_resolve_from_module(mod: Any, callables: Sequence[str], vars_: Sequence[str]) -> Any | None:
    for fn_name in callables:
        fn = getattr(mod, fn_name, None)
        if not callable(fn):
            continue
        try:
            value = fn()
        except BrowserArtifactError:
            # Preserve deterministic errors from the underlying Thomas layer.
            raise
        except Exception:
            continue
        if value is not None:
            return value

    for var_name in vars_:
        value = getattr(mod, var_name, None)
        if value is not None:
            return value

    return None


# ---- Registration helpers --------------------------------------------------


def register_typer(browser_app: Any) -> None:
    """Register this command on an existing Typer app."""
    global _REGISTERED
    if _REGISTERED:
        return
    if typer is None:
        return

    if not hasattr(browser_app, "command"):
        raise TypeError("browser_app does not look like a Typer application (missing .command).")

    @browser_app.command("artifact-accessibility-snapshot")
    def artifact_accessibility_snapshot(
        artifact_dir: Optional[Path] = typer.Option(
            None,
            "--artifact-dir",
            "-o",
            help="Directory to write the artifact (or THOMAS_ARTIFACT_DIR).",
        ),
        name: str = typer.Option(
            "accessibility_snapshot",
            "--name",
            help="Base filename (without extension).",
        ),
        interesting_only: bool = typer.Option(
            True,
            "--interesting-only/--all-nodes",
            help="Whether to filter to interesting nodes only.",
        ),
        json_mode: bool = typer.Option(
            False,
            "--json",
            help="Emit machine-readable JSON.",
        ),
    ) -> None:
        """Write an accessibility snapshot JSON file to the artifact directory."""
        code = run_accessibility_snapshot(
            artifact_dir=artifact_dir,
            name=name,
            interesting_only=interesting_only,
            json_mode=json_mode,
        )
        raise typer.Exit(code=code)

    _REGISTERED = True


def register_argparse(add_parser: Callable[..., Any]) -> None:  # pragma: no cover
    """Register this command on an argparse subparser factory.

    This helper is provided for codebases that wire CLI commands via argparse.
    The exact signature of `add_parser` varies across projects, so we accept a
    callable that behaves like `subparsers.add_parser`.
    """
    parser = add_parser("artifact-accessibility-snapshot", help="Capture an accessibility snapshot artifact.")
    parser.add_argument("--artifact-dir", "-o", default=None)
    parser.add_argument("--name", default="accessibility_snapshot")
    parser.add_argument("--interesting-only", dest="interesting_only", action="store_true", default=True)
    parser.add_argument("--all-nodes", dest="interesting_only", action="store_false")
    parser.add_argument("--json", dest="json_mode", action="store_true", default=False)

    def _run(args: Any) -> int:
        return run_accessibility_snapshot(
            artifact_dir=Path(args.artifact_dir) if args.artifact_dir else None,
            name=args.name,
            interesting_only=args.interesting_only,
            json_mode=args.json_mode,
        )

    parser.set_defaults(_thomas_run=_run)


def _auto_register_with_browser_command_group() -> None:
    """Best-effort auto-registration.

    If the browser command group is Typer-based and exposes a `app` object at
    either:
      - thomas.cli.commands.browser.app (module attr) OR
      - thomas.cli.commands.browser (package attr)

    then register this command.
    """
    if typer is None:
        return

    pkg_name = __package__  # e.g. "thomas.cli.commands.browser"
    if not pkg_name:
        return

    # 1) Package attribute (thomas.cli.commands.browser: app = Typer())
    try:
        pkg = importlib.import_module(pkg_name)
        pkg_app = getattr(pkg, "app", None)
        if pkg_app is not None and hasattr(pkg_app, "command"):
            register_typer(pkg_app)
            return
    except Exception:
        pass

    # 2) Submodule (thomas.cli.commands.browser.app: app = Typer())
    try:
        mod = importlib.import_module(f"{pkg_name}.app")
        mod_app = getattr(mod, "app", None)
        if mod_app is not None and hasattr(mod_app, "command"):
            register_typer(mod_app)
            return
    except Exception:
        pass


_auto_register_with_browser_command_group()
