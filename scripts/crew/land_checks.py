#!/usr/bin/env python3
"""Preflight checks for land.py (Landing Lane component B).

Each check returns a StepResult whose `fix` field is a concrete next command —
fix-it cards, not dead ends. land.py orchestrates these; keeping them here
also keeps both files under the per-commit growth cap on purpose.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ALLOWED_SIGNERS = "docs/ops/allowed_signers"

# Files whose modification requires the owner-tap (Windows Hello breakglass)
# flow. Mirror of agent_safety.toml's intent — we detect early and route to
# commit_guarded rather than letting CI reject the PR later. The authoritative
# list lives in agent_safety.toml; this is a fast-path detector, fail-open to
# the real gate (protected_files_gate still runs in CI either way).
PROTECTED_HINTS = (
    "agent_safety.toml",
    "AGENTS.md",
    "GUARDRAILS.md",
    ".pre-commit-config.yaml",
    "pyproject.toml",
    "thomas.toml",
    "thomas.prod.toml",
    "thomas/_architecture.py",
    "scripts/forge/gates/",
    "scripts/crew/brief/commit.py",
    "scripts/commit_breakglass_guard.py",
    "scripts/breakglass_auth.py",
    "scripts/commit_guarded.py",
    "evolve_corpus/",
    ".github/workflows/gates.yml",
    "docs/ops/allowed_signers",
)


@dataclass
class StepResult:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""


def run_cmd(args: list[str], *, cwd: Path, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=timeout, check=False)


def git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return run_cmd(["git", *args], cwd=repo)


def gh(repo: Path, *args: str, timeout: int = 300) -> subprocess.CompletedProcess[str]:
    return run_cmd(["gh", *args], cwd=repo, timeout=timeout)


def card(step: StepResult) -> str:
    head = "OK  " if step.ok else "FAIL"
    lines = [f"[{head}] {step.name}"]
    if step.detail:
        lines.extend(f"    {ln}" for ln in step.detail.strip().splitlines()[:12])
    if not step.ok and step.fix:
        lines.append(f"    FIX: {step.fix}")
    return "\n".join(lines)


def check_preconditions(repo: Path, base: str, remote: str) -> list[StepResult]:
    out: list[StepResult] = []
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
    if branch in {base, "main", "HEAD"}:
        out.append(
            StepResult(
                "preconditions.branch",
                False,
                f"current branch is '{branch}'",
                "create a unit branch first: git checkout -b <agent>/<unit>-<date> then re-run",
            )
        )
    else:
        out.append(StepResult("preconditions.branch", True, f"on {branch}"))

    dirty = git(repo, "status", "--porcelain").stdout.strip()
    if dirty:
        out.append(
            StepResult(
                "preconditions.clean_tree",
                False,
                f"uncommitted changes present:\n{dirty[:800]}",
                "commit through scripts/crew/brief/commit.py (scoped) or stash before landing",
            )
        )
    else:
        out.append(StepResult("preconditions.clean_tree", True))

    ahead = git(repo, "rev-list", "--count", f"{remote}/{base}..HEAD").stdout.strip()
    if ahead == "0":
        out.append(
            StepResult(
                "preconditions.has_commits",
                False,
                f"branch has no commits ahead of {remote}/{base}",
                "commit your unit first; nothing to land",
            )
        )
    else:
        out.append(StepResult("preconditions.has_commits", True, f"{ahead} commit(s) ahead"))
    return out


def detect_protected(repo: Path, base_ref: str) -> StepResult:
    diff = git(repo, "diff", "--name-only", f"{base_ref}...HEAD").stdout.splitlines()
    hits = sorted(
        {
            f
            for f in (x.strip().replace("\\", "/") for x in diff)
            if f and any(f == h.rstrip("/") or f.startswith(h) for h in PROTECTED_HINTS)
        }
    )
    if hits:
        return StepResult(
            "protected_files.detect",
            False,
            "protected files in this diff:\n" + "\n".join(hits[:20]),
            'these need the owner tap: commit them via `python scripts/commit_guarded.py --agent <id> -m "..."` '
            "(Windows Hello breakglass) BEFORE landing; do not add approval trailers by hand",
        )
    return StepResult("protected_files.detect", True, "no protected files in diff")


def rebase_onto_base(repo: Path, base: str, remote: str) -> StepResult:
    fetch = git(repo, "fetch", remote, base)
    if fetch.returncode != 0:
        return StepResult("rebase.fetch", False, fetch.stderr.strip()[:400], "check network/credentials, re-run")
    behind = git(repo, "rev-list", "--count", f"HEAD..{remote}/{base}").stdout.strip()
    if behind == "0":
        return StepResult("rebase", True, "already on top of base")
    rebase = git(repo, "rebase", f"{remote}/{base}")
    if rebase.returncode != 0:
        conflict = git(repo, "diff", "--name-only", "--diff-filter=U").stdout.strip()
        git(repo, "rebase", "--abort")
        return StepResult(
            "rebase",
            False,
            f"rebase onto {remote}/{base} conflicts in:\n{conflict[:600]}",
            f"resolve manually: git rebase {remote}/{base}, fix conflicts file-by-file, git rebase --continue, "
            "then re-run land.py. Do NOT start a new branch on top of this one.",
        )
    return StepResult("rebase", True, f"rebased over {behind} new base commit(s)")


def verify_signatures(repo: Path, base: str, remote: str) -> StepResult:
    """Pre-flight the exact signed-commits check CI runs (G/U only)."""
    signers = repo / ALLOWED_SIGNERS
    if signers.exists():
        git(repo, "config", "gpg.ssh.allowedSignersFile", str(signers))
    shas = git(repo, "rev-list", f"{remote}/{base}..HEAD").stdout.split()
    bad: list[str] = []
    for sha in shas:
        status = git(repo, "log", "-1", "--format=%G?", sha).stdout.strip()
        if status not in {"G", "U"}:
            subject = git(repo, "log", "-1", "--format=%s", sha).stdout.strip()
            bad.append(f"{sha[:10]}[{status}] {subject[:60]}")
    if bad:
        return StepResult(
            "signatures",
            False,
            "commits that will FAIL the required signed-commits check:\n" + "\n".join(bad),
            "re-sign the chain: for each commit rebuild with `git commit-tree <tree> -p <parent> -S` "
            "(see docs/SIGNING_KEY_SETUP.md), or soft-reset and re-commit via scripts/crew/brief/commit.py "
            "(it signs when commit.gpgsign=true)",
        )
    return StepResult("signatures", True, f"{len(shas)} commit(s) verify G/U")


def check_growth(repo: Path, base_ref: str, max_growth: int = 300) -> StepResult:
    """Pre-flight the commit-growth guard the way CI runs it: base..HEAD aggregate."""
    diff = git(repo, "diff", "--name-only", f"{base_ref}...HEAD").stdout.splitlines()
    over: list[str] = []
    for rel in (x.strip().replace("\\", "/") for x in diff):
        if not rel or Path(rel).suffix.lstrip(".").lower() not in {"py", "js", "ts", "css", "html", "mjs"}:
            continue
        head_n = len(git(repo, "show", f"HEAD:{rel}").stdout.splitlines())
        base_n = len(git(repo, "show", f"{base_ref}:{rel}").stdout.splitlines())
        if head_n - base_n > max_growth:
            over.append(f"{rel}: {base_n} -> {head_n} (+{head_n - base_n})")
    if over:
        return StepResult(
            "growth",
            False,
            f"files exceeding the {max_growth}-line aggregate growth cap:\n" + "\n".join(over[:10]),
            "split into smaller modules (semantic names — *_part* names are banned); the guard measures "
            "base..head aggregate, so splitting across commits does NOT help",
        )
    return StepResult("growth", True, "all files within the growth cap")


def rehearse_gates(repo: Path) -> list[StepResult]:
    """Run the CI gates that bit us historically and are cheap locally."""
    out: list[StepResult] = []
    checks: tuple[tuple[str, list[str], str], ...] = (
        (
            "gate.enforcement_integrity",
            [sys.executable, "scripts/forge/gates/enforcement_integrity.py"],
            "if you legitimately changed an enforcement script: regenerate via "
            "--generate-manifest and land the manifest through the owner-tap flow",
        ),
        (
            "gate.plan_structure",
            [sys.executable, "scripts/forge/gates/plan_structure_gate.py"],
            "add the missing plan references to plans/thomas/README.md and the WORKBOARD "
            "Canonical Plan Pointers section (new plans/ files must be referenced in both)",
        ),
        (
            "gate.workboard_task_problems",
            [sys.executable, "scripts/forge/gates/workboard_task_problems.py"],
            "run `python scripts/crew/tasks/manager.py --sync-plans --apply` then "
            "`git add -f` the generated PLAN.md/PROBLEM.md (problems/ is gitignored); "
            "use slug-safe task ids (no colons/brackets)",
        ),
        (
            "gate.public_repo_leak",
            [sys.executable, "scripts/forge/gates/public_repo_leak_guard.py"],
            "scrub the flagged term(s) from the listed files; never add gate exceptions for real leaks",
        ),
    )
    for name, cmd, fix in checks:
        proc = run_cmd(cmd, cwd=repo, timeout=300)
        ok = proc.returncode == 0
        tail = "\n".join((proc.stdout or proc.stderr or "").strip().splitlines()[-6:])
        out.append(StepResult(name, ok, tail, "" if ok else fix))
    return out
