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
@click.option("--json", "as_json", is_flag=True, help="Machine-readable output.")
@click.option("--repo", default=".", show_default=True, help="Repository root.")
def consolidate_command(
    trunk: str,
    ceiling: int,
    active_days: int,
    namespace: str,
    apply_: bool,
    as_json: bool,
    repo: str,
) -> None:
    """Find branch sprawl and retire what is provably safe to retire."""
    git = subprocess_git_runner(repo)
    try:
        report = survey(git, trunk=trunk, active_days=active_days, ceiling=ceiling, namespace=namespace)
    except BranchCustodianError as exc:
        raise click.ClickException(f"Could not read the repository: {exc}") from exc

    result = consolidate(git, report, apply=apply_)

    if as_json:
        click.echo(_json.dumps({"report": report.as_dict(), "result": result.as_dict()}, indent=2, sort_keys=True))
        raise SystemExit(0 if result.ok else 1)

    click.echo(click.style(report.summary(), bold=True))
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
