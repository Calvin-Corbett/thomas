"""CLI commands for Thomas green-side self-improvement sessions."""

from __future__ import annotations

import json
from pathlib import Path

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore

from thomas.upgrade.evolve import (
    DEFAULT_EVOLVE_OBJECTIVE,
    DEFAULT_EVOLVE_PRINCIPLES,
    DEFAULT_VERIFY_COMMANDS,
    EvolveCharter,
    build_charter_markdown,
    ensure_evolve_charter,
    has_evolve_charter,
    list_evolve_sessions,
    load_evolve_charter,
    load_latest_evolve_session,
    promote_evolve_session,
    resolve_evolve_root,
    resolve_repo_root,
    run_evolve_session,
)


def _emit_json(payload: dict) -> None:
    click.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@click.group("evolve")
def evolve() -> None:
    """Run green-side self-improvement cycles against Thomas."""


@evolve.command("init")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--objective", default=DEFAULT_EVOLVE_OBJECTIVE, show_default=True)
@click.option("--default-goal", default="", help="Default evolve goal when none is supplied.")
@click.option("--principle", "principles", multiple=True, help="Charter principle (repeatable).")
@click.option("--verify-cmd", "verify_commands", multiple=True, help="Verification command (repeatable).")
@click.option("--max-passes", default=1, show_default=True, type=int)
@click.option("--overwrite", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def evolve_init(
    repo_root: Path | None,
    objective: str,
    default_goal: str,
    principles: tuple[str, ...],
    verify_commands: tuple[str, ...],
    max_passes: int,
    overwrite: bool,
    as_json: bool,
) -> None:
    """Initialize the evolve charter under `.thomas/evolve/`."""
    resolved_root = resolve_repo_root(repo_root)
    charter = EvolveCharter(
        objective=str(objective or DEFAULT_EVOLVE_OBJECTIVE).strip() or DEFAULT_EVOLVE_OBJECTIVE,
        default_goal=str(default_goal or "").strip(),
        principles=list(principles) or list(DEFAULT_EVOLVE_PRINCIPLES),
        verify_commands=list(verify_commands) or list(DEFAULT_VERIFY_COMMANDS),
        max_passes=max(1, min(int(max_passes or 1), 8)),
    )
    evolve_root, json_path, markdown_path = ensure_evolve_charter(resolved_root, charter, overwrite=overwrite)
    payload = {
        "ok": True,
        "repo_root": str(resolved_root),
        "evolve_root": str(evolve_root),
        "charter_path": str(json_path),
        "charter_markdown_path": str(markdown_path),
        "charter": charter.to_dict(),
        "charter_preview": build_charter_markdown(charter),
    }
    if as_json:
        _emit_json(payload)
        return
    click.echo(f"Initialized evolve mode in {evolve_root}")
    click.echo(f"Objective: {charter.objective}")
    click.echo(f"Verification: {', '.join(charter.verify_commands)}")


@evolve.command("status")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
def evolve_status(repo_root: Path | None, as_json: bool) -> None:
    """Show the current evolve charter and latest session."""
    resolved_root = resolve_repo_root(repo_root)
    initialized = has_evolve_charter(resolved_root)
    charter = load_evolve_charter(resolved_root) if initialized else None
    sessions = list_evolve_sessions(resolved_root, limit=20)
    latest = load_latest_evolve_session(resolved_root)
    payload = {
        "ok": True,
        "initialized": initialized,
        "repo_root": str(resolved_root),
        "evolve_root": str(resolve_evolve_root(resolved_root)),
        "charter": charter.to_dict() if charter else None,
        "latest_session": latest,
        "run_count": len(sessions),
    }
    if as_json:
        _emit_json(payload)
        return
    if not initialized:
        click.echo(f"Evolve mode is not initialized for {resolved_root}")
        return
    click.echo(f"Evolve objective: {charter.objective}")
    click.echo(f"Verification: {', '.join(charter.verify_commands)}")
    click.echo(f"Run count: {len(sessions)}")
    if latest:
        click.echo(
            f"Latest session: {latest['session_id']} status={latest['status']} "
            f"changed={latest['delta']['changed_count']} promotable={latest['promotable']}"
        )


@evolve.command("run")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--goal", default="", help="Specific improve-the-system goal for this session.")
@click.option("--profile", default="", help="Model profile to use for the evolve pass.")
@click.option("--passes", default=1, show_default=True, type=int)
@click.option("--promote-on-pass", is_flag=True, help="Promote green to blue automatically when gates pass.")
@click.option("--timeout-seconds", default=1800, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
def evolve_run(
    repo_root: Path | None,
    goal: str,
    profile: str,
    passes: int,
    promote_on_pass: bool,
    timeout_seconds: int,
    as_json: bool,
) -> None:
    """Run one green-side evolve session."""
    payload = run_evolve_session(
        repo_root,
        goal=goal,
        profile=profile,
        passes=passes,
        promote_on_pass=promote_on_pass,
        timeout_seconds=timeout_seconds,
    )
    if as_json:
        _emit_json(payload)
        return
    session = payload["session"]
    click.echo(f"Evolve session: {session['session_id']}")
    click.echo(f"Status: {session['status']}")
    click.echo(f"Changed files: {session['delta']['changed_count']}")
    click.echo(f"Promotable: {session['promotable']}")


@evolve.command("promote")
@click.argument("session_id", required=False)
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--stop-port", default=8899, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
def evolve_promote(session_id: str | None, repo_root: Path | None, stop_port: int, as_json: bool) -> None:
    """Promote the latest ready evolve session from green to blue."""
    payload = promote_evolve_session(repo_root, session_id=str(session_id or ""), stop_port=stop_port)
    if as_json:
        _emit_json(payload)
        return
    click.echo(f"Promoted evolve session: {payload['session']['session_id']}")
    if payload.get("backup_path"):
        click.echo(f"Backup: {payload['backup_path']}")


def register_evolve_commands(cli_group: click.Group) -> None:
    """Register evolve-mode commands."""
    cli_group.add_command(evolve)
