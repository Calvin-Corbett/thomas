#!/usr/bin/env python3
"""Gate to enforce mandatory worktree discipline instructions."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AGENTS = ROOT / "AGENTS.md"
DEFAULT_RULES = ROOT / "WORKTREE_RULES.md"

REQUIRED_AGENTS_SNIPPETS = [
    "## Worktree Discipline",
    "Read `WORKTREE_RULES.md` before making edits.",
    "Use only the explicitly assigned worktree path for the task.",
    "If no worktree is specified, use the current repo root.",
    "Do not edit multiple worktrees in one task unless explicitly requested.",
    "Do not create, remove, move, or rebind worktrees without explicit user approval.",
    "If branch/worktree intent is unclear, stop and ask before editing.",
    "If git status --porcelain is not clean, do not start normal implementation work in that repo.",
]

REQUIRED_RULES_SNIPPETS = [
    "# Worktree Rules (Required)",
    "Current worktrees:",
    "Use `git worktree list --porcelain` as the source of truth for local branch paths.",
    "`main` is the public branch users should care about.",
    "If no worktree is specified, use the current repo root.",
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
        rules_text = _load_text(Path(args.rules))
    except Exception as exc:
        print("Worktree rules gate: FAIL")
        print(f"- {exc}")
        return 1

    missing_agents = _missing_snippets(agents_text, REQUIRED_AGENTS_SNIPPETS)
    for item in missing_agents:
        violations.append(f"AGENTS.md missing required snippet: {item}")

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
