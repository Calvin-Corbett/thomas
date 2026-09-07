"""Thomas can open a pull request from a task (frontier parity: Claude Code, Codex, Cursor).

Drives ``gh pr create`` in the working directory. It never pushes unless asked,
never invents a title, and says plainly when the GitHub CLI is missing.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from thomas.tools import git as git_tools


def _stub(monkeypatch, outcomes):
    calls: list[list[str]] = []

    async def fake_run(args, cwd):  # noqa: ANN001
        calls.append(list(args))
        rc, out, err = outcomes.pop(0)
        return rc, out, err

    monkeypatch.setattr(git_tools, "_gh_run", fake_run)
    return calls


def test_creates_a_pull_request_with_title_body_base_and_draft(monkeypatch, tmp_path: Path) -> None:
    calls = _stub(monkeypatch, [(0, "https://github.com/o/r/pull/12\n", "")])

    result = asyncio.run(
        git_tools.GitPullRequestTool(tmp_path).execute(
            {"title": "Add thing", "body": "Why and how.", "base": "dev", "draft": True}
        )
    )

    assert result.ok is True
    assert "pull/12" in str(result.data)
    assert calls[0][:3] == ["pr", "create", "--title"]
    assert "--base" in calls[0] and "dev" in calls[0] and "--draft" in calls[0]
    assert "Why and how." in calls[0]


def test_pushes_first_only_when_asked(monkeypatch, tmp_path: Path) -> None:
    pushed: list[list[str]] = []

    async def fake_git(args, cwd):  # noqa: ANN001
        pushed.append(list(args))
        return 0, "", ""

    monkeypatch.setattr(git_tools, "_git_run", fake_git)
    calls = _stub(monkeypatch, [(0, "https://github.com/o/r/pull/13\n", "")])

    result = asyncio.run(git_tools.GitPullRequestTool(tmp_path).execute({"title": "T", "body": "B", "push": True}))

    assert result.ok is True
    assert pushed and pushed[0][:2] == ["push", "-u"]
    assert calls[0][:2] == ["pr", "create"]


def test_refuses_without_a_title_and_reports_a_missing_cli(monkeypatch, tmp_path: Path) -> None:
    no_title = asyncio.run(git_tools.GitPullRequestTool(tmp_path).execute({"body": "B"}))
    assert no_title.ok is False and "title" in str(no_title.error)

    _stub(monkeypatch, [(-1, "", "gh executable not found in PATH")])
    missing = asyncio.run(git_tools.GitPullRequestTool(tmp_path).execute({"title": "T", "body": "B"}))
    assert missing.ok is False and "gh" in str(missing.error) and "install" in str(missing.error).lower()
