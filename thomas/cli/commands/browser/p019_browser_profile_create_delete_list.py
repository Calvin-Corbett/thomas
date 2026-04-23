"""CLI commands for browser profile management (create/delete/list).

This module exposes a Typer app named "profile" intended to be registered under
the existing "browser" command group.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn

import typer

from thomas.browser.p019_browser_profile_create_delete_list import (
    BrowserProfileError,
    CreateBrowserProfileRequest,
    DeleteBrowserProfileRequest,
    ListBrowserProfilesRequest,
    create_browser_profile,
    delete_browser_profile,
    list_browser_profiles,
)
from thomas.cli.commands.browser._runtime_entrypoint import run_typer_app

profile_app = typer.Typer(
    name="profile",
    help="Manage local browser profiles (create/delete/list).",
    no_args_is_help=True,
)

# Compatibility alias for loaders that look for `app`.
app = profile_app


def _emit(payload: dict, *, json_output: bool) -> None:
    if json_output:
        typer.echo(json.dumps(payload, sort_keys=True))
        return

    message = payload.get("message")
    if message is None:
        return
    typer.echo(message)


def _emit_error(exc: BrowserProfileError, *, json_output: bool) -> NoReturn:
    if json_output:
        payload = {"ok": False, "error": {"code": exc.code, "message": str(exc)}}
        typer.echo(json.dumps(payload, sort_keys=True))
    else:
        typer.echo(f"Error [{exc.code}]: {exc}", err=True)
    raise typer.Exit(code=getattr(exc, "exit_code", 1))


@profile_app.command("create")
def create(
    name: str = typer.Argument(..., help="Profile name (letters/numbers/._-)."),
    root: Path | None = typer.Option(
        None,
        "--root",
        help="Override the profiles root directory (advanced).",
        show_default=False,
    ),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    """Create a new browser profile."""

    try:
        result = create_browser_profile(CreateBrowserProfileRequest(name=name, profiles_root=root))
    except BrowserProfileError as e:
        _emit_error(e, json_output=json_output)

    payload = {
        "ok": True,
        "action": "create",
        "profile": result.profile.to_dict(),
        "message": f"Created browser profile '{result.profile.name}'.",
    }
    _emit(payload, json_output=json_output)


@profile_app.command("delete")
def delete(
    name: str = typer.Argument(..., help="Profile name to delete."),
    root: Path | None = typer.Option(
        None,
        "--root",
        help="Override the profiles root directory (advanced).",
        show_default=False,
    ),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    """Delete an existing browser profile."""

    try:
        result = delete_browser_profile(DeleteBrowserProfileRequest(name=name, profiles_root=root))
    except BrowserProfileError as e:
        _emit_error(e, json_output=json_output)

    payload = {
        "ok": True,
        "action": "delete",
        "name": result.name,
        "deleted": result.deleted,
        "message": f"Deleted browser profile '{result.name}'.",
    }
    _emit(payload, json_output=json_output)


@profile_app.command("list")
def list_cmd(
    root: Path | None = typer.Option(
        None,
        "--root",
        help="Override the profiles root directory (advanced).",
        show_default=False,
    ),
    json_output: bool = typer.Option(False, "--json", help="Output machine-readable JSON."),
) -> None:
    """List browser profiles."""

    try:
        result = list_browser_profiles(ListBrowserProfilesRequest(profiles_root=root))
    except BrowserProfileError as e:
        _emit_error(e, json_output=json_output)

    if result.profiles:
        message = "\n".join([f"{p.name} ({p.kind})" for p in result.profiles])
    else:
        message = "(no profiles)"

    payload = {
        "ok": True,
        "action": "list",
        "profiles": [p.to_dict() for p in result.profiles],
        "count": len(result.profiles),
        "message": message,
    }
    _emit(payload, json_output=json_output)


def register(parent_app: object) -> None:
    """Register this command group under the browser CLI group.

    This helper increases compatibility with command loaders that explicitly call
    `register()` when importing command modules.
    """

    if getattr(parent_app, "_p019_browser_profile_registered", False):
        return
    try:
        parent_app._p019_browser_profile_registered = True
    except ImportError:
        pass

    if hasattr(parent_app, "add_typer"):
        parent_app.add_typer(profile_app, name="profile")
        return

    if hasattr(parent_app, "add_command"):
        try:
            cmd = typer.main.get_command(profile_app)
        except Exception as e:  # pragma: no cover
            raise RuntimeError("Failed to build click command from Typer app") from e
        parent_app.add_command(cmd, name="profile")
        return

    raise TypeError(f"Unsupported parent app type for registration: {type(parent_app)!r}")


def main(argv: list[str] | None = None) -> int:
    """Pack-proxy runtime entrypoint."""
    return run_typer_app(
        profile_app,
        argv,
        command="browser profile-create-delete-list",
        require_args=True,
        missing_args_message="Specify a profile action: create, delete, or list.",
    )
