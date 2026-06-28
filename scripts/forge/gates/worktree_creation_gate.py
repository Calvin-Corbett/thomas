#!/usr/bin/env python3
"""Debt-ceiling creation gate — the sanctioned front door for new worktrees.

Raw ``git worktree add`` is *discouraged*: it is invisible to the next agent and
bypasses the merge-debt ceiling. This command is the front door. Before creating
a worktree it:

  1. Refreshes and DISPLAYS the ledger (so the human/agent sees what exists).
  2. BLOCKS creation when DIRTY worktrees are at/above the configured ceiling
     (``[worktree_governance] max_dirty_worktrees``, default 5).
  3. REFUSES creation when an existing branch/worktree already matches the
     requested feature keyword (no duplicate efforts) unless ``--force`` with a
     ``--reason``.

Only after those checks pass does it create the worktree, then auto-refreshes the
ledger.

Usage:
    python scripts/forge/gates/worktree_creation_gate.py new <name> [--branch B]
        [--path P] [--force --reason "why"]
    python scripts/forge/gates/worktree_creation_gate.py check <name>   # dry-run

This is a *helper* front door, not a pre-commit enforcement hook, so it has no
runtime-guard shim — it is meant to be run directly by humans and agents.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _force_utf8_streams() -> None:
    """UTF-8 stdout/stderr so glyphs render on a cp1252 console instead of crashing."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, ValueError):
            pass


_force_utf8_streams()

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from scripts.crew import worktree_ledger
except ImportError:  # pragma: no cover - import path varies by run context
    _crew = _REPO_ROOT / "scripts" / "crew"
    if str(_crew) not in sys.path:
        sys.path.insert(0, str(_crew))
    import worktree_ledger  # type: ignore

ROOT = _REPO_ROOT

# Words too generic to count as a feature keyword for collision detection.
_STOP_WORDS = frozenset(
    {
        "feat",
        "feature",
        "fix",
        "bugfix",
        "wip",
        "chore",
        "refactor",
        "exp",
        "experiment",
        "spike",
        "the",
        "and",
        "for",
        "new",
        "old",
        "tmp",
        "temp",
        "test",
        "main",
        "dev",
        "branch",
        "work",
    }
)


def _keywords(name: str, branch: str = "") -> list[str]:
    """Extract meaningful feature keywords from a worktree name/branch."""
    tokens: list[str] = []
    seen: set[str] = set()
    for source in (name, branch):
        for raw in re.split(r"[^a-zA-Z0-9]+", str(source or "").lower()):
            token = raw.strip()
            if len(token) >= 3 and token not in _STOP_WORDS and token not in seen:
                seen.add(token)
                tokens.append(token)
    return tokens


def _git_branches(root: Path) -> list[str]:
    """List local + remote branch names (defensive)."""
    code, out, _ = worktree_ledger._run_git(["branch", "-a", "--format=%(refname:short)"], cwd=root)
    if code != 0:
        return []
    return [line.strip() for line in out.splitlines() if line.strip()]


@dataclass
class CreationDecision:
    name: str
    requested_branch: str
    allowed: bool
    blocked_reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    collisions: list[str] = field(default_factory=list)
    ledger: worktree_ledger.Ledger | None = None


def evaluate_creation(
    root: Path,
    name: str,
    *,
    branch: str = "",
    force: bool = False,
    reason: str = "",
) -> CreationDecision:
    """Decide whether a new worktree may be created. Reads only — never creates.

    Blocking conditions:
      * DIRTY worktrees >= ceiling.
      * keyword collision with an existing branch/worktree (unless --force+reason).
    """
    ledger = worktree_ledger.collect(root)
    decision = CreationDecision(name=name, requested_branch=branch, allowed=True, ledger=ledger)

    # ── Debt ceiling ──
    ceiling = ledger.config.max_dirty_worktrees
    if ledger.dirty_count >= ceiling:
        decision.allowed = False
        decision.blocked_reasons.append(
            f"You have {ledger.dirty_count} unmerged (DIRTY) worktree(s), at/above the ceiling of "
            f"{ceiling}. Consolidate before opening another. (run `thomas consolidate`)"
        )

    # ── Keyword collision ──
    keywords = _keywords(name, branch)
    existing_branches = _git_branches(root)
    collisions: list[str] = []
    for row in ledger.linked:
        haystack = f"{row.branch} {row.purpose}".lower()
        for kw in keywords:
            if kw in haystack:
                collisions.append(f"worktree '{row.branch or row.path}' (purpose: {row.purpose}) matches '{kw}'")
                break
    for existing in existing_branches:
        low = existing.lower()
        for kw in keywords:
            if kw in low and not any(existing in c for c in collisions):
                collisions.append(f"branch '{existing}' matches '{kw}'")
                break
    decision.collisions = collisions

    if collisions:
        if force and reason.strip():
            decision.warnings.append(
                f"Keyword collision overridden via --force (reason: {reason.strip()}). "
                "Proceeding despite existing related work."
            )
        else:
            decision.allowed = False
            detail = "; ".join(collisions[:5])
            decision.blocked_reasons.append(
                f"Existing work already matches this feature keyword — {detail}. "
                'Reuse/merge it, or pass --force --reason "<why a parallel effort is justified>".'
            )

    return decision


def _default_path(root: Path, name: str) -> Path:
    """Compute a default worktree location grouped beside the repo.

    e.g. <repo>.worktrees/<name>. Cross-platform via pathlib; no machine paths.
    """
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "-", name.strip()).strip("-") or "worktree"
    return root.parent / f"{root.name}.worktrees" / safe


def create_worktree(
    root: Path,
    name: str,
    *,
    branch: str = "",
    path: Path | None = None,
) -> tuple[bool, str]:
    """Run ``git worktree add`` then refresh the ledger. Returns (ok, message)."""
    target = path or _default_path(root, name)
    args = ["worktree", "add"]
    if branch:
        args += ["-b", branch, str(target)]
    else:
        args += [str(target), name]
    code, out, err = worktree_ledger._run_git(args, cwd=root)
    if code != 0:
        return False, f"git worktree add failed: {err.strip() or out.strip()}"
    worktree_ledger.update(root)
    return True, f"created worktree at {target} (ledger refreshed)"


def _print_decision(decision: CreationDecision) -> None:
    if decision.ledger is not None:
        print(worktree_ledger.render_table(decision.ledger))
        print("")
    if decision.warnings:
        for warning in decision.warnings:
            print(f"⚠ {warning}")
    if decision.allowed:
        print("✓ creation gate: PASS")
    else:
        print("✗ creation gate: BLOCKED")
        for item in decision.blocked_reasons:
            print(f"  - {item}")


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sanctioned front door for creating git worktrees.")
    sub = parser.add_subparsers(dest="command")
    for cmd in ("new", "check"):
        sp = sub.add_parser(cmd, help="Create a worktree" if cmd == "new" else "Dry-run the gate checks only.")
        sp.add_argument("name", help="Short worktree/feature name.")
        sp.add_argument("--branch", default="", help="Branch to create (-b). Defaults to checking out <name>.")
        sp.add_argument("--path", default="", help="Explicit worktree path (defaults to <repo>.worktrees/<name>).")
        sp.add_argument("--force", action="store_true", help="Override a keyword collision (requires --reason).")
        sp.add_argument("--reason", default="", help="Justification required with --force.")
        sp.add_argument("--root", default=str(ROOT), help="Repository root.")
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 2

    root = Path(args.root).expanduser()
    decision = evaluate_creation(
        root,
        args.name,
        branch=args.branch,
        force=bool(args.force),
        reason=args.reason,
    )
    _print_decision(decision)

    if args.command == "check":
        return 0 if decision.allowed else 1

    # new
    if not decision.allowed:
        return 1
    path = Path(args.path).expanduser() if args.path else None
    ok, message = create_worktree(root, args.name, branch=args.branch, path=path)
    print(message)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(run())
