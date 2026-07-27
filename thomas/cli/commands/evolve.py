"""CLI commands for Thomas green-side self-improvement sessions."""

from __future__ import annotations

import json
from pathlib import Path

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore

from evolve_supervisor import POSTURE_LABELS, parse_posture, run_evolve_corpus
from thomas.forge.anvil.evolve import (
    DEFAULT_EVOLVE_OBJECTIVE,
    DEFAULT_EVOLVE_PRINCIPLES,
    DEFAULT_VERIFY_COMMANDS,
    EvolveCharter,
    _render_session_markdown,
    _sessions_root,
    _write_json,
    _write_text,
    build_charter_markdown,
    ensure_evolve_charter,
    has_evolve_charter,
    list_evolve_sessions,
    load_evolve_charter,
    load_evolve_session,
    load_latest_evolve_session,
    promote_evolve_session,
    resolve_evolve_root,
    resolve_repo_root,
    run_evolve_session,
    utc_now_iso,
)
from thomas.forge.anvil.evolve_loop import (
    approve_pending,
    load_loop_state,
    reject_pending,
    run_evolve_loop,
)
from thomas.forge.anvil.evolve_planner import plan_backlog, render_backlog_markdown
from thomas.forge.anvil.native_orchestration import (
    DEFAULT_RECIPE_ID,
    get_recipe,
    list_recipes,
    plan_orchestration_run,
    start_orchestration_run,
    status_payload,
)


def _emit_json(payload: dict) -> None:
    click.echo(json.dumps(payload, ensure_ascii=True, indent=2))


def _latest_verifier_panel(latest: dict | None) -> dict | None:
    if not isinstance(latest, dict):
        return None
    panel = latest.get("verifier_panel")
    if isinstance(panel, dict):
        return panel
    supervisor_verdict = latest.get("supervisor_verdict")
    if isinstance(supervisor_verdict, dict):
        panel = supervisor_verdict.get("verifier_panel")
        if isinstance(panel, dict):
            return panel
    artifacts = latest.get("artifacts")
    if isinstance(artifacts, dict):
        panel = artifacts.get("verifier_panel")
        if isinstance(panel, dict):
            return panel
    return None


def _format_verifier_panel_summary(panel: dict | None) -> str:
    if not isinstance(panel, dict):
        return ""
    status = "PASS" if bool(panel.get("ok")) else "HOLD"
    pass_count = int(panel.get("pass_count") or 0)
    quorum = int(panel.get("quorum") or 0)
    critical = int(panel.get("critical_dissent_count") or 0)
    return f"{status} ({pass_count}/{quorum} pass, {critical} critical dissent)"


def _format_verifier_panel_reconciled(panel: dict | None) -> str:
    if not isinstance(panel, dict):
        return ""
    pass_count = int(panel.get("pass_count") or 0)
    quorum = int(panel.get("quorum") or 0)
    critical = int(panel.get("critical_dissent_count") or 0)
    return f"votes={pass_count} quorum={quorum} dissent={critical} (computed)"


def _verification_output_artifact_count(latest: dict | None) -> int:
    if not isinstance(latest, dict):
        return 0
    rows = latest.get("verification")
    if not isinstance(rows, list):
        return 0
    count = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        count += int(bool(row.get("stdout_artifact")))
        count += int(bool(row.get("stderr_artifact")))
    return count


def _reject_session_if_exists(repo_root: Path, session_token: str, reason: str) -> dict | None:
    try:
        session = load_evolve_session(repo_root, session_token)
    except RuntimeError as exc:
        if "was not found" in str(exc) or "session_id is required" in str(exc):
            return None
        raise
    if session.get("promoted"):
        raise RuntimeError("promoted evolve sessions cannot be rejected")
    rejection_reason = str(reason or "").strip() or "manual red-team rejection"
    rejection = f"manual red-team rejection: {rejection_reason}"
    session_rejections = [str(item) for item in (session.get("session_rejections") or [])]
    if rejection not in session_rejections:
        session_rejections.append(rejection)
    session["session_rejections"] = session_rejections
    session["rejection_reason"] = rejection_reason
    session["rejected_at"] = utc_now_iso()
    session["finished_at"] = session["rejected_at"]
    session["promotable"] = False
    session["promoted"] = False
    session["status"] = "rejected"
    session_id = str(session.get("session_id") or session_token)
    session_dir = _sessions_root(repo_root) / session_id
    _write_json(session_dir / "session.json", session)
    _write_text(session_dir / "session.md", _render_session_markdown(session))
    return {"ok": True, "session": session, "rejected_session": True}


@click.group("evolve")
def evolve() -> None:
    """Run green-side self-improvement cycles against Thomas."""


@evolve.command("init")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--objective", default=DEFAULT_EVOLVE_OBJECTIVE, show_default=True)
@click.option("--default-goal", default="", help="Default evolve goal when none is supplied.")
@click.option("--principle", "principles", multiple=True, help="Charter principle (repeatable).")
@click.option("--verify-cmd", "verify_commands", multiple=True, help="Verification command (repeatable).")
@click.option(
    "--acceptance-check", "acceptance_checks", multiple=True, help="Semantic acceptance check id (repeatable)."
)
@click.option("--max-passes", default=1, show_default=True, type=int)
@click.option("--overwrite", is_flag=True)
@click.option("--json", "as_json", is_flag=True)
def evolve_init(
    repo_root: Path | None,
    objective: str,
    default_goal: str,
    principles: tuple[str, ...],
    verify_commands: tuple[str, ...],
    acceptance_checks: tuple[str, ...],
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
        acceptance_checks=list(acceptance_checks),
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
    if charter.acceptance_checks:
        click.echo(f"Acceptance checks: {', '.join(charter.acceptance_checks)}")


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
    verifier_panel_summary = _format_verifier_panel_summary(_latest_verifier_panel(latest))
    verifier_panel_reconciled = _format_verifier_panel_reconciled(_latest_verifier_panel(latest))
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
    if charter.acceptance_checks:
        click.echo(f"Acceptance checks: {', '.join(charter.acceptance_checks)}")
    click.echo(f"Run count: {len(sessions)}")
    if latest:
        click.echo(
            f"Latest session: {latest['session_id']} status={latest['status']} "
            f"changed={latest['delta']['changed_count']} promotable={latest['promotable']}"
        )
        if latest.get("status") == "rejected" and latest.get("rejection_reason"):
            click.echo(f"Rejection reason: {latest['rejection_reason']}")
        verification_output_artifacts = _verification_output_artifact_count(latest)
        if verification_output_artifacts:
            click.echo(f"Verification output artifacts: {verification_output_artifacts}")
        if latest.get("verification_repair_attempted"):
            click.echo("Verification repair: attempted")
        verification_repair_artifacts = latest.get("verification_repair_artifacts")
        if isinstance(verification_repair_artifacts, list) and verification_repair_artifacts:
            click.echo(f"Verification repair artifacts: {len(verification_repair_artifacts)}")
            first_repair_artifact = verification_repair_artifacts[0]
            if isinstance(first_repair_artifact, dict):
                first_repair_artifact = first_repair_artifact.get("path")
            if first_repair_artifact:
                first_repair_artifact_path = Path(str(first_repair_artifact))
                first_repair_artifact_parts = first_repair_artifact_path.parts
                if "verification-repair" in first_repair_artifact_parts:
                    first_repair_artifact = Path(
                        *first_repair_artifact_parts[first_repair_artifact_parts.index("verification-repair") :]
                    )
                click.echo(
                    f"Verification repair artifact: {first_repair_artifact.as_posix()}"
                    if isinstance(first_repair_artifact, Path)
                    else f"Verification repair artifact: {first_repair_artifact}"
                )
        if verifier_panel_summary:
            click.echo(f"Verifier panel: {verifier_panel_summary}")
        if verifier_panel_reconciled:
            click.echo(f"Verifier panel reconciled: {verifier_panel_reconciled}")


@evolve.command("corpus")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
def evolve_corpus(repo_root: Path | None, as_json: bool) -> None:
    """Run the blue-owned frozen evolve corpus."""
    resolved_root = resolve_repo_root(repo_root)
    result = run_evolve_corpus(resolved_root)
    payload = result.to_dict()
    if as_json:
        _emit_json(payload)
        if not result.ok:
            raise SystemExit(1)
        return
    failed_case_count = sum(1 for case in result.cases if not case.ok)
    lock_error_count = len(result.lock_errors)
    summary = f"{result.case_count} case(s), {failed_case_count} failed, {lock_error_count} lock error(s)"
    if result.ok:
        click.echo(f"Evolve corpus: PASS ({summary})")
        return
    click.echo(f"Evolve corpus: FAIL ({summary})")
    for error in result.lock_errors:
        click.echo(f"- {error.get('code')}: {error.get('path')} {error.get('message')}")
    for case in result.cases:
        if not case.ok:
            click.echo(f"- {case.case_id}: expected {case.expected}, got {case.actual}")
    raise SystemExit(1)


@evolve.command("run")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--goal", default="", help="Specific improve-the-system goal for this session.")
@click.option("--profile", default="", help="Model profile to use for the evolve pass.")
@click.option("--passes", default=1, show_default=True, type=int)
@click.option("--promote-on-pass", is_flag=True, help="Promote green to blue automatically when gates pass.")
@click.option(
    "--acceptance-check", "acceptance_checks", multiple=True, help="Semantic acceptance check id (repeatable)."
)
@click.option(
    "--refactor-first/--no-refactor-first",
    default=None,
    help="Run the pre-refactor pass before this session. Defaults to on only when no explicit --goal is supplied.",
)
@click.option("--timeout-seconds", default=1800, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
def evolve_run(
    repo_root: Path | None,
    goal: str,
    profile: str,
    passes: int,
    promote_on_pass: bool,
    acceptance_checks: tuple[str, ...],
    refactor_first: bool | None,
    timeout_seconds: int,
    as_json: bool,
) -> None:
    """Run one green-side evolve session."""
    goal_text = str(goal or "").strip()
    run_refactor_first = bool(refactor_first) if refactor_first is not None else not bool(goal_text)
    payload = run_evolve_session(
        repo_root,
        goal=goal_text,
        profile=profile,
        passes=passes,
        promote_on_pass=promote_on_pass,
        acceptance_checks=list(acceptance_checks),
        refactor_first=run_refactor_first,
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
    if session.get("acceptance_checks"):
        click.echo(f"Acceptance checks: {', '.join(session['acceptance_checks'])}")


@evolve.command("promote")
@click.argument("session_id", required=False)
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--stop-port", default=8899, show_default=True, type=int)
@click.option("--json", "as_json", is_flag=True)
@click.option(
    "--approve-critical-risk",
    is_flag=True,
    help="Allow manual promotion when the session re-evaluates to the critical risk floor.",
)
def evolve_promote(
    session_id: str | None,
    repo_root: Path | None,
    stop_port: int,
    as_json: bool,
    approve_critical_risk: bool,
) -> None:
    """Promote the latest ready evolve session from green to blue."""
    payload = promote_evolve_session(
        repo_root,
        session_id=str(session_id or ""),
        stop_port=stop_port,
        allow_critical_risk_floor=approve_critical_risk,
    )
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
@click.option(
    "--mode",
    type=click.Choice(["classic", "funnel"]),
    default="classic",
    show_default=True,
    help="Per-goal engine: classic single-pass, or the multi-agent funnel.",
)
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
    mode: str,
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
        mode=mode,
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


@evolve.command("dispatch")
@click.argument("goal")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--use-funnel", is_flag=True, help="Converge a plan via the funnel before dispatching.")
@click.option("--profile", default="", help="Model profile for funnel composition.")
@click.option(
    "--via",
    type=click.Choice(["cli", "desktop"]),
    default="cli",
    show_default=True,
    help="cli = headless `claude -p` (safe, observable); desktop = type into the GUI via desktop_operator.",
)
@click.option("--execute", is_flag=True, help="Actually dispatch (needs bridge enabled + --yes). Default is preview.")
@click.option("--yes", is_flag=True, help="Explicit human confirmation for --execute.")
@click.option(
    "--model",
    default="claude:sonnet",
    show_default=True,
    help="Which brain builds it: claude:sonnet|claude:opus|claude:fable or codex:gpt.",
)
@click.option(
    "--effort", default="medium", help="Reasoning effort hint: low|medium|high|max (accepted for compatibility)."
)
@click.option(
    "--conversation-id",
    "conversation_id",
    default="",
    help="Forge Code conversation id; loads its prior turns as multi-turn history.",
)
def evolve_dispatch_command(
    goal: str,
    repo_root: Path | None,
    use_funnel: bool,
    profile: str,
    via: str,
    execute: bool,
    yes: bool,
    model: str,
    effort: str,
    conversation_id: str,
) -> None:
    """Dispatch a build task to Claude Code (Thomas drives Claude to build). PREVIEW by default."""
    from thomas.forge.anvil.evolve_claude_bridge import (
        BridgeConfig,
        ClaudeCodeBridge,
        compose_from_funnel,
        connect_desktop_operator_driver,
        dispatch_via_claude_cli,
    )

    root = resolve_repo_root(repo_root)
    cfg = BridgeConfig.load(root)
    definition = plan = ""
    if use_funnel:
        try:
            definition, plan = compose_from_funnel(goal, project_root=root, profile=profile)
        except (ImportError, ModuleNotFoundError, OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
            # Composing is an enhancement; the raw goal is still dispatchable.
            click.echo(f"(funnel compose failed: {exc}; dispatching the raw goal)")

    # Prior turns of this Forge Code conversation, so the dispatched turn is a real
    # MULTI-TURN exchange (a follow-up like "explain what you just did" sees them),
    # not a one-shot. Loading is best-effort: no id / unknown id => no history.
    history: list[dict] = []
    if conversation_id:
        try:
            from thomas.forge.anvil import forge_code_store

            history = forge_code_store.history_turns(root, conversation_id)
        except (ImportError, ModuleNotFoundError, OSError, RuntimeError, TypeError, ValueError, KeyError) as exc:
            # History is additive; never block a dispatch because prior turns
            # could not be read.
            click.echo(f"(history load failed: {exc}; dispatching without prior turns)")

    live = bool(execute and yes and cfg.enabled)

    if via == "cli":
        provider, _, variant = model.partition(":")
        # The GPT/ChatGPT brain runs IN-PROCESS through Thomas's own ChatGPT-OAuth
        # provider (AgentLoop + openai_codex) — NEVER the codex CLI. The picker
        # value "codex:gpt" still works, but "codex" no longer means a subprocess.
        gpt_brain = provider in ("codex", "gpt", "chatgpt", "openai_codex")
        if gpt_brain:
            from thomas.forge.anvil.evolve_claude_bridge import dispatch_via_agent_loop
            from thomas.server.openai_codex_oauth import (
                _default_secret_store,
                has_openai_codex_token,
            )

            def _chatgpt_connected() -> bool:
                try:
                    return bool(has_openai_codex_token(_default_secret_store(), "openai_codex"))
                except (RuntimeError, OSError, ValueError, TypeError):
                    return False

            res = dispatch_via_agent_loop(
                goal,
                cwd=root,
                definition=definition,
                plan=plan,
                timeout=900,
                dry_run=not live,
                history=history,
                token_check=_chatgpt_connected,
            )
        else:
            res = dispatch_via_claude_cli(
                goal,
                cwd=root,
                definition=definition,
                plan=plan,
                model=(variant or "sonnet"),
                timeout=900,
                dry_run=not live,
                history=history,
            )
        brain_label = "GPT (ChatGPT OAuth)" if gpt_brain else "claude CLI"
        invoke_label = "the in-process GPT agent loop" if gpt_brain else "`claude -p`"
        if not live:
            click.echo(f"PREVIEW ({brain_label} not invoked). Prompt that WOULD be sent to {invoke_label}:\n")
            click.echo(res.prompt)
            click.echo(
                "\nTo dispatch for real: set [evolve.claude_bridge].enabled=true, then "
                "`--execute --yes`. The dispatched build edits files only (no shell/git/network); "
                "review the diff and run the tests before keeping it."
            )
            return
        if res.ok and res.changed_files:
            head = f"DISPATCHED via {brain_label}"
        elif res.ok:
            head = f"NO-OP ({brain_label} ran but changed nothing)"
        else:
            head = "FAILED"
        click.echo(f"{head}: {res.reason}")
        if res.changed_files:
            click.echo("changed files:\n  " + "\n  ".join(res.changed_files))
            click.echo("\nReview the diff before keeping these changes.")
        # Honest exit: a non-zero returncode (a failed build OR a failed
        # engine verification after fix attempts) must propagate so the caller
        # (the Forge route's `done` frame) shows a real failure, never green.
        if not res.ok and res.returncode:
            raise SystemExit(res.returncode)
        return

    # via == "desktop"
    if not (execute and yes):
        bridge = ClaudeCodeBridge(config=cfg, driver=None)
        res = bridge.preview(goal, definition=definition, plan=plan)
        click.echo("PREVIEW — no PC control. Planned actions:")
        for a in res.planned_actions:
            click.echo("  - " + a)
        click.echo("\n----- prompt that WOULD be typed into Claude Code -----\n")
        click.echo(res.prompt)
        click.echo(
            "\nTo actually type into the GUI: set [evolve.claude_bridge].enabled=true, run the desktop "
            "host service with an allowlisted 'claude_code' profile, then `--via desktop --execute --yes`."
        )
        return
    driver = connect_desktop_operator_driver()
    bridge = ClaudeCodeBridge(config=cfg, driver=driver)
    res = bridge.dispatch(goal, confirm=yes, definition=definition, plan=plan)
    click.echo(("DISPATCHED" if res.dispatched else "REFUSED") + f": {res.reason}")
    if res.window:
        click.echo(f"window: {res.window}")


@evolve.group("orchestration")
def evolve_orchestration() -> None:
    """Plan native Thomas orchestration recipes and worker lanes."""


@evolve_orchestration.command("recipes")
@click.option("--json", "as_json", is_flag=True)
def evolve_orchestration_recipes(as_json: bool) -> None:
    """List built-in orchestration recipes."""
    recipes = [recipe.to_dict() for recipe in list_recipes()]
    payload = {"ok": True, "recipes": recipes, "count": len(recipes)}
    if as_json:
        _emit_json(payload)
        return
    for recipe in recipes:
        click.echo(f"{recipe['id']}: {recipe['name']}")
        click.echo(f"  trigger: {recipe['trigger']}")
        click.echo(f"  lanes: {len(recipe['lanes'])} | max active workers: {recipe['max_active_workers']}")


@evolve_orchestration.command("status")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True)
def evolve_orchestration_status(repo_root: Path | None, as_json: bool) -> None:
    """Show native orchestration recipes, runs, and active workers."""
    resolved_root = resolve_repo_root(repo_root)
    payload = status_payload(resolved_root)
    if as_json:
        _emit_json(payload)
        return
    click.echo(f"Native orchestration state: {payload['state_path']}")
    click.echo(f"Recipes: {len(payload['recipes'])} | Runs: {payload['run_count']}")
    click.echo(f"Active workers: {payload['active_worker_count']}")
    for worker in payload["active_workers"][:12]:
        click.echo(f"  {worker['worker_id']} [{worker['status']}] {worker['title']}")


@evolve_orchestration.command("plan")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--recipe", "recipe_id", default=DEFAULT_RECIPE_ID, show_default=True)
@click.option("--json", "as_json", is_flag=True)
def evolve_orchestration_plan(repo_root: Path | None, recipe_id: str, as_json: bool) -> None:
    """Dry-run a recipe plan without spawning workers."""
    resolved_root = resolve_repo_root(repo_root)
    recipe = get_recipe(recipe_id)
    plan = plan_orchestration_run(resolved_root, recipe_id=recipe.id)
    payload = {"ok": True, "recipe": recipe.to_dict(), "run": plan.to_dict()}
    if as_json:
        _emit_json(payload)
        return
    click.echo(f"Recipe: {recipe.name}")
    click.echo(f"Plan status: {plan.status}")
    for worker in plan.workers:
        click.echo(f"  {worker.lane_key}: {worker.status} via {worker.runner_hint}")
        if worker.reason:
            click.echo(f"    {worker.reason}")
    for blocked in plan.blocked_lanes:
        click.echo(f"  blocked {blocked['lane_key']}: {blocked['reason']}")
    for action in plan.recommended_actions:
        click.echo(f"next: {action}")


@evolve_orchestration.command("start")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--recipe", "recipe_id", default=DEFAULT_RECIPE_ID, show_default=True)
@click.option("--dry-run", is_flag=True, help="Preview only; do not write orchestration state.")
@click.option("--json", "as_json", is_flag=True)
def evolve_orchestration_start(repo_root: Path | None, recipe_id: str, dry_run: bool, as_json: bool) -> None:
    """Start a native orchestration run by writing the planned worker ledger."""
    resolved_root = resolve_repo_root(repo_root)
    run = start_orchestration_run(resolved_root, recipe_id=recipe_id, dry_run=dry_run)
    payload = {"ok": True, "run": run.to_dict()}
    if as_json:
        _emit_json(payload)
        return
    mode = "DRY RUN" if dry_run else "STARTED"
    click.echo(f"{mode}: {run.run_id} status={run.status}")
    click.echo(f"Workers: {len(run.workers)} | Blocked lanes: {len(run.blocked_lanes)}")
    for action in run.recommended_actions:
        click.echo(f"next: {action}")


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
    """Dismiss a held change or ready evolve session without promoting it."""
    resolved_root = resolve_repo_root(repo_root)
    payload = _reject_session_if_exists(resolved_root, approval_id, reason) or reject_pending(
        resolved_root, approval_id, reason=reason
    )
    if as_json:
        _emit_json(payload)
        return
    if payload.get("rejected_session"):
        click.echo(f"Rejected evolve session: {payload['session'].get('session_id')}")
        return
    click.echo(f"Rejected: {payload['approval'].get('title')}")


def register_evolve_commands(cli_group: click.Group) -> None:
    """Register evolve-mode commands."""
    cli_group.add_command(evolve)
