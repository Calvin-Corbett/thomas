"""`thomas ship` -- end-to-end wrap-up: dirty tree -> GitHub dev -> local sync.

Thin CLI front-end over ``scripts/forge/ship.py``. The heavy lifting (commit
through the gates, push, owner-override merge into protected ``dev``, and
syncing the merged ``dev`` back to this machine) lives in the engine so it can
also be driven from automation. This command just locates the repo root and
hands off, because ``scripts/`` is not part of the installed package.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

try:
    import click
except ImportError:
    from thomas._vendor import click_shim as click  # type: ignore

logger = logging.getLogger(__name__)


def _find_repo_root() -> Path | None:
    """Find a Thomas checkout root that has scripts/forge/ship.py."""
    candidates: list[Path] = [Path.cwd()]
    try:
        import thomas

        pkg = Path(thomas.__file__).resolve().parent
        candidates += [pkg.parent, pkg.parent.parent]
    except ImportError:
        pass
    for base in candidates:
        for up in [base, *base.parents]:
            if (up / "scripts" / "forge" / "ship.py").exists():
                return up
    return None


def register_ship_commands(cli_group: click.Group) -> None:
    """Register the ``ship`` command on the CLI group."""

    @cli_group.command("ship")
    @click.option("-m", "--message", default="", help="Commit message (required if the tree is dirty).")
    @click.option("--base", default="dev", help="Branch to merge into (default: dev).")
    @click.option("--repo", default="Calvin-Corbett/thomas-dev", help="GitHub OWNER/REPO for the merge.")
    @click.option("--remote", default="dev-origin", help="Git remote to push to.")
    @click.option("--merge", "merge_method", type=click.Choice(["squash", "merge", "rebase"]), default="squash")
    @click.option("--pr", default=None, help="Existing PR number to land.")
    @click.option("--no-commit", is_flag=True, help="Skip the commit phase.")
    @click.option("--no-push", is_flag=True, help="Skip the push phase.")
    @click.option("--no-merge", is_flag=True, help="Stop after push (no dev merge).")
    @click.option("--no-sync", is_flag=True, help="Skip syncing dev back to this machine.")
    @click.option("--dry-run", is_flag=True, help="Show the plan without making changes.")
    def ship_cmd(
        message: str,
        base: str,
        repo: str,
        remote: str,
        merge_method: str,
        pr: str | None,
        no_commit: bool,
        no_push: bool,
        no_merge: bool,
        no_sync: bool,
        dry_run: bool,
    ) -> None:
        """Wrap up the current work: commit -> push -> merge to dev -> sync this machine.

        \b
        Examples:
          thomas ship -m "fix: parity"     # full loop to dev + local sync
          thomas ship -m "wip" --no-merge  # commit + push only
          thomas ship --dry-run -m "x"     # preview the plan, no side effects

        The code-quality and security gates are always enforced; the merge into
        protected dev uses the owner-override (one Windows credential tap).
        """
        root = _find_repo_root()
        if not root:
            click.echo(click.style("  Cannot find a Thomas checkout with scripts/forge/ship.py.", fg="red"))
            raise SystemExit(1)

        cmd = [sys.executable, str(root / "scripts" / "forge" / "ship.py")]
        if message:
            cmd += ["-m", message]
        cmd += ["--base", base, "--repo", repo, "--remote", remote, "--merge", merge_method]
        if pr:
            cmd += ["--pr", str(pr)]
        for flag, enabled in (
            ("--no-commit", no_commit),
            ("--no-push", no_push),
            ("--no-merge", no_merge),
            ("--no-sync", no_sync),
            ("--dry-run", dry_run),
        ):
            if enabled:
                cmd.append(flag)

        # Run from the current directory so ship anchors to the active worktree.
        raise SystemExit(subprocess.run(cmd).returncode)
