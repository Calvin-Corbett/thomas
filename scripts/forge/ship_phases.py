#!/usr/bin/env python3
"""Phase implementations + shared helpers for ``thomas ship``.

Split out of ``ship.py`` so each file stays within the per-commit growth cap and
the orchestrator reads as a clean sequence. See ``ship.py`` for the overview.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]


# ── shell helpers ────────────────────────────────────────────────


def run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a command, optionally capturing output. Raises on failure when check."""
    proc = subprocess.run(
        cmd,
        cwd=str(cwd or _REPO_ROOT),
        capture_output=capture,
        text=True,
        env=env,
    )
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip() if capture else ""
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{detail}")
    return proc


def git(args: list[str], *, cwd: Path | None = None, check: bool = True) -> str:
    return run(["git", *args], cwd=cwd, check=check).stdout.strip()


def say(phase: str, message: str) -> None:
    print(f"  [{phase}] {message}", flush=True)


# ── state probes ─────────────────────────────────────────────────


def current_branch(cwd: Path) -> str:
    return git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=cwd)


def has_uncommitted_changes(cwd: Path) -> bool:
    return bool(git(["status", "--porcelain"], cwd=cwd))


def quickbuilder_active() -> bool:
    """True iff a validly signed QuickBuilder flag is active."""
    try:
        sys.path.insert(0, str(_REPO_ROOT))
        from scripts.forge.gates._quickbuilder_guard import quickbuilder_active as _qb

        return bool(_qb(_REPO_ROOT))
    except Exception:
        return False


def resolve_agent(explicit: str | None) -> str:
    if explicit:
        return explicit
    for key in ("AGENT_ID", "THOMAS_AGENT_ID", "CLAUDE_AGENT_ID"):
        val = str(os.environ.get(key, "")).strip()
        if val:
            return val
    return "claude"


def find_pr(repo: str, base: str, head: str) -> str | None:
    proc = run(
        ["gh", "pr", "list", "--repo", repo, "--base", base, "--head", head, "--state", "open", "--json", "number"],
        check=False,
    )
    if proc.returncode != 0:
        return None
    try:
        rows = json.loads(proc.stdout or "[]")
    except (ValueError, json.JSONDecodeError):
        return None
    return str(rows[0]["number"]) if rows else None


# ── phases ───────────────────────────────────────────────────────


def phase_commit(cwd: Path, branch: str, message: str, agent: str, dry_run: bool) -> bool:
    """Stage everything and commit through the gates. Returns True if committed."""
    if not has_uncommitted_changes(cwd):
        say("commit", "working tree clean -- nothing to commit")
        return False

    if dry_run:
        files = git(["status", "--porcelain"], cwd=cwd)
        say("commit", f"DRY-RUN would: git add -A && git commit -m {message!r}")
        for line in files.splitlines()[:40]:
            say("commit", f"    {line}")
        return False

    if not quickbuilder_active():
        say(
            "commit",
            "QuickBuilder is OFF -- workflow gates will require a breakglass tap or block. "
            "Enable a smooth commit with: python scripts/quickbuilder_toggle.py on",
        )

    env = dict(os.environ)
    for key in ("AGENT_ID", "THOMAS_AGENT_ID", "CLAUDE_AGENT_ID"):
        env[key] = agent
    say("commit", "staging all changes (git add -A)")
    run(["git", "add", "-A"], cwd=cwd, env=env, capture=False)
    say("commit", "committing through the Forge gates...")
    proc = run(["git", "commit", "-m", message], cwd=cwd, env=env, capture=False, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            "commit blocked by a gate. If it was a workflow/coordination gate, enable QuickBuilder "
            "(python scripts/quickbuilder_toggle.py on) and re-run ship; if it was a code/security "
            "gate, fix the underlying issue -- ship never bypasses those."
        )
    say("commit", f"committed: {git(['rev-parse', '--short', 'HEAD'], cwd=cwd)}")
    return True


def phase_push(cwd: Path, branch: str, remote: str, dry_run: bool) -> None:
    if dry_run:
        say("push", f"DRY-RUN would: git push -u {remote} {branch}")
        return
    say("push", f"pushing {branch} -> {remote}")
    run(["git", "push", "-u", remote, branch], cwd=cwd, capture=False)
    say("push", "pushed")


def phase_merge(cwd: Path, repo: str, base: str, branch: str, pr: str | None, merge: str, dry_run: bool) -> str | None:
    resolved_pr = pr or find_pr(repo, base, branch)
    if dry_run:
        if resolved_pr:
            say("merge", f"DRY-RUN would: dev_land.py {resolved_pr} (--{merge} into {base})")
        else:
            say("merge", f"DRY-RUN would: gh pr create --base {base} --head {branch}, then dev_land it")
        return resolved_pr

    if not resolved_pr:
        say("merge", f"no open PR for {branch} -> creating one against {base}")
        title = git(["log", "-1", "--pretty=%s"], cwd=cwd)
        run(
            [
                "gh",
                "pr",
                "create",
                "--repo",
                repo,
                "--base",
                base,
                "--head",
                branch,
                "--title",
                title,
                "--body",
                "Shipped via `thomas ship`.",
            ],
            cwd=cwd,
            capture=False,
        )
        resolved_pr = find_pr(repo, base, branch)
        if not resolved_pr:
            raise RuntimeError("PR creation reported success but no open PR was found")

    say("merge", f"landing PR #{resolved_pr} into {base} via owner override (dev_land.py) -- expect a Windows tap")
    proc = run(
        [
            sys.executable,
            str(_REPO_ROOT / "scripts" / "dev_land.py"),
            str(resolved_pr),
            "--repo",
            repo,
            "--base",
            base,
            "--merge",
            merge,
        ],
        cwd=cwd,
        capture=False,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"dev_land.py failed for PR #{resolved_pr} (branch protection was restored by dev_land)")
    say("merge", f"PR #{resolved_pr} merged into {base}")
    return resolved_pr


def phase_sync(cwd: Path, remote: str, base: str, dry_run: bool) -> None:
    """Bring the freshly merged ``base`` (dev) back to this machine."""
    if dry_run:
        say("sync", f"DRY-RUN would: git fetch {remote} {base}; fast-forward local '{base}' + dev worktrees")
        return

    say("sync", f"fetching {remote}/{base}")
    run(["git", "fetch", remote, base], cwd=cwd, capture=False)
    new_tip = git(["rev-parse", "--short", f"{remote}/{base}"], cwd=cwd)
    say("sync", f"{remote}/{base} is now {new_tip}")

    worktrees = git(["worktree", "list", "--porcelain"], cwd=cwd)
    blocks = [b for b in worktrees.split("\n\n") if b.strip()]
    synced_any = False
    for block in blocks:
        path = ""
        wt_branch = ""
        for line in block.splitlines():
            if line.startswith("worktree "):
                path = line[len("worktree ") :].strip()
            elif line.startswith("branch "):
                wt_branch = line[len("branch ") :].strip().replace("refs/heads/", "")
        if wt_branch == base and path:
            res = run(["git", "merge", "--ff-only", f"{remote}/{base}"], cwd=Path(path), check=False)
            if res.returncode == 0:
                say("sync", f"fast-forwarded worktree on '{base}': {path}")
                synced_any = True
            else:
                say("sync", f"could NOT ff worktree {path} (diverged) -- left untouched")

    has_local_base = run(["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{base}"], cwd=cwd, check=False)
    if has_local_base.returncode == 0 and not synced_any:
        upd = run(["git", "update-ref", f"refs/heads/{base}", f"{remote}/{base}"], cwd=cwd, check=False)
        if upd.returncode == 0:
            say("sync", f"fast-forwarded local '{base}' ref -> {new_tip}")
    say("sync", "this machine now has the merged dev")
