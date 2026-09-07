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


# Per-install worktree-topology config lives in the gitignored ``agent_safety.local.toml``
# overlay (section ``[worktree_branch_guard]``), NOT in tracked gate source — so no
# machine-specific absolute paths ship in the repo (portability + privacy/leak fix). With
# no overlay configured the topology guard is a NO-OP: a fresh clone on any machine is
# never false-blocked. The repo OWNER opts into strict canonical-checkout enforcement by
# setting ``primary_root`` (+ optional ``expected_by_branch`` / ``approved_extra_roots``)
# in that overlay.
def _overlay() -> dict[str, object]:
    try:
        import tomllib
    except ModuleNotFoundError:  # pragma: no cover - py<3.11
        return {}
    try:
        data = tomllib.loads((ROOT / "agent_safety.local.toml").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    section = data.get("worktree_branch_guard")
    return section if isinstance(section, dict) else {}


def _primary_root() -> str:
    """The owner-configured canonical Thomas checkout, or '' when unconfigured (no-op)."""
    return str(_overlay().get("primary_root") or "").strip()


def _expected_by_branch() -> dict[str, str]:
    raw = _overlay().get("expected_by_branch")
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def _approved_extra_roots() -> tuple[str, ...]:
    raw = _overlay().get("approved_extra_roots")
    return tuple(str(x) for x in raw) if isinstance(raw, (list, tuple)) else ()


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
    roots = [_primary_root(), *_expected_by_branch().values(), *_approved_extra_roots()]
    return {_normalize_path(root) for root in roots if str(root).strip()}


def _canonical_common_git_dir() -> str:
    return _normalize_path(Path(_primary_root()) / ".git")


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
    # Owner-opt-in: with no canonical anchor configured in the local overlay, do not
    # enforce checkout topology at all — a fresh clone on any machine must never be
    # false-blocked by someone else's absolute paths.
    if not _primary_root():
        return []
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


def _ref_sha(ref: str) -> str:
    """Sha for an exact, fully-qualified ref path via `git show-ref --verify`
    -- NO DWIM fallback, so a same-named tag can never stand in for the
    branch this guard means to check (the landed claim_evidence.py
    `_ref_resolves` pattern, 9ac14311/f7a523f0). Empty string when the ref
    does not exist or cannot be read.
    """
    try:
        proc = subprocess.run(
            ["git", "show-ref", "--verify", ref],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    if proc.returncode != 0 or not (proc.stdout or "").strip():
        return ""
    return (proc.stdout or "").strip().splitlines()[0].split(maxsplit=1)[0].strip()


def _head_ref() -> str:
    """Full refname HEAD points at (e.g. refs/heads/dev); '' when detached.
    `symbolic-ref` reads .git/HEAD directly -- no DWIM resolution."""
    proc = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def _local_branch_refs() -> list[tuple[str, str]]:
    """(bare_name, full_refname) for every local branch. The bare name is
    cut from for-each-ref's own %(refname) -- never from %(refname:short),
    whose disambiguation lengthens under a same-named tag (e.g. to
    heads/topic) and would then denote a different ref."""
    proc = subprocess.run(
        ["git", "for-each-ref", "--format=%(refname)", "refs/heads/"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return []
    out: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        full = line.strip()
        if full.startswith("refs/heads/"):
            out.append((full[len("refs/heads/") :], full))
    return out


def _branch_tip(name: str) -> str:
    """Commit hash at the tip of BRANCH `name`. Empty string if unknown.
    Resolved as the exact path refs/heads/<name> (or as given when already
    fully qualified) -- the old bare-name `rev-parse --verify
    {name}^{{commit}}` let a same-named tag shadow the branch
    (gitrevisions(7) tries refs/tags/ before refs/heads/), so a stray tag
    `dev` at HEAD silently bypassed the freshness check.
    """
    ref = name if name.startswith("refs/") else f"refs/heads/{name}"
    return _ref_sha(ref)


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
# `dev` is the day-to-day integration branch every topic branch should be cut
# from and rebased onto; it MUST be here or the guard reasons about the wrong base
# (the 2026-06-14 stale-branch incident: an agent worked a week on a branch cut
# off an old dev and Praxis never noticed because `dev` wasn't a recognized base).
CANONICAL_BASE_BRANCHES: tuple[str, ...] = ("dev", "main", "master", "release/oss-launch", "publish-clean")

# Integration bases in priority order — a topic branch's freshness is measured
# against the first one that exists locally.
_INTEGRATION_BASES: tuple[str, ...] = ("dev", "main", "master")

# A topic branch may be at most this many commits behind its integration base
# before a commit is blocked. Past this, you are building on code that has since
# changed under you — exactly the debt that silently breaks the next agent who
# doesn't know what moved. Rebase (or re-cut) before committing. Set deliberately
# low: the 2026-06-14 stale branch was only ~6 commits behind and still caused the
# whole mess, so a double-digit limit would be useless theater.
_MAX_COMMITS_BEHIND_BASE = 5
_MAX_BEHIND_ENV = "THOMAS_BRANCH_MAX_BEHIND"


def _commits_behind(base: str) -> int | None:
    """Commits on `base` not reachable from HEAD (how stale our base is).

    Returns None when it can't be determined (base missing, detached, etc.) so
    the caller can skip rather than false-positive.
    """
    tip = _branch_tip(base)
    if not tip:
        return None
    # `tip` is a sha -- passing the bare `base` name here would re-run the
    # DWIM resolution _branch_tip just avoided.
    proc = subprocess.run(
        ["git", "rev-list", "--count", f"HEAD..{tip}"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw.isdigit():
        return None
    return int(raw)


def _max_commits_behind() -> int:
    raw = str(os.environ.get(_MAX_BEHIND_ENV, "")).strip()
    if raw.isdigit():
        return max(0, int(raw))
    return _MAX_COMMITS_BEHIND_BASE


def freshness_violation(behind: int | None, *, limit: int) -> bool:
    """Pure decision: is the branch too far behind its base? (testable)."""
    if behind is None:
        return False
    return behind > max(0, int(limit))


def _branch_freshness_failure(branch: str) -> list[str]:
    """Block when the current topic branch is built on a stale base.

    Returns failure lines (empty = pass). Skips canonical bases themselves and
    cases where staleness can't be determined.
    """
    if branch in CANONICAL_BASE_BRANCHES:
        return []
    limit = _max_commits_behind()
    for base in _INTEGRATION_BASES:
        if base == branch:
            continue
        behind = _commits_behind(base)
        if behind is None:
            continue  # base not present locally; try the next
        if freshness_violation(behind, limit=limit):
            return [
                f"branch '{branch}' is {behind} commits behind '{base}' (limit {limit}).",
                "you are committing on a stale base — code you can't see has changed under you,",
                "which silently breaks the next agent. Bring it current before committing:",
                f"  git fetch && git rebase {base}        # or re-cut a fresh branch off {base}",
                f"tune the limit only with intent: {_MAX_BEHIND_ENV}=<n>",
            ]
        return []  # measured against the first available base; it's fresh enough
    return []


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
    # Branch freshness is enforced FIRST and is NOT suppressible by QuickBuilder
    # or the disable flags. Committing on a stale base creates debt that silently
    # breaks the next agent — that is a correctness guarantee, not workflow
    # friction, so no convenience mode may skip it. (Root cause of the 2026-06-14
    # incident: the whole guard was QuickBuilder-suppressed, and `dev` wasn't even
    # a recognized base.) The fix — rebase — is cheap; there is no reason to skip.
    try:
        _fresh_branch = _branch_name()
    # _branch_name shells out to git; an unreadable branch must leave the
    # freshness check skipped, never crash the guard that protects the tree.
    # RuntimeError included: _branch_name raises it verbatim when git cannot
    # detect a branch ("not a git repository"), which is exactly the case a
    # guard running outside a checkout must survive.
    except (OSError, subprocess.SubprocessError, ValueError, RuntimeError):
        _fresh_branch = ""
    if _fresh_branch:
        freshness_failure = _branch_freshness_failure(_fresh_branch)
        if freshness_failure:
            print("Worktree branch guard: FAIL (branch freshness)")
            for line in freshness_failure:
                print(f"- {line}")
            return 1

    try:
        from scripts.forge.gates._quickbuilder_guard import announce_suppressed
    except ImportError:  # pragma: no cover - import path varies by run context
        try:
            from forge.gates._quickbuilder_guard import announce_suppressed
        except ImportError:
            from _quickbuilder_guard import announce_suppressed
    if announce_suppressed("thomas-worktree-branch-guard", ROOT, "Worktree branch guard"):
        return 0
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
        expected = _expected_by_branch().get(branch)
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
        # The current branch's tip comes from HEAD's own full refname --
        # `branch` (from --abbrev-ref) can be a lengthened short form under
        # a same-named tag, which refs/heads/-qualifying would then miss.
        head_ref = _head_ref()
        current_tip = _ref_sha(head_ref) if head_ref else ""
        if current_tip:
            base_tips = {name: _branch_tip(name) for name in CANONICAL_BASE_BRANCHES}
            local_branches = _local_branch_refs()
            unmerged_ancestors: list[str] = []
            for other, other_full in local_branches:
                if other_full == head_ref or not _is_topic_branch(other):
                    continue
                other_tip = _ref_sha(other_full)
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

    # (Branch freshness already enforced at the top of run(), before any
    # suppression — see there.)

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
