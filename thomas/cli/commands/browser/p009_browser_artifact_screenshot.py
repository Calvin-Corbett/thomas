from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import typer

from thomas.browser.p009_browser_artifact_screenshot import (
    BrowserArtifactScreenshotError,
    BrowserArtifactScreenshotRequest,
    take_artifact_screenshot,
)

# Avoid duplicate registration if a command loader imports this module and also calls `register(...)`.
_REGISTERED_APP_IDS: set[int] = set()


def _emit(payload: dict[str, Any], *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return

    if payload.get("ok"):
        typer.echo(payload.get("screenshot_path", ""))
        return

    err = payload.get("error") or {}
    typer.echo(f"ERROR [{err.get('code', 'UNKNOWN')}]: {err.get('message', '')}", err=True)


def _run(
    *,
    artifact: str,
    out: Optional[Path],
    artifact_root: Optional[Path],
    full_page: bool,
    width: int,
    height: int,
    wait_ms: int,
    timeout_ms: int,
    json_output: bool,
) -> None:
    req = BrowserArtifactScreenshotRequest(
        artifact=artifact,
        output=str(out) if out is not None else None,
        full_page=full_page,
        viewport_width=width,
        viewport_height=height,
        wait_ms=wait_ms,
        timeout_ms=timeout_ms,
        artifact_root=str(artifact_root) if artifact_root is not None else None,
    )

    try:
        result_obj = take_artifact_screenshot(req)
    except BrowserArtifactScreenshotError as e:
        _emit({"ok": False, "error": e.to_dict()}, json_output=json_output)
        raise typer.Exit(code=2)
    except Exception as e:  # pragma: no cover
        _emit(
            {
                "ok": False,
                "error": {
                    "code": "UNHANDLED",
                    "message": "Unhandled exception while taking artifact screenshot.",
                    "details": {"exception": repr(e)},
                },
            },
            json_output=json_output,
        )
        raise typer.Exit(code=3)

    _emit({"ok": True, **result_obj.to_dict()}, json_output=json_output)


def _get_typer_subapp(parent: typer.Typer, name: str, *, help_text: str) -> typer.Typer:
    """Find or create a named Typer sub-app on `parent`."""
    groups = getattr(parent, "registered_groups", None) or []
    for group_info in groups:
        try:
            if getattr(group_info, "name", None) != name:
                continue
        except Exception:
            continue
        for attr in ("typer_instance", "typer", "app"):
            candidate = getattr(group_info, attr, None)
            if isinstance(candidate, typer.Typer):
                return candidate

    sub = typer.Typer(help=help_text)
    parent.add_typer(sub, name=name)
    return sub


def _normalize_browser_container(app: Any) -> Any:
    """If `app` is the root CLI, return its `browser` group; otherwise return `app`."""
    if isinstance(app, typer.Typer):
        groups = getattr(app, "registered_groups", None) or []
        for group_info in groups:
            if getattr(group_info, "name", None) != "browser":
                continue
            for attr in ("typer_instance", "typer", "app"):
                candidate = getattr(group_info, attr, None)
                if isinstance(candidate, typer.Typer):
                    return candidate
        return app

    try:
        import click
    except Exception:  # pragma: no cover
        return app

    if isinstance(app, click.Group):
        return app.commands.get("browser", app)

    return app


def register(app: Any) -> None:
    """Register `thomas browser artifact screenshot` on the provided CLI app."""
    app_id = id(app)
    if app_id in _REGISTERED_APP_IDS:
        return

    try:
        container = _normalize_browser_container(app)

        if isinstance(container, typer.Typer):
            artifact_app = _get_typer_subapp(container, "artifact", help_text="Utilities for browser artifacts.")

            # Typer will raise if you attempt to register the same command twice. Avoid that by
            # checking if click already has it.
            click_group = typer.main.get_command(artifact_app)
            if "screenshot" in getattr(click_group, "commands", {}):
                _REGISTERED_APP_IDS.add(app_id)
                return

            @artifact_app.command("screenshot")
            def artifact_screenshot(
                artifact: str = typer.Argument(..., help="Artifact path or artifact id."),
                out: Optional[Path] = typer.Option(
                    None,
                    "--out",
                    "--output",
                    help="Where to write the screenshot (PNG). If a directory, a name will be chosen automatically.",
                ),
                artifact_root: Optional[Path] = typer.Option(
                    None,
                    "--artifact-root",
                    help="Optional root directory used to resolve artifact ids to files.",
                ),
                full_page: bool = typer.Option(
                    True,
                    "--full-page/--viewport-only",
                    help="Capture the full scroll height instead of only the current viewport (HTML only).",
                ),
                width: int = typer.Option(1280, "--width", min=1, help="Viewport width (px)."),
                height: int = typer.Option(720, "--height", min=1, help="Viewport height (px)."),
                wait_ms: int = typer.Option(250, "--wait-ms", min=0, help="Extra delay after load before screenshot."),
                timeout_ms: int = typer.Option(30_000, "--timeout-ms", min=1, help="Navigation timeout (ms)."),
                json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON to stdout."),
            ) -> None:
                """Save a PNG screenshot of a browser artifact."""
                _run(
                    artifact=artifact,
                    out=out,
                    artifact_root=artifact_root,
                    full_page=full_page,
                    width=width,
                    height=height,
                    wait_ms=wait_ms,
                    timeout_ms=timeout_ms,
                    json_output=json_output,
                )

            _REGISTERED_APP_IDS.add(app_id)
            return

        try:
            import click
        except Exception as e:  # pragma: no cover
            raise RuntimeError("Thomas CLI command registration requires click or typer.") from e

        if not isinstance(container, click.Group):  # pragma: no cover
            raise RuntimeError(f"Unsupported CLI container type: {type(container)!r}")

        artifact_group = container.commands.get("artifact")
        if not isinstance(artifact_group, click.Group):
            artifact_group = click.Group("artifact", help="Utilities for browser artifacts.")
            container.add_command(artifact_group)

        if "screenshot" in artifact_group.commands:
            _REGISTERED_APP_IDS.add(app_id)
            return

        @artifact_group.command("screenshot")
        @click.argument("artifact")
        @click.option("--out", "--output", type=click.Path(path_type=Path), default=None)
        @click.option("--artifact-root", type=click.Path(path_type=Path), default=None)
        @click.option("--full-page/--viewport-only", default=True)
        @click.option("--width", type=int, default=1280)
        @click.option("--height", type=int, default=720)
        @click.option("--wait-ms", type=int, default=250)
        @click.option("--timeout-ms", type=int, default=30_000)
        @click.option("--json", "json_output", is_flag=True, default=False)
        def _artifact_screenshot_click(
            artifact: str,
            out: Optional[Path],
            artifact_root: Optional[Path],
            full_page: bool,
            width: int,
            height: int,
            wait_ms: int,
            timeout_ms: int,
            json_output: bool,
        ) -> None:
            _run(
                artifact=artifact,
                out=out,
                artifact_root=artifact_root,
                full_page=full_page,
                width=width,
                height=height,
                wait_ms=wait_ms,
                timeout_ms=timeout_ms,
                json_output=json_output,
            )

        _REGISTERED_APP_IDS.add(app_id)
    except Exception:
        # Only mark it registered on success.
        _REGISTERED_APP_IDS.discard(app_id)
        raise


# Compatibility aliases for potential command loaders.
build = register
add_to_app = register
register_command = register
register_commands = register


def _auto_register_if_possible() -> None:
    """Try to register on an already-created CLI app without causing import cycles."""
    if "thomas.cli.main" not in sys.modules:
        return
    main_mod = sys.modules.get("thomas.cli.main")
    if not main_mod:
        return
    app = getattr(main_mod, "app", None) or getattr(main_mod, "cli", None)
    if app is None:
        return
    try:
        register(app)
    except Exception:
        # Never crash on import; determinism belongs at runtime invocation.
        return


_auto_register_if_possible()
