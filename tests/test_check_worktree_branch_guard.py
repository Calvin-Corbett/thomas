from __future__ import annotations

from pathlib import Path

import scripts.check_worktree_branch_guard as mod


def test_branch_guard_passes_when_branch_is_not_mapped(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "_branch_name", lambda: "feature/public-docs")
    monkeypatch.setattr(mod, "_worktree_paths_by_branch", lambda: {})

    rc = mod.run([])
    out = capsys.readouterr().out

    assert rc == 0
    assert "is not mapped by git worktree list" in out


def test_branch_guard_passes_when_current_path_matches_expected(monkeypatch, capsys, tmp_path: Path) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "_branch_name", lambda: "feature/public-docs")
    monkeypatch.setattr(mod, "_worktree_paths_by_branch", lambda: {"feature/public-docs": str(tmp_path)})

    rc = mod.run([])
    out = capsys.readouterr().out

    assert rc == 0
    assert "is in expected worktree path" in out


def test_branch_guard_fails_when_current_path_does_not_match_expected(
    monkeypatch,
    capsys,
    tmp_path: Path,
) -> None:
    expected = tmp_path / "expected"
    actual = tmp_path / "actual"
    actual.mkdir()

    monkeypatch.setattr(mod, "ROOT", actual)
    monkeypatch.setattr(mod, "_branch_name", lambda: "feature/public-docs")
    monkeypatch.setattr(mod, "_worktree_paths_by_branch", lambda: {"feature/public-docs": str(expected)})

    rc = mod.run([])
    out = capsys.readouterr().out

    assert rc == 1
    assert "must run from" in out
    assert str(expected) in out
