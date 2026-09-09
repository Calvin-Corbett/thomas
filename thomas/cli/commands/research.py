"""CLI commands for repo-scoped autonomous research loops."""

from __future__ import annotations

import json
from pathlib import Path

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore

from thomas.library.research_models import ResearchProgramConfig, ResearchRunRecord, utc_now_iso
from thomas.library.research_runner import execute_research_run
from thomas.library.research_store import (
    build_program_markdown,
    has_research_program,
    init_research_program,
    list_research_runs,
    load_research_config,
    metric_sort_key,
    resolve_repo_root,
    resolve_research_root,
    resolve_run_record,
    save_research_config,
    update_research_run,
)


def _format_metric(metric_value: float | None) -> str:
    if metric_value is None:
        return "-"
    return f"{float(metric_value):.6f}".rstrip("0").rstrip(".")


def _emit_json(payload: dict) -> None:
    click.echo(json.dumps(payload, indent=2, ensure_ascii=False))


def _scoreboard_payload(repo_root: Path, config: ResearchProgramConfig) -> dict:
    runs = list_research_runs(repo_root)
    rows = sorted(
        runs,
        key=lambda run: (
            metric_sort_key(run.metric_value, config.metric_goal),
            0 if run.decision == "accepted" else 1,
            run.created_at,
        ),
    )
    return {
        "repo_root": str(repo_root),
        "research_root": str(resolve_research_root(repo_root)),
        "metric_name": config.metric_name,
        "metric_goal": config.metric_goal,
        "baseline_value": config.baseline_value,
        "run_count": len(runs),
        "rows": [row.to_dict() for row in rows],
    }


def _print_scoreboard(payload: dict, *, limit: int) -> None:
    rows = list(payload.get("rows") or [])[: max(1, int(limit or 10))]
    click.echo(
        f"Research scoreboard: {payload['metric_name']} ({payload['metric_goal']}) "
        f"baseline={_format_metric(payload.get('baseline_value'))}"
    )
    if not rows:
        click.echo("No research runs recorded yet.")
        return
    click.echo("")
    click.echo("RUN ID                         METRIC     VERDICT             DECISION   LABEL")
    click.echo("-----                          ------     -------             --------   -----")
    for row in rows:
        run_id = str(row.get("run_id", ""))[:28].ljust(28)
        metric = _format_metric(row.get("metric_value")).rjust(10)
        verdict = str(row.get("verdict", ""))[:18].ljust(18)
        decision = str(row.get("decision", ""))[:10].ljust(10)
        label = str(row.get("label", ""))[:32]
        click.echo(f"{run_id}  {metric}  {verdict}  {decision}  {label}")


@click.group("research")
def research() -> None:
    """Run a repo-local autoresearch loop with ledgers and accept/reject gates."""


@research.command("init")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--title", default="", help="Human-readable name for the program.")
@click.option("--objective", required=True, help="Single objective the loop should optimize.")
@click.option("--metric-name", required=True, help="Metric to track for accept/reject.")
@click.option(
    "--metric-goal",
    type=click.Choice(["maximize", "minimize"]),
    default="maximize",
    show_default=True,
    help="Whether higher or lower metric values are better.",
)
@click.option("--baseline-value", type=float, default=None, help="Current frontier metric value.")
@click.option("--editable-path", "editable_paths", multiple=True, help="Allowed relative path prefix.")
@click.option("--eval-cmd", default="", help="Shell command used to evaluate a candidate.")
@click.option("--metric-path", default="", help="JSON file path produced by the eval command.")
@click.option("--metric-key", default="", help="Dot path inside the metric JSON payload.")
@click.option("--runtime-budget-seconds", default=300, show_default=True, type=int, help="Eval timeout budget.")
@click.option("--overwrite", is_flag=True, help="Replace an existing program.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def research_init(
    repo_root: Path,
    title: str,
    objective: str,
    metric_name: str,
    metric_goal: str,
    baseline_value: float | None,
    editable_paths: tuple[str, ...],
    eval_cmd: str,
    metric_path: str,
    metric_key: str,
    runtime_budget_seconds: int,
    overwrite: bool,
    as_json: bool,
) -> None:
    """Initialize a repo-scoped research program under `.thomas/research/`."""
    resolved_root = resolve_repo_root(repo_root)
    config = ResearchProgramConfig(
        title=title or f"{resolved_root.name} Research Program",
        objective=objective,
        metric_name=metric_name,
        metric_goal=metric_goal,
        baseline_value=baseline_value,
        evaluation_command=eval_cmd,
        metric_path=metric_path,
        metric_key=metric_key,
        editable_paths=list(editable_paths),
        runtime_budget_seconds=runtime_budget_seconds,
    )
    research_root, config_path, program_path = init_research_program(resolved_root, config, overwrite=overwrite)
    payload = {
        "ok": True,
        "repo_root": str(resolved_root),
        "research_root": str(research_root),
        "config_path": str(config_path),
        "program_path": str(program_path),
        "config": config.to_dict(),
        "program_preview": build_program_markdown(config),
    }
    if as_json:
        _emit_json(payload)
        return
    click.echo(f"Initialized research mode in {research_root}")
    click.echo(f"Program: {program_path}")
    click.echo(f"Metric: {config.metric_name} ({config.metric_goal})")
    if config.editable_paths:
        click.echo(f"Editable paths: {', '.join(config.editable_paths)}")
    else:
        click.echo("Editable paths: unrestricted")


@research.command("status")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def research_status(repo_root: Path | None, as_json: bool) -> None:
    """Show the current research-program frontier and latest run."""
    resolved_root = resolve_repo_root(repo_root)
    if not has_research_program(resolved_root):
        raise click.ClickException(f"research mode is not initialized for {resolved_root}")
    config = load_research_config(resolved_root)
    runs = list_research_runs(resolved_root)
    latest = runs[0].to_dict() if runs else None
    payload = {
        "ok": True,
        "repo_root": str(resolved_root),
        "research_root": str(resolve_research_root(resolved_root)),
        "config": config.to_dict(),
        "latest_run": latest,
        "run_count": len(runs),
    }
    if as_json:
        _emit_json(payload)
        return
    click.echo(f"Research program: {config.title}")
    click.echo(f"Objective: {config.objective}")
    click.echo(f"Metric: {config.metric_name} ({config.metric_goal})")
    click.echo(f"Baseline: {_format_metric(config.baseline_value)}")
    click.echo(f"Runtime budget: {config.runtime_budget_seconds}s")
    click.echo(f"Eval command: {config.evaluation_command or '<unset>'}")
    click.echo("Editable paths: " + (", ".join(config.editable_paths) if config.editable_paths else "unrestricted"))
    click.echo(f"Run count: {len(runs)}")
    if latest:
        click.echo("")
        click.echo(
            f"Latest run: {latest['run_id']} metric={_format_metric(latest.get('metric_value'))} "
            f"verdict={latest.get('verdict')} decision={latest.get('decision')}"
        )


@research.command("run")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--label", default="candidate", show_default=True, help="Run label stored in the ledger.")
@click.option("--metric-value", type=float, default=None, help="Record a metric directly without running eval.")
@click.option("--eval-cmd", default="", help="Override the configured eval command for this run.")
@click.option("--notes", default="", help="Freeform notes for this run.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def research_run(
    repo_root: Path,
    label: str,
    metric_value: float | None,
    eval_cmd: str,
    notes: str,
    as_json: bool,
) -> None:
    """Execute or record one candidate run and write an immutable artifact."""
    resolved_root = resolve_repo_root(repo_root)
    config = load_research_config(resolved_root)
    run = execute_research_run(
        resolved_root,
        config,
        label=label,
        metric_value=metric_value,
        eval_cmd_override=eval_cmd,
        notes=notes,
    )
    payload = {
        "ok": run.status == "completed",
        "run": run.to_dict(),
        "repo_root": str(resolved_root),
        "research_root": str(resolve_research_root(resolved_root)),
    }
    if as_json:
        _emit_json(payload)
        return
    click.echo(f"Run: {run.run_id}")
    click.echo(f"Status: {run.status}")
    click.echo(f"Metric: {run.metric_name}={_format_metric(run.metric_value)}")
    click.echo(f"Verdict: {run.verdict}")
    if run.disallowed_files:
        click.echo("Disallowed files:")
        for item in run.disallowed_files:
            click.echo(f"  - {item}")
    click.echo(f"Artifact: {resolve_research_root(resolved_root) / 'runs' / run.run_id}")


def _decide_run(
    repo_root: Path,
    run_token: str,
    *,
    decision: str,
    reason: str,
    promote_baseline: bool,
) -> tuple[ResearchRunRecord, ResearchProgramConfig]:
    resolved_root = resolve_repo_root(repo_root)
    run = resolve_run_record(resolved_root, run_token)
    config = load_research_config(resolved_root)
    run.decision = decision
    run.decision_at = utc_now_iso()
    run.decision_reason = str(reason or "").strip()
    update_research_run(resolved_root, run)
    if promote_baseline and decision == "accepted" and run.metric_value is not None:
        config.baseline_value = float(run.metric_value)
        save_research_config(resolved_root, config)
    return run, config


@research.command("accept")
@click.argument("run_id")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--reason", default="", help="Why this run is being promoted.")
@click.option(
    "--promote-baseline/--no-promote-baseline",
    default=True,
    show_default=True,
    help="Update the program baseline with the accepted metric.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def research_accept(
    run_id: str,
    repo_root: Path,
    reason: str,
    promote_baseline: bool,
    as_json: bool,
) -> None:
    """Accept a run and optionally promote its metric to the baseline."""
    run, config = _decide_run(
        repo_root,
        run_id,
        decision="accepted",
        reason=reason,
        promote_baseline=promote_baseline,
    )
    payload = {"ok": True, "run": run.to_dict(), "config": config.to_dict()}
    if as_json:
        _emit_json(payload)
        return
    click.echo(f"Accepted: {run.run_id}")
    if promote_baseline and run.metric_value is not None:
        click.echo(f"Baseline promoted to {_format_metric(config.baseline_value)}")


@research.command("reject")
@click.argument("run_id")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--reason", default="", help="Why this run is being rejected.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def research_reject(run_id: str, repo_root: Path | None, reason: str, as_json: bool) -> None:
    """Reject a run while preserving its immutable artifact."""
    run, config = _decide_run(
        repo_root,
        run_id,
        decision="rejected",
        reason=reason,
        promote_baseline=False,
    )
    payload = {"ok": True, "run": run.to_dict(), "config": config.to_dict()}
    if as_json:
        _emit_json(payload)
        return
    click.echo(f"Rejected: {run.run_id}")


@research.command("scoreboard")
@click.option("--repo-root", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option("--limit", default=10, show_default=True, type=int, help="Number of rows to display.")
@click.option("--json", "as_json", is_flag=True, help="Emit JSON.")
def research_scoreboard(repo_root: Path | None, limit: int, as_json: bool) -> None:
    """Show the current experiment frontier ordered by the tracked metric."""
    resolved_root = resolve_repo_root(repo_root)
    config = load_research_config(resolved_root)
    payload = _scoreboard_payload(resolved_root, config)
    if as_json:
        _emit_json(payload)
        return
    _print_scoreboard(payload, limit=limit)


def register_research_commands(cli_group: click.Group) -> None:
    """Register research-mode commands."""
    cli_group.add_command(research)
