"""CLI commands for Thomas green-side self-improvement sessions."""

from __future__ import annotations

import json
from pathlib import Path

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore

from thomas.forge.anvil.evolve import (
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
from thomas.forge.anvil.evolve_autonomy import POSTURE_LABELS, parse_posture
from thomas.forge.anvil.evolve_chat import (
    interpret_evolve_message,
    resolve_approval_ids,
    status_summary,
)
from thomas.forge.anvil.evolve_loop import (
    approve_pending,
    load_loop_state,
    reject_pending,
    request_pause,
    run_evolve_loop,
)
from thomas.forge.anvil.evolve_planner import plan_backlog, render_backlog_markdown


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


@evolve.command("plan")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--focus", default="", help="Bias the backlog toward a category (e.g. hardening, perf, tests).")
@click.option("--category", "categories", multiple=True, help="Restrict to these categories (repeatable).")
@click.option("--limit", default=12, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
def evolve_plan(
    repo_root: Path | None,
    focus: str,
    categories: tuple[str, ...],
    limit: int,
    as_json: bool,
) -> None:
    """Survey Thomas and show the self-chosen improvement backlog (no model calls)."""
    resolved_root = resolve_repo_root(repo_root)
    backlog = plan_backlog(resolved_root, focus=focus, categories=set(categories) or None, limit=limit)
    if as_json:
        _emit_json(backlog.to_dict())
        return
    click.echo(render_backlog_markdown(backlog))


@evolve.command("loop")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--posture", default="auto_safe", show_default=True, help="propose | auto_safe | autonomous")
@click.option("--focus", default="", help="Bias the loop toward a category (e.g. hardening, perf).")
@click.option("--category", "categories", multiple=True, help="Restrict to these categories (repeatable).")
@click.option("--max-iterations", default=6, show_default=True, type=int)
@click.option("--max-promotions", default=4, show_default=True, type=int)
@click.option("--max-wall-seconds", default=0, show_default=True, type=int, help="0 = no wall-clock bound.")
@click.option("--profile", default="", help="Model profile to use for evolve passes.")
@click.option("--timeout-seconds", default=1800, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
def evolve_loop_command(
    repo_root: Path | None,
    posture: str,
    focus: str,
    categories: tuple[str, ...],
    max_iterations: int,
    max_promotions: int,
    max_wall_seconds: int,
    profile: str,
    timeout_seconds: int,
    as_json: bool,
) -> None:
    """Run the self-recursive evolve loop: plan, improve, verify, promote, repeat."""
    resolved_root = resolve_repo_root(repo_root)
    resolved_posture = parse_posture(posture).value
    state = run_evolve_loop(
        resolved_root,
        posture=resolved_posture,
        focus=focus,
        categories=list(categories) or None,
        max_iterations=max_iterations,
        max_promotions=max_promotions,
        max_wall_seconds=max_wall_seconds,
        profile=profile,
        timeout_seconds=timeout_seconds,
    )
    if as_json:
        _emit_json(state)
        return
    counters = state["counters"]
    click.echo(f"Evolve loop {state['status']} ({POSTURE_LABELS.get(state['posture'], state['posture'])})")
    click.echo(
        f"Promoted {counters['promoted']} | Held {counters['held']} | "
        f"Rejected {counters['rejected']} | Failed {counters['failed']} | Iterations {state['iteration']}"
    )
    if state["pending_count"]:
        click.echo(
            f"{state['pending_count']} change(s) awaiting your approval. "
            "Review with `thomas evolve loop-status`, then `thomas evolve approve <id>`."
        )


@evolve.command("loop-status")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
def evolve_loop_status(repo_root: Path | None, as_json: bool) -> None:
    """Show the evolve loop state, counters, and pending approvals."""
    resolved_root = resolve_repo_root(repo_root)
    state = load_loop_state(resolved_root).to_dict()
    if as_json:
        _emit_json(state)
        return
    click.echo(f"Loop status: {state['status']} | posture: {state['posture']} | iteration: {state['iteration']}")
    counters = state["counters"]
    click.echo(
        f"Promoted {counters['promoted']} | Held {counters['held']} | "
        f"Rejected {counters['rejected']} | Failed {counters['failed']}"
    )
    pending = [p for p in state["pending_approvals"] if p.get("status") == "pending"]
    if not pending:
        click.echo("No changes awaiting approval.")
        return
    click.echo(f"\n{len(pending)} change(s) awaiting your approval:")
    for item in pending:
        click.echo(f"  [{item['id']}] ({item['category']}/{item['risk_tier']}) {item['title']}")


@evolve.command("approve")
@click.argument("approval_id")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--profile", default="", help="Model profile for the re-run.")
@click.option("--timeout-seconds", default=1800, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
def evolve_approve(
    approval_id: str,
    repo_root: Path | None,
    profile: str,
    timeout_seconds: int,
    as_json: bool,
) -> None:
    """Approve a held change: re-derive its goal in the mirror and promote it."""
    resolved_root = resolve_repo_root(repo_root)
    payload = approve_pending(resolved_root, approval_id, profile=profile, timeout_seconds=timeout_seconds)
    if as_json:
        _emit_json(payload)
        return
    approval = payload.get("approval", {})
    if payload.get("ok"):
        click.echo(f"Approved and promoted: {approval.get('title')} [{approval.get('status')}]")
    else:
        click.echo(f"Could not promote: {approval.get('reason')}")


@evolve.command("reject")
@click.argument("approval_id")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--reason", default="", help="Why you are dismissing this change.")
@click.option("--json", "as_json", is_flag=True)
def evolve_reject(approval_id: str, repo_root: Path | None, reason: str, as_json: bool) -> None:
    """Dismiss a held change without promoting it."""
    resolved_root = resolve_repo_root(repo_root)
    payload = reject_pending(resolved_root, approval_id, reason=reason)
    if as_json:
        _emit_json(payload)
        return
    click.echo(f"Rejected: {payload['approval'].get('title')}")


@evolve.command("chat")
@click.argument("message")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--interpret-only", is_flag=True, help="Only print the parsed intent; take no action.")
@click.option("--posture", default="", help="Override posture for a start intent.")
@click.option("--profile", default="", help="Model profile for a start/approve action.")
@click.option("--max-iterations", default=6, show_default=True, type=int)
@click.option("--max-promotions", default=4, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
def evolve_chat_command(
    message: str,
    repo_root: Path | None,
    interpret_only: bool,
    posture: str,
    profile: str,
    max_iterations: int,
    max_promotions: int,
    as_json: bool,
) -> None:
    """Talk to the evolve loop in plain language: start, status, pause, approve, reject."""
    intent = interpret_evolve_message(message)
    if interpret_only:
        _emit_json(intent.to_dict())
        return

    resolved_root = resolve_repo_root(repo_root)
    reply = intent.reply
    if intent.action == "start":
        resolved_posture = parse_posture(posture or intent.posture or "auto_safe").value
        state = run_evolve_loop(
            resolved_root,
            posture=resolved_posture,
            focus=intent.focus,
            max_iterations=max_iterations,
            max_promotions=max_promotions,
            profile=profile,
        )
    elif intent.action == "status":
        state = load_loop_state(resolved_root).to_dict()
        reply = f"{intent.reply} {status_summary(state)}"
    elif intent.action == "pause":
        state = request_pause(resolved_root)
    elif intent.action in ("approve", "reject"):
        ids = resolve_approval_ids(load_loop_state(resolved_root).to_dict(), intent.approval_ref)
        if not ids:
            reply = "Nothing is waiting for your approval right now."
        else:
            for approval_id in ids:
                if intent.action == "approve":
                    approve_pending(resolved_root, approval_id, profile=profile)
                else:
                    reject_pending(resolved_root, approval_id, reason="dismissed via chat")
        state = load_loop_state(resolved_root).to_dict()
    else:  # help
        state = load_loop_state(resolved_root).to_dict()

    payload = {"ok": True, "action": intent.action, "reply": reply, "intent": intent.to_dict(), "state": state}
    if as_json:
        _emit_json(payload)
        return
    click.echo(reply)


def register_evolve_commands(cli_group: click.Group) -> None:
    """Register evolve-mode commands."""
    cli_group.add_command(evolve)
