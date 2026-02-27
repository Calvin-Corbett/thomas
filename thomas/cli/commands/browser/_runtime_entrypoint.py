"""Shared helpers for browser pack-module main(argv) entrypoints."""

from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from datetime import datetime, timezone

import click
import typer


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _argv_list(argv: Sequence[str] | None) -> list[str]:
    return [str(arg) for arg in (argv or [])]


def _emit_error(
    *,
    command: str,
    code: str,
    category: str,
    message: str,
    exit_code: int,
    json_mode: bool,
    hint: str = "",
) -> int:
    payload = {
        "ok": False,
        "command": str(command),
        "timestamp_utc": _utc_iso(),
        "error": {
            "category": str(category),
            "code": str(code),
            "message": str(message),
        },
    }
    hint_text = str(hint or "").strip()
    if hint_text:
        payload["error"]["hint"] = hint_text

    if json_mode:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        sys.stdout.write("\n")
    else:
        sys.stderr.write(f"{code}: {message}\n")
    return int(exit_code)


def run_click_command(
    click_command: click.Command,
    argv: Sequence[str] | None = None,
    *,
    command: str,
    require_args: bool = False,
    missing_args_message: str = "",
) -> int:
    args = _argv_list(argv)
    json_mode = "--json" in args

    if require_args and not args:
        return _emit_error(
            command=command,
            code="browser_command_invalid_input",
            category="invalid_input",
            message=(str(missing_args_message or "").strip() or "Arguments are required for this command."),
            exit_code=2,
            json_mode=json_mode,
        )

    try:
        rv = click_command.main(
            args=args,
            prog_name=str(command).strip() or "browser-command",
            standalone_mode=False,
        )
        return int(rv) if isinstance(rv, int) else 0
    except SystemExit as exc:
        return int(exc.code or 0)
    except click.ClickException as exc:
        if json_mode:
            return _emit_error(
                command=command,
                code="browser_command_invalid_input",
                category="invalid_input",
                message=str(exc),
                exit_code=int(getattr(exc, "exit_code", 2) or 2),
                json_mode=True,
            )
        exc.show()
        return int(getattr(exc, "exit_code", 1) or 1)
    except Exception as exc:  # pragma: no cover
        return _emit_error(
            command=command,
            code="browser_command_unexpected_error",
            category="internal_error",
            message=f"{type(exc).__name__}: {exc}",
            exit_code=1,
            json_mode=json_mode,
        )


def run_typer_app(
    app: typer.Typer,
    argv: Sequence[str] | None = None,
    *,
    command: str,
    require_args: bool = False,
    missing_args_message: str = "",
) -> int:
    click_command = typer.main.get_command(app)
    return run_click_command(
        click_command,
        argv,
        command=command,
        require_args=require_args,
        missing_args_message=missing_args_message,
    )
