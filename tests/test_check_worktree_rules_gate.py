from __future__ import annotations

from pathlib import Path

import scripts.check_worktree_rules_gate as mod


def test_worktree_rules_gate_passes_with_dirty_worktree_policy(tmp_path: Path, capsys) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "\n".join(
            [
                "## Worktree discipline (required)",
                "Read `WORKTREE_RULES.md` before making edits.",
                "Use only the explicitly assigned worktree path for the task.",
                "If no worktree is specified, use the canonical development worktree reported by `git worktree list` for `master`.",
                "Do not edit multiple worktrees in one task unless explicitly requested.",
                "Do not create, remove, move, or rebind worktrees without explicit user approval.",
                "If branch/worktree intent is unclear, stop and ask before editing.",
                "If `git status --porcelain` is not clean, do not start normal implementation work in that repo.",
            ]
        ),
        encoding="utf-8",
    )
    rules = tmp_path / "WORKTREE_RULES.md"
    rules.write_text(
        "\n".join(
            [
                "# Worktree Rules (Required)",
                "Current worktrees:",
                "- Use `git worktree list --porcelain` as the source of truth for local branch paths.",
                "- `master` is the default development path.",
                "If `git status --porcelain` is not clean, do not start normal implementation work in that repo until it is cleaned or an explicit audited dirty-worktree override is being used for cleanup/remediation.",
            ]
        ),
        encoding="utf-8",
    )

    rc = mod.run(["--agents", str(agents), "--rules", str(rules)])
    out = capsys.readouterr().out

    assert rc == 0
    assert "Worktree rules gate: PASS" in out


def test_worktree_rules_gate_fails_when_dirty_worktree_policy_missing(tmp_path: Path, capsys) -> None:
    agents = tmp_path / "AGENTS.md"
    agents.write_text(
        "\n".join(
            [
                "## Worktree discipline (required)",
                "Read `WORKTREE_RULES.md` before making edits.",
                "Use only the explicitly assigned worktree path for the task.",
                "If no worktree is specified, use the canonical development worktree reported by `git worktree list` for `master`.",
                "Do not edit multiple worktrees in one task unless explicitly requested.",
                "Do not create, remove, move, or rebind worktrees without explicit user approval.",
                "If branch/worktree intent is unclear, stop and ask before editing.",
            ]
        ),
        encoding="utf-8",
    )
    rules = tmp_path / "WORKTREE_RULES.md"
    rules.write_text(
        "\n".join(
            [
                "# Worktree Rules (Required)",
                "Current worktrees:",
                "- Use `git worktree list --porcelain` as the source of truth for local branch paths.",
            ]
        ),
        encoding="utf-8",
    )

    rc = mod.run(["--agents", str(agents), "--rules", str(rules)])
    out = capsys.readouterr().out

    assert rc == 1
    assert "AGENTS.md missing required snippet" in out
