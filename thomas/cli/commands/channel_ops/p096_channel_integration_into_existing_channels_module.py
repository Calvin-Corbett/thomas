from __future__ import annotations

"""P096 CLI wiring: channel integration.

This is implemented as an extension module (channel_ops) so that channels CLI can
stay stable while gaining new provider-specific behavior.
"""

import json
from pathlib import Path
from typing import Any

import click
import typer

from thomas.channels.p096_channel_integration_into_existing_channels_module import (
    ChannelIntegrationError,
    ChannelIntegrationRequest,
    integrate_channel,
    supported_providers,
)


def _emit_json(payload: dict[str, Any]) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _providers_payload() -> dict[str, Any]:
    return {"ok": True, "providers": list(supported_providers())}


def _integrate_payload(
    *,
    provider: str,
    config: Path | None,
    token: str | None,
    chat_id: str | None,
    persist: bool,
    dry_run: bool,
    test_message: str | None,
    validate_external: bool,
) -> dict[str, Any]:
    inline_cfg: dict[str, Any] = {"token": token, "chat_id": chat_id}
    inline_cfg = {k: v for k, v in inline_cfg.items() if v is not None}

    req = ChannelIntegrationRequest(
        provider=provider,
        config_path=config,
        config=inline_cfg if inline_cfg else None,
        persist_enablement=persist,
        dry_run=dry_run,
        test_message=test_message,
        validate_external=validate_external,
    )
    result = integrate_channel(req)
    return {"ok": True, "result": result.to_dict()}


def register(app: Any) -> None:
    """Register P096 commands onto an existing channels app (Typer or Click)."""
    if isinstance(app, click.core.Group):
        _register_click(app)
        return
    _register_typer(app)


def _register_typer(app: typer.Typer) -> None:
    """Register Typer variants."""

    @app.command("providers")
    def providers(  # noqa: WPS430 - Typer command function
        json_output: bool = typer.Option(False, "--json", help="Machine readable output."),
    ) -> None:
        payload = _providers_payload()
        if json_output:
            _emit_json(payload)
        else:
            for p in payload["providers"]:
                typer.echo(p)

    @app.command("integrate")
    def integrate(  # noqa: WPS430 - Typer command function
        provider: str = typer.Argument(..., help="Provider name (e.g. telegram)."),
        config: Path | None = typer.Option(None, "--config", help="Path to Thomas JSON config."),
        token: str | None = typer.Option(None, "--token", envvar="THOMAS_TELEGRAM_BOT_TOKEN", help="Telegram bot token."),
        chat_id: str | None = typer.Option(None, "--chat-id", envvar="THOMAS_TELEGRAM_CHAT_ID", help="Telegram chat id."),
        persist: bool = typer.Option(True, "--persist/--no-persist", help="Persist enablement into the config file."),
        dry_run: bool = typer.Option(False, "--dry-run", help="Validate without writing changes."),
        test_message: str | None = typer.Option(None, "--test-message", help="Send a test message to validate the provider."),
        validate_external: bool = typer.Option(False, "--validate", help="Perform a lightweight provider validation (may call integration module)."),
        json_output: bool = typer.Option(False, "--json", help="Machine readable output."),
    ) -> None:
        try:
            payload = _integrate_payload(
                provider=provider,
                config=config,
                token=token,
                chat_id=chat_id,
                persist=persist,
                dry_run=dry_run,
                test_message=test_message,
                validate_external=validate_external,
            )
        except ChannelIntegrationError as e:
            if json_output:
                _emit_json({"ok": False, "error": e.to_dict()})
            else:
                typer.echo(f"ERROR[{e.code}]: {e.message}", err=True)
            raise typer.Exit(code=2) from e

        if json_output:
            _emit_json(payload)
            return

        result = payload["result"]
        msg = f"Integrated provider '{result['provider']}'."
        if bool(result.get("wrote_config")):
            msg += " Config updated."
        if result.get("details"):
            msg += f" Details: {result.get('details')}"
        warnings = result.get("warnings") or []
        if isinstance(warnings, list) and warnings:
            msg += f" Warnings: {', '.join(str(x) for x in warnings)}"
        typer.echo(msg)


def _register_click(app: click.core.Group) -> None:
    """Register Click variants for click-based channels CLI."""

    @app.command("providers")
    @click.option("--json", "json_output", is_flag=True, help="Machine readable output.")
    def providers_click(json_output: bool) -> None:
        payload = _providers_payload()
        if json_output:
            click.echo(json.dumps(payload, indent=2, sort_keys=True))
        else:
            for p in payload["providers"]:
                click.echo(str(p))

    @app.command("integrate")
    @click.argument("provider")
    @click.option("--config", "config_path", type=click.Path(path_type=Path), default=None)
    @click.option("--token", default=None)
    @click.option("--chat-id", default=None)
    @click.option("--persist/--no-persist", default=True)
    @click.option("--dry-run", is_flag=True, default=False)
    @click.option("--test-message", default=None)
    @click.option("--validate", "validate_external", is_flag=True, default=False)
    @click.option("--json", "json_output", is_flag=True, default=False)
    def integrate_click(
        provider: str,
        config_path: Path | None,
        token: str | None,
        chat_id: str | None,
        persist: bool,
        dry_run: bool,
        test_message: str | None,
        validate_external: bool,
        json_output: bool,
    ) -> None:
        try:
            payload = _integrate_payload(
                provider=provider,
                config=config_path,
                token=token,
                chat_id=chat_id,
                persist=persist,
                dry_run=dry_run,
                test_message=test_message,
                validate_external=validate_external,
            )
        except ChannelIntegrationError as e:
            err_payload = {"ok": False, "error": e.to_dict()}
            if json_output:
                click.echo(json.dumps(err_payload, indent=2, sort_keys=True))
            else:
                click.echo(f"ERROR[{e.code}]: {e.message}", err=True)
            raise SystemExit(2)

        if json_output:
            click.echo(json.dumps(payload, indent=2, sort_keys=True))
            return

        result = payload["result"]
        msg = f"Integrated provider '{result['provider']}'."
        if bool(result.get("wrote_config")):
            msg += " Config updated."
        click.echo(msg)
