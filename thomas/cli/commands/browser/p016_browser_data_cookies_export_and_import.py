"""CLI: browser data cookies export/import.

Adds:

    thomas browser data cookies export ...

    thomas browser data cookies import ...

Supports:

- `--json` machine-readable output.
- `--format auto|json|zip` for explicit automation control.
- `--zip` as a shorthand for `--format zip` on export.

Implementation lives in:
    thomas.browser.p016_browser_data_cookies_export_and_import
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any, cast

import typer

from thomas.browser.p016_browser_data_cookies_export_and_import import (
    CookiesExportRequest,
    CookiesFormat,
    CookiesImportRequest,
    CookiesTransferError,
    InvalidInputError,
    export_cookies,
    import_cookies,
    result_to_dict,
)
from thomas.cli.commands.browser._runtime_entrypoint import run_typer_app

_REGISTERED = False
_FORMAT_HELP = "Format: auto|json|zip. 'auto' infers from file extension/signature."


def _emit(obj: Any, *, json_mode: bool) -> None:
    if json_mode:
        typer.echo(json.dumps(obj, indent=2, sort_keys=True))
        return

    # Human mode: keep it concise.
    if isinstance(obj, dict) and obj.get("ok") is True and isinstance(obj.get("result"), dict):
        res = cast(dict[str, Any], obj["result"])
        if "output_file" in res:
            fmt = res.get("output_format") or "json"
            typer.echo(f"Exported {res.get('cookie_count', 0)} cookies -> {res['output_file']} ({fmt})")
            return
        if "input_file" in res:
            fmt = res.get("input_format") or "json"
            typer.echo(f"Imported {res.get('cookie_count', 0)} cookies from {res['input_file']} ({fmt})")
            return
        typer.echo(str(res))
        return

    if isinstance(obj, dict) and obj.get("ok") is False and isinstance(obj.get("error"), dict):
        err = cast(dict[str, Any], obj["error"])
        typer.echo(f"ERROR [{err.get('code')}]: {err.get('message')}")
        return

    typer.echo(str(obj))


def _handle_error(err: Exception, *, json_mode: bool) -> None:
    if isinstance(err, CookiesTransferError):
        payload = {"ok": False, "error": err.to_dict()}
    else:
        payload = {
            "ok": False,
            "error": {"code": "EXTERNAL_FAILURE", "message": str(err), "details": {"error": type(err).__name__}},
        }

    _emit(payload, json_mode=json_mode)
    raise typer.Exit(code=1)


def _parse_format_option(format_opt: str, *, zip_flag: bool = False) -> str | None:
    fmt = (format_opt or "auto").strip().lower()

    if zip_flag:
        # --zip is shorthand for format=zip; reject conflicting explicit formats.
        if fmt not in ("auto", "zip"):
            raise InvalidInputError("Conflicting format options", details={"format": format_opt, "zip": True})
        return "zip"

    if fmt in ("auto", ""):
        return None
    if fmt in ("json", "zip"):
        return fmt

    raise InvalidInputError(
        "Invalid format option", details={"format": format_opt, "expected": ["auto", "json", "zip"]}
    )


def _find_group(parent: typer.Typer, name: str) -> typer.Typer | None:
    for info in getattr(parent, "registered_groups", []) or []:
        if getattr(info, "name", None) == name:
            for attr in ("typer_instance", "typer", "app"):
                maybe = getattr(info, attr, None)
                if isinstance(maybe, typer.Typer):
                    return maybe
    return None


def _get_or_create_group(parent: typer.Typer, name: str, *, help_text: str) -> typer.Typer:
    existing = _find_group(parent, name)
    if existing is not None:
        return existing
    group = typer.Typer(help=help_text)
    parent.add_typer(group, name=name)
    return group


app = typer.Typer(help="Export/import browser cookies")


@app.command("export")
def cookies_export(
    output_file: Path = typer.Argument(..., exists=False, dir_okay=False, writable=True, readable=False),
    profile_dir: Path | None = typer.Option(
        None, "--profile-dir", help="Browser profile directory (or set THOMAS_BROWSER_PROFILE_DIR)."
    ),
    url: str | None = typer.Option(None, "--url", help="Optional URL scope filter."),
    format: str = typer.Option("auto", "--format", help=_FORMAT_HELP),
    zip_mode: bool = typer.Option(False, "--zip", help="Shorthand for --format zip."),
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Export cookies from the browser profile to a JSON file or zip."""
    try:
        output_format = _parse_format_option(format, zip_flag=zip_mode)
        res = export_cookies(
            CookiesExportRequest(
                output_file=output_file,
                profile_dir=profile_dir,
                url=url,
                output_format=cast(CookiesFormat | None, output_format),
            )
        )
        payload = {"ok": True, "result": result_to_dict(res)}
        _emit(payload, json_mode=json_mode)
    except Exception as e:
        _handle_error(e, json_mode=json_mode)


@app.command("import")
def cookies_import(
    input_file: Path = typer.Argument(..., exists=True, dir_okay=False, readable=True),
    profile_dir: Path | None = typer.Option(
        None, "--profile-dir", help="Browser profile directory (or set THOMAS_BROWSER_PROFILE_DIR)."
    ),
    format: str = typer.Option("auto", "--format", help=_FORMAT_HELP),
    json_mode: bool = typer.Option(False, "--json", help="Emit machine-readable JSON output."),
) -> None:
    """Import cookies from a JSON file or zip into the browser profile."""
    try:
        input_format = _parse_format_option(format)
        res = import_cookies(
            CookiesImportRequest(
                input_file=input_file,
                profile_dir=profile_dir,
                input_format=cast(CookiesFormat | None, input_format),
            )
        )
        payload = {"ok": True, "result": result_to_dict(res)}
        _emit(payload, json_mode=json_mode)
    except Exception as e:
        _handle_error(e, json_mode=json_mode)


def register(browser_app: typer.Typer) -> None:
    """Register the cookies export/import commands under `browser data cookies`."""
    global _REGISTERED
    if _REGISTERED:
        return

    data_app = _get_or_create_group(browser_app, "data", help_text="Manage browser data")

    if _find_group(data_app, "cookies") is None:
        data_app.add_typer(app, name="cookies")

    _REGISTERED = True


def main(argv: Sequence[str] | None = None) -> int:
    """Pack-proxy runtime entrypoint."""
    return run_typer_app(
        app,
        argv,
        command="browser data-cookies-export-and-import",
        require_args=True,
        missing_args_message="Specify an operation: export or import.",
    )
