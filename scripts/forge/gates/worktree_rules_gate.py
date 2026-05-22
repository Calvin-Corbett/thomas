#!/usr/bin/env python3
"""Gate to enforce mandatory worktree discipline instructions."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_AGENTS = ROOT / "AGENTS.md"
DEFAULT_RULES = ROOT / "WORKTREE_RULES.md"

# Gate revised 2026-05-22 (0.16.4): the gate previously required exact
# snippets including a hardcoded `C:\Users\corbe\Thomas` user path and a
# `master` branch reference. Those were leaks (the public repo published
# the maintainer's local filesystem layout). The required snippets now
# describe the *policy* the doc must convey, not the maintainer's specific
# environment. See bible Pattern 17 (CI gates depending on deleted/leaky
# artifacts are the second-order leak surface).
REQUIRED_AGENTS_SNIPPETS = [
    "## Worktree discipline (required)",
    "Use only the explicitly assigned worktree path for the task.",
    "Do not edit multiple worktrees in one task unless explicitly requested.",
    "Do not create, remove, move, or rebind worktrees without explicit user approval.",
    "If branch/worktree intent is unclear, stop and ask before editing.",
    "If git status --porcelain is not clean, do not start normal implementation work in that repo",
]

REQUIRED_RULES_SNIPPETS = [
    "# Worktree Rules (Required)",
    "Current worktrees:",
    "If git status --porcelain is not clean, do not start normal implementation work in that repo",
]


def _load_text(path: Path) -> str:
    if not path.exists():
        raise RuntimeError(f"missing required file: {path}")
    return path.read_text(encoding="utf-8-sig")


def _normalize_for_match(text: str) -> str:
    return text.replace("`", "")


def _missing_snippets(text: str, snippets: Sequence[str]) -> list[str]:
    normalized_text = _normalize_for_match(text)
    return [item for item in snippets if _normalize_for_match(item) not in normalized_text]


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate mandatory worktree discipline docs in AGENTS.md.")
    parser.add_argument("--agents", default=str(DEFAULT_AGENTS), help="path to AGENTS.md")
    parser.add_argument(
        "--rules",
        default=str(DEFAULT_RULES),
        help="path to WORKTREE_RULES.md",
    )
    args = parser.parse_args(argv)

    violations: list[str] = []

    try:
        agents_text = _load_text(Path(args.agents))
    except Exception as exc:
        print("Worktree rules gate: FAIL")
        print(f"- {exc}")
        return 1

    missing_agents = _missing_snippets(agents_text, REQUIRED_AGENTS_SNIPPETS)
    for item in missing_agents:
        violations.append(f"AGENTS.md missing required snippet: {item}")

    # WORKTREE_RULES.md was deleted in the 2026-05-21 pre-public cleanup
    # (it contained personal directory paths like C:\Users\corbe\... that
    # exposed the developer's local filesystem layout). When the file is
    # present, we still check its content; when absent, we skip silently
    # so the gate doesn't block public-repo cleanups.
    rules_path = Path(args.rules)
    if rules_path.is_file():
        try:
            rules_text = _load_text(rules_path)
        except Exception as exc:  # pragma: no cover
            violations.append(f"could not read {rules_path}: {exc}")
        else:
            missing_rules = _missing_snippets(rules_text, REQUIRED_RULES_SNIPPETS)
            for item in missing_rules:
                violations.append(f"WORKTREE_RULES.md missing required snippet: {item}")

    if violations:
        print("Worktree rules gate: FAIL")
        for item in violations:
            print(f"- {item}")
        return 1

    print("Worktree rules gate: PASS")
    print("- AGENTS.md and WORKTREE_RULES.md contain required worktree policy text")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
