"""Miscellaneous commands (serve, repl, onboarding, release-contracts, security)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore[assignment]

# This module extends the cli group defined in _commands_base.py
# Import shared utilities and the cli group
from thomas.cli._commands_base import (
    _build_tools,
    _emit_json,
    _repl_needs_codex_event_loop,
    _resolve_model_profile_name,
    cli,
)
from thomas.core.config import AppConfig

if TYPE_CHECKING:
    pass


@cli.command()
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host")
@click.option("--port", default=8899, show_default=True, type=int, help="Bind port")
@click.pass_context
def serve(ctx: click.Context, host: str, port: int) -> None:
    """Run the web UI + HTTP API server."""
    config: AppConfig = ctx.obj["config"]
    errors = config.validate()
    if errors:
        for e in errors:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    try:
        from thomas.server.app import serve as serve_app

        serve_app(config, host=host, port=port)
    except ModuleNotFoundError as e:
        # Most commonly: aiohttp missing.
        click.echo(f"Server dependencies missing: {e}", err=True)
        click.echo('Install with: pip install -e ".[server]"', err=True)
        sys.exit(1)


@cli.command()
@click.option("-m", "--model", "model_name", help="Model profile to use")
@click.option(
    "--trace-files/--no-trace-files",
    default=None,
    help="Show files read by REPL on startup and each turn.",
)
@click.pass_context
def repl(ctx: click.Context, model_name: str | None, trace_files: bool | None) -> None:
    """Start the interactive REPL with rich terminal UI."""
    try:
        from thomas.cli.repl import ThomasREPL
    except ImportError as e:
        click.echo(f"REPL requires additional dependencies: {e}", err=True)
        click.echo("Install with: pip install prompt_toolkit>=3.0 rich>=13.0", err=True)
        sys.exit(1)

    config: AppConfig = ctx.obj["config"]
    try:
        from thomas.core.model_resolution import resolve_effective_model

        selected_model = _resolve_model_profile_name(config, model_name)
        if model_name and not selected_model:
            click.echo(
                f"Unknown model profile '{model_name}'. Available: {', '.join(config.models.keys())}",
                err=True,
            )
            sys.exit(2)

        resolved_profile, resolved_model_id = resolve_effective_model(
            config,
            cli_profile=selected_model,
            env_profile=str(os.environ.get("THOMAS_DEFAULT_MODEL", "")).strip(),
            user_id="default",
        )
        if not resolved_profile:
            click.echo(
                f"Unknown model profile '{model_name}'. Available: {', '.join(config.models.keys())}",
                err=True,
            )
            sys.exit(2)
        config.default_model = resolved_profile
        if resolved_model_id and resolved_profile in config.models:
            config.models[resolved_profile].model = resolved_model_id
    except Exception:
        resolved_profile = _resolve_model_profile_name(config, config.default_model)
        if not resolved_profile:
            click.echo("No valid model profile configured.", err=True)
            sys.exit(2)
        config.default_model = resolved_profile
    selected_model = config.default_model

    errors = config.validate()
    if errors:
        for e in errors:
            click.echo(f"Config error: {e}", err=True)
        sys.exit(1)

    tools_registry = _build_tools(config)

    # Keep Windows REPL compatible with prompt_toolkit while allowing Codex
    # flows to spawn its subprocess bridge.
    if sys.platform == "win32":
        if _repl_needs_codex_event_loop(config, selected_model):
            policy_cls = getattr(asyncio, "WindowsProactorEventLoopPolicy", None)
        else:
            policy_cls = getattr(asyncio, "WindowsSelectorEventLoopPolicy", None)
        if policy_cls is not None:
            asyncio.set_event_loop_policy(policy_cls())

    if trace_files is None:
        trace_files = str(os.environ.get("THOMAS_REPL_TRACE_FILES", "1")).strip().lower() not in (
            "0",
            "false",
            "off",
            "no",
        )
    repl_instance = ThomasREPL(config, tools_registry, trace_file_reads=trace_files)
    asyncio.run(repl_instance.run())


@cli.command("onboarding-outcomes")
@click.option("--db", "db_path", type=click.Path(exists=False, dir_okay=False), default="", help="Runs DB path.")
@click.option("--days", "window_days", type=int, default=7, show_default=True, help="Lookback window in days.")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
def onboarding_outcomes_cmd(db_path: str, window_days: int, as_json: bool) -> None:
    """Generate onboarding outcome metrics from observability events."""
    from thomas.marketplace.observability.onboarding_outcomes import (
        build_onboarding_outcome_report,
        get_outcomes_report,
    )

    days = max(1, int(window_days))
    if str(db_path or "").strip():
        report = build_onboarding_outcome_report(Path(str(db_path).strip()), since_days=days)
    else:
        report = get_outcomes_report(since_days=days)

    if as_json:
        _emit_json(report, ensure_ascii=False)
        return
    summary = dict(report.get("summary") or {})
    click.echo(f"events: {int(summary.get('events', 0) or 0)}")
    click.echo(f"wizard_opened: {int(summary.get('wizard_opened', 0) or 0)}")
    click.echo(f"onboarding_completed: {int(summary.get('onboarding_completed', 0) or 0)}")


@cli.group("release-contracts")
def release_contracts_group() -> None:
    """Release contract governance checks."""


@release_contracts_group.command("check")
@click.option("--registry", "registry_path", type=click.Path(exists=False, dir_okay=False), default="")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--strict", is_flag=True, help="Exit non-zero when checks fail.")
def release_contracts_check_cmd(registry_path: str, as_json: bool, strict: bool) -> None:
    """Validate the release contract registry."""
    from thomas.system.release_contracts import build_release_contract_report

    report = build_release_contract_report(Path(registry_path).resolve() if registry_path else None)
    if as_json:
        _emit_json(report, ensure_ascii=False)
    else:
        summary = dict(report.get("summary") or {})
        click.echo(f"ok: {bool(report.get('ok', False))}")
        click.echo(f"contract_count: {int(summary.get('contract_count', 0) or 0)}")
        click.echo(f"errors: {int(summary.get('error_count', 0) or 0)}")
        click.echo(f"warnings: {int(summary.get('warning_count', 0) or 0)}")
    if strict and not bool(report.get("ok", False)):
        raise SystemExit(2)


@cli.group("security")
def security_group() -> None:
    """Security governance checks."""


@security_group.command("audit")
@click.option("--repo-root", type=click.Path(exists=False, file_okay=False, dir_okay=True), default="")
@click.option("--json", "as_json", is_flag=True, help="Output machine-readable JSON.")
@click.option("--strict", is_flag=True, help="Exit non-zero when checks fail.")
def security_audit_cmd(repo_root: str, as_json: bool, strict: bool) -> None:
    """Run aggregated security audit checks."""
    from thomas.marketplace.security.security_audit import run_security_audit

    resolved_root = Path(repo_root).expanduser().resolve() if str(repo_root or "").strip() else Path.cwd().resolve()
    report = run_security_audit(resolved_root, include_incident_drill=False)
    payload = {
        "ok": bool(report.get("ok", False)),
        "command": "security",
        "action": "audit",
        "repo_root": str(report.get("repo_root") or resolved_root),
        "summary": dict(report.get("summary") or {}),
        "checks": dict(report.get("checks") or {}),
    }
    if as_json:
        _emit_json(payload, ensure_ascii=False)
    else:
        summary = payload["summary"]
        click.echo(f"ok: {payload['ok']}")
        click.echo(f"check_count: {int(summary.get('check_count', 0) or 0)}")
        click.echo(f"error_count: {int(summary.get('error_count', 0) or 0)}")
        click.echo(f"warning_count: {int(summary.get('warning_count', 0) or 0)}")
    if strict and not payload["ok"]:
        raise SystemExit(2)


# Public root app alias used by external loaders/tests.
app = cli
