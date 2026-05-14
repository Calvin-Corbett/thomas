"""CLI wrapper for message permissions view (P068).

This module is designed to be easy to register from Thomas' CLI composition
layer. It exposes:
 `typer_app` (and alias `app`)
 `register(parent_app)`
 `get_typer_app()`

The command supports human output as well as machine-readable JSON via `--json`.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Optional

import typer

from thomas.messages.p068_message_permissions_view import (
    MessagePermissionsViewConfig,
    MessagePermissionsViewError,
    MessagePermissionsViewRequest,
    _coerce_permissions_mapping,
    load_message_permissions_view_config,
    view_message_permissions,
)

# Common metadata / compatibility surface for CLI discovery layers.
PROMPT_ID = "P068"
COMMAND_GROUP = "permissions"
COMMAND_NAME = "view"
COMMAND_FULL = f"messages {COMMAND_GROUP} {COMMAND_NAME}"

typer_app = typer.Typer(add_completion=False, help="View message-level permissions.")
app = typer_app


@typer_app.callback()
def _permissions_group() -> None:
    return None


def _build_config(
    *,
    static_permissions: str | None = None,
    endpoint: str | None = None,
    token: str | None = None,
    timeout_s: float | None = None,
) -> MessagePermissionsViewConfig:
    """Construct config from CLI overrides or environment."""

    if static_permissions is None and endpoint is None and token is None and timeout_s is None:
        return load_message_permissions_view_config()

    resolved_timeout = 10.0
    if timeout_s is not None:
        resolved_timeout = timeout_s
    else:
        raw_timeout = os.environ.get("THOMAS_MESSAGE_PERMISSIONS_VIEW_TIMEOUT_S")
        if raw_timeout:
            try:
                resolved_timeout = float(raw_timeout)
            except ValueError as exc:
                raise MessagePermissionsViewError(
                    code="invalid_input",
                    message="Invalid THOMAS_MESSAGE_PERMISSIONS_VIEW_TIMEOUT_S: must be a number",
                    details={"value": raw_timeout},
                ) from exc

    if static_permissions is not None:
        try:
            parsed = json.loads(static_permissions)
        except json.JSONDecodeError as exc:
            raise MessagePermissionsViewError(
                code="invalid_input",
                message="--static-permissions must be valid JSON",
                details={"value": static_permissions},
            ) from exc

        return MessagePermissionsViewConfig(
            static_permissions=_coerce_permissions_mapping(parsed, context="cli"),
            timeout_s=resolved_timeout,
        )

    resolved_endpoint = endpoint or os.environ.get("THOMAS_MESSAGE_PERMISSIONS_VIEW_ENDPOINT")
    resolved_token = token or os.environ.get("THOMAS_MESSAGE_PERMISSIONS_VIEW_TOKEN")

    if not resolved_endpoint:
        raise MessagePermissionsViewError(
            code="missing_config",
            message=(
                "Remote permissions backend endpoint not configured. "
                "Provide --endpoint or set THOMAS_MESSAGE_PERMISSIONS_VIEW_ENDPOINT."
            ),
            details={"required": ["THOMAS_MESSAGE_PERMISSIONS_VIEW_ENDPOINT"]},
        )

    return MessagePermissionsViewConfig(
        endpoint=resolved_endpoint,
        token=resolved_token,
        timeout_s=resolved_timeout,
    )


@typer_app.command(COMMAND_NAME)
def cli_view(
    message_id: str = typer.Option(..., "--message-id", "-m", help="Message identifier."),
    user_id: str | None = typer.Option(
        None, "--user-id", "-u", help="User identifier for which to view permissions."
    ),
    json_output: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON output.",
    ),
    static_permissions: str | None = typer.Option(
        None,
        "--static-permissions",
        help="Override permissions with a JSON mapping (e.g. '{\"view\": true}').",
    ),
    endpoint: str | None = typer.Option(
        None,
        "--endpoint",
        help="Remote permissions backend URL (overrides env).",
    ),
    token: str | None = typer.Option(
        None,
        "--token",
        help="Bearer token for remote backend (overrides env).",
    ),
    timeout_s: float | None = typer.Option(
        None,
        "--timeout-s",
        help="HTTP timeout in seconds (overrides env).",
    ),
) -> None:
    """View permissions for a message."""

    try:
        cfg = _build_config(
            static_permissions=static_permissions,
            endpoint=endpoint,
            token=token,
            timeout_s=timeout_s,
        )
        result = view_message_permissions(
            MessagePermissionsViewRequest(message_id=message_id, user_id=user_id),
            config=cfg,
        )

        if json_output:
            typer.echo(json.dumps({"ok": True, "result": asdict(result)}, sort_keys=True))
        else:
            perms = ", ".join(
                f"{name}={'yes' if allowed else 'no'}" for name, allowed in sorted(result.permissions.items())
            )
            typer.echo(f"Message {result.message_id} permissions ({result.source}): {perms}")

    except MessagePermissionsViewError as exc:
        if json_output:
            typer.echo(json.dumps({"ok": False, "error": exc.to_dict()}, sort_keys=True))
        else:
            typer.echo(f"ERROR[{exc.code}]: {exc}", err=True)
        raise typer.Exit(code=1)
 
 
def register(parent_app: typer.Typer) -> None:
     """Register this command under an existing Typer app.
 
     This helper prefers a nested structure: `messages permissions view`.
     """
 
     parent_app.add_typer(typer_app, name=COMMAND_GROUP)
 
 
def get_typer_app() -> typer.Typer:
     """Compatibility helper for CLI composition layers."""
 
     return typer_app
