"""``thomas consolidate`` -- the branch-sprawl remedy.

The worktree debt alarm has recommended this command for a long time
(``CONSOLIDATE_HINT``) without it existing. This is that command.

It is written for someone who does not read git plumbing: it says how many
branches there are, how many can be retired safely, and how many carry work
only a human should decide about. It changes nothing unless asked with
``--apply``, and it never deletes a branch carrying unique content.
"""

from __future__ import annotations

import json as _json
from pathlib import Path

import click

from thomas.forge.branch_custodian import (
    DEFAULT_ACTIVE_DAYS,
    DEFAULT_BRANCH_CEILING,
    DEFAULT_TRUNK,
    Action,
    BranchCustodianError,
    consolidate,
    subprocess_git_runner,
    survey,
)
from thomas.forge.consolidation_plan import advise, render_plan
from thomas.forge.consolidation_plan import subprocess_git_runner as plan_git_runner

_MAX_LISTED = 15


def _echo_rows(title: str, rows, *, show_files: bool = False) -> None:
    if not rows:
        return
    click.echo("")
    click.echo(click.style(title, bold=True))
    for row in rows[:_MAX_LISTED]:
        detail = f"  ({len(row.unique_files)} files)" if show_files and row.unique_files else ""
        click.echo(f"  {row.name}{detail}")
    if len(rows) > _MAX_LISTED:
        click.echo(f"  ... and {len(rows) - _MAX_LISTED} more")


def _run_audit(git, *, repo: str, trunk: str, ceiling: int, namespace: str, as_json: bool) -> None:
    """Background mode: let the repository police itself."""
    from thomas.forge.consolidation_hold import audit as run_audit

    try:
        result = run_audit(git, repo, trunk=trunk, ceiling=ceiling, namespace=namespace, now=_utc_stamp)
    except BranchCustodianError as exc:
        raise click.ClickException(f"Could not read the repository: {exc}") from exc

    if as_json:
        click.echo(_json.dumps(result.as_dict(), indent=2, sort_keys=True))
        return

    click.echo(click.style(result.report.summary(), bold=True))
    if result.hold_placed:
        # FIX ROUND 1 (2026-08-27, adversarial review IMP-2): this used to
        # claim "new branches are blocked until this clears" -- false.
        # guard_new_branch (the only function that could make that true) has
        # zero callers anywhere in this codebase. Say what is actually true.
        click.echo(
            click.style(
                "Consolidation hold PLACED -- recorded only; nothing currently consults it "
                "at branch creation, so this does not by itself block a new branch. "
                "Push-time enforcement is branch_claim_gate.py (CI today; local pre-push "
                "wiring rides the prepared tap).",
                fg="yellow",
            )
        )
    elif result.hold_released:
        click.echo(click.style("Consolidation hold lifted -- back under the ceiling.", fg="green"))
    for note in result.notes:
        click.echo(f"  {note}")


def _utc_stamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _divergence_plan(repo: Path, trunk: str):
    """Every OTHER way work sits outside the trunk, and the next move for each.

    Branch count is one dimension of five. This command read green on
    2026-09-03 while the trunk was 75 commits unpushed and the public repo 891
    behind, and a person did that consolidation by hand. Never let a failure
    here break the branch audit that already worked: an empty plan is honest,
    a crashed command is not.
    """
    try:
        import sys as _sys

        scripts_forge = Path(__file__).resolve().parents[2] / "scripts" / "forge"
        if str(scripts_forge) not in _sys.path:
            _sys.path.insert(0, str(scripts_forge))
        import trunk_divergence  # type: ignore[import-not-found]

        findings = trunk_divergence.build_report(repo=repo, trunk=trunk, scan_clones=False).findings
        return advise(findings, git=plan_git_runner(repo), trunk=trunk)
    except (ImportError, OSError, ValueError):
        return []


@click.command("consolidate")
@click.option("--trunk", default=DEFAULT_TRUNK, show_default=True, help="Branch everything is compared against.")
@click.option(
    "--ceiling", default=DEFAULT_BRANCH_CEILING, show_default=True, help="Branch count that counts as sprawl."
)
@click.option(
    "--active-days",
    default=DEFAULT_ACTIVE_DAYS,
    show_default=True,
    help="Branches touched within this many days are left alone.",
)
@click.option("--namespace", default="refs/heads", show_default=True, help="Ref namespace to audit.")
@click.option("--apply", "apply_", is_flag=True, help="Actually retire the safe branches (default is a dry run).")
@click.option(
    "--audit",
    "audit_",
    is_flag=True,
    help="Background mode: place or lift the consolidation hold automatically, then exit.",
)
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.option("--repo", default=".", show_default=True, help="Repository root.")
def consolidate_command(
    trunk: str,
    ceiling: int,
    active_days: int,
    namespace: str,
    apply_: bool,
    audit_: bool,
    as_json: bool,
    repo: str,
) -> None:
    """Find branch sprawl and retire what is provably safe to retire."""
    git = subprocess_git_runner(repo)

    if audit_:
        _run_audit(git, repo=repo, trunk=trunk, ceiling=ceiling, namespace=namespace, as_json=as_json)
        return

    try:
        report = survey(git, trunk=trunk, active_days=active_days, ceiling=ceiling, namespace=namespace)
    except BranchCustodianError as exc:
        raise click.ClickException(f"Could not read the repository: {exc}") from exc

    result = consolidate(git, report, apply=apply_, repo_root=Path(repo))
    plan = _divergence_plan(Path(repo), trunk)

    if as_json:
        click.echo(
            _json.dumps(
                {
                    "report": report.as_dict(),
                    "result": result.as_dict(),
                    "plan": [{"dimension": a.dimension, "do": a.do, "why": a.why, "actor": a.actor} for a in plan],
                },
                indent=2,
                sort_keys=True,
            )
        )
        raise SystemExit(0 if result.ok else 1)

    click.echo(click.style(report.summary(), bold=True))
    if plan:
        click.echo("")
        click.echo(render_plan(plan))
    if report.over_ceiling:
        click.echo(
            click.style(
                f"  Over the ceiling ({report.total} > {ceiling}) -- worth consolidating before starting new work.",
                fg="yellow",
            )
        )

    _echo_rows("Safe to retire (already in trunk):", report.by_action(Action.DELETE))
    _echo_rows("Safe to retire (diverged, but nothing unique left):", report.by_action(Action.ARCHIVE_AND_DELETE))
    _echo_rows("Carries work trunk does not have -- your call:", report.needs_decision, show_files=True)

    click.echo("")
    if not apply_:
        retirable = len(report.reclaimable)
        if retirable:
            click.echo(f"Dry run -- nothing changed. Re-run with --apply to retire {retirable} branch(es).")
        else:
            click.echo("Dry run -- nothing to retire automatically.")
    else:
        click.echo(f"Retired {len(result.deleted)} branch(es); archived {len(result.archived)} first.")
        if result.flagged:
            click.echo(f"Left {len(result.flagged)} branch(es) alone -- they carry unique work.")
        for err in result.errors:
            click.echo(click.style(f"  could not retire {err}", fg="red"))

    raise SystemExit(0 if result.ok else 1)
