#!/usr/bin/env python3
"""Block edits when branch is used from the wrong local worktree path."""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
DISABLE_ENV = "THOMAS_WORKTREE_BRANCH_GUARD_DISABLE"
PRIMARY_THOMAS_ROOT = r"C:\Users\corbe\Thomas"

EXPECTED_BY_BRANCH = {
    "master": r"C:\Users\corbe\Thomas",
    "release/oss-launch": r"C:\Users\corbe\thomas-oss-launch",
    "publish-clean": r"C:\Users\corbe\Thomas_publish_clean",
}

# Explicitly approved linked worktrees. Anything else is treated as a side
# checkout, so an agent cannot make proof in a hidden clone/worktree and call it
# production evidence for the real Thomas repository.
APPROVED_EXTRA_WORKTREE_ROOTS: tuple[str, ...] = (r"C:\Users\corbe\tmp\thomas_heartbeat_l1",)


def _normalize_path(value: str | Path) -> str:
    text = str(value).replace("\\", "/").rstrip("/")
    return text.lower()


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _branch_name() -> str:
    cmd = ["git", "rev-parse", "--abbrev-ref", "HEAD"]
    proc = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"git branch detection failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _approved_worktree_roots() -> set[str]:
    roots = [PRIMARY_THOMAS_ROOT, *EXPECTED_BY_BRANCH.values(), *APPROVED_EXTRA_WORKTREE_ROOTS]
    return {_normalize_path(root) for root in roots if str(root).strip()}


def _canonical_common_git_dir() -> str:
    return _normalize_path(Path(PRIMARY_THOMAS_ROOT) / ".git")


def _git_common_dir() -> str:
    proc = subprocess.run(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git common-dir detection failed: {proc.stderr.strip()}")
    raw = proc.stdout.strip()
    if not raw:
        raise RuntimeError("git common-dir detection returned an empty path")
    path = Path(raw)
    if not path.is_absolute():
        path = ROOT / path
    return str(path.resolve())


def _topology_violations(branch: str) -> list[str]:
    actual_root = _normalize_path(ROOT)
    approved_roots = _approved_worktree_roots()
    canonical_common = _canonical_common_git_dir()
    common_dir = _normalize_path(_git_common_dir())

    violations: list[str] = []
    if actual_root not in approved_roots:
        if common_dir == canonical_common:
            violations.append(
                "unapproved linked worktree detected: "
                f"branch '{branch}' is running from '{ROOT}', which is not an approved Thomas worktree."
            )
        else:
            violations.append(
                "side clone detected: "
                f"branch '{branch}' is running from '{ROOT}' with git database '{common_dir}', "
                f"not the canonical Thomas git database '{canonical_common}'."
            )
        return violations

    if common_dir != canonical_common:
        violations.append(
            "repo topology drift detected: "
            f"approved worktree '{ROOT}' is not attached to the canonical Thomas git database "
            f"'{canonical_common}' (actual: '{common_dir}')."
        )

    return violations


def _local_branch_names() -> list[str]:
    """All local branch names (one per line, no leading marker)."""
    proc = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _branch_tip(name: str) -> str:
    """Commit hash at the tip of `name`. Empty string if the branch is unknown."""
    proc = subprocess.run(
        ["git", "rev-parse", "--verify", f"{name}^{{commit}}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def _is_ancestor(commit: str, ref: str) -> bool:
    """True if `commit` is an ancestor of `ref` (i.e., reachable from it)."""
    if not commit or not ref:
        return False
    proc = subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, ref],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


# Canonical base branches that topic branches may legitimately stack on.
CANONICAL_BASE_BRANCHES: tuple[str, ...] = ("master", "release/oss-launch", "publish-clean")


def _is_topic_branch(name: str) -> bool:
    """A topic branch is any branch that isn't one of the canonical bases."""
    return name not in CANONICAL_BASE_BRANCHES


def _runtime_protection_disabled() -> bool:
    """B9: only a validly SIGNED disable flag counts (presence alone does not)."""
    try:
        from scripts.forge.gates._runtime_guard import runtime_protection_disabled
    except ImportError:  # pragma: no cover - import path varies by run context
        try:
            from forge.gates._runtime_guard import runtime_protection_disabled
        except ImportError:
            from _runtime_guard import runtime_protection_disabled
    return runtime_protection_disabled(ROOT)


def run(_argv: Sequence[str] | None = None) -> int:
    # Honour the runtime protection toggle (requires Windows auth to disable).
    if _runtime_protection_disabled():
        print("Worktree branch guard: PASS (runtime protection disabled by human)")
        return 0
    if _truthy(os.environ.get(DISABLE_ENV)):
        print(f"Worktree branch guard: SKIP ({DISABLE_ENV}=1)")
        return 0

    # CI environments skip the worktree-PATH check (CI runners check out the
    # default path, not the per-branch path). The topic-branch-stacking check
    # below still runs because it's a branch-state check, not a path check.
    ci_env = _truthy(os.environ.get("CI"))

    try:
        branch = _branch_name()
    except Exception as exc:
        print("Worktree branch guard: FAIL")
        print(f"- {exc}")
        return 1

    if not ci_env:
        try:
            topology_violations = _topology_violations(branch)
        except Exception as exc:
            print("Worktree branch guard: FAIL")
            print(f"- {exc}")
            return 1
        if topology_violations:
            print("Worktree branch guard: FAIL")
            for violation in topology_violations:
                print(f"- {violation}")
            print("- work only from the assigned canonical Thomas checkout or an explicitly approved linked worktree")
            print(f"- override only when intentional: set {DISABLE_ENV}=1")
            return 1

    if not ci_env:
        expected = EXPECTED_BY_BRANCH.get(branch)
        if expected:
            actual_norm = _normalize_path(ROOT)
            expected_norm = _normalize_path(expected)
            if actual_norm != expected_norm:
                print("Worktree branch guard: FAIL")
                print(f"- branch '{branch}' must run from: {expected}")
                print(f"- current worktree path is: {ROOT}")
                print(f"- override only when intentional: set {DISABLE_ENV}=1")
                return 1
    else:
        expected = None

    # Topic-branch-stacking check: if the current branch is a topic branch,
    # ensure it doesn't have another unmerged topic branch as an ancestor.
    # Topic branches must start directly from canonical base branches
    # (master, main, release/oss-launch, publish-clean).
    if _is_topic_branch(branch):
        current_tip = _branch_tip(branch)
        if current_tip:
            base_tips = {name: _branch_tip(name) for name in CANONICAL_BASE_BRANCHES}
            local_branches = _local_branch_names()
            unmerged_ancestors: list[str] = []
            for other in local_branches:
                if other == branch or not _is_topic_branch(other):
                    continue
                other_tip = _branch_tip(other)
                if not other_tip or not _is_ancestor(other_tip, current_tip):
                    continue
                already_merged = any(base_tip and _is_ancestor(other_tip, base_tip) for base_tip in base_tips.values())
                if not already_merged:
                    unmerged_ancestors.append(other)
            if unmerged_ancestors:
                print("Worktree branch guard: FAIL")
                print("- topic branches must start directly from canonical base branches")
                print(f"  (one of: {', '.join(CANONICAL_BASE_BRANCHES)}).")
                print(f"- branch '{branch}' is stacked on these unmerged topic ancestors:")
                for ancestor in sorted(unmerged_ancestors):
                    print(f"  - {ancestor}")
                return 1

    print("Worktree branch guard: PASS")
    if expected:
        print(f"- branch '{branch}' is in expected worktree path")
    elif _is_topic_branch(branch):
        print(f"- branch '{branch}' has no unmerged topic-branch ancestors")
    else:
        print(f"- branch '{branch}' is not mapped; no path restriction")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
