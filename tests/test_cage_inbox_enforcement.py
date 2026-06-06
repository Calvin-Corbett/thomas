"""Tests for the cage's scope-aware coordination enforcement (PROBLEM 2).

Calvin chose scope-aware (2026-06-02): the cage blocks a worker's submission
only on *relevant* unread messages (`commit_master._inbox_blocking`) -- must-read
kinds (blocker/scope_change) or messages whose subject paths overlap the files
being submitted. It reuses `message.unread_messages` and composes with (does not
duplicate) the repo-wide block-on-any pre-commit gate `workboard_inbox.py`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import scripts.crew.workboard.message as message
from scripts.forge import commit_master


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=False)


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "plans" / "thomas").mkdir(parents=True)
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "T")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "initial")
    return repo


def _workboard(repo: Path, *, claims: str = "- none", tasks: str = "- none") -> Path:
    path = repo / "plans" / "thomas" / "WORKBOARD.md"
    path.write_text(
        (
            "# Thomas Workboard\n\nLast updated: 2026-06-02\n\n"
            "## Agent Claims (Active)\n\n"
            f"{claims}\n\n"
            "## Active Tasks\n\n"
            f"{tasks}\n\n"
            "## Issues / Blockers\n\n- none\n\n"
            "## Up For Grabs\n\n- none\n\n"
            "## Supporting Docs (Not Plan Sources)\n\n- docs/PROJECT_SCOPE.md\n"
        ),
        encoding="utf-8",
    )
    return path


def _send(workboard: Path, **kwargs) -> str:
    kwargs.setdefault("require_claims_to_have_active_task", False)
    ok, payload = message.send_message(workboard, **kwargs)
    assert ok, payload
    return str(payload["message"]["msg_id"])


def _stage(repo: Path, rel: str, content: str = "x = 1\n") -> None:
    target = repo / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(repo, "add", rel)


def _blocking(repo: Path, wb: Path, agent: str) -> list[dict]:
    return commit_master._inbox_blocking(wb, agent, repo, None)


# --- inline relevance helpers (dotfile/url normalization regressions) -------- #
def test_paths_overlap_dotfiles() -> None:
    assert commit_master._co_paths_overlap(".github/workflows/ci.yml", ".github")
    assert commit_master._co_paths_overlap("./scripts/cage/x.ps1", "scripts/cage")
    assert not commit_master._co_paths_overlap(".github", "github")
    assert not commit_master._co_paths_overlap("scripts/cageyard", "scripts/cage")


def test_path_tokens_keep_dot_and_skip_urls() -> None:
    assert commit_master._co_path_tokens("do not edit .github/workflows now") == [".github/workflows"]
    assert commit_master._co_path_tokens("see https://example.com/x/y for docs") == []
    assert commit_master._co_path_tokens("touch scripts/cage, please.") == ["scripts/cage"]


# --- scope-aware relevance against a real staged diff ------------------------ #
def test_path_token_overlap_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    wb = _workboard(repo)
    _send(
        wb,
        sender="claude",
        recipient="codex",
        summary="please do not touch scripts/cage while I finish the sandbox",
        kind="coordination",
        task_id="none",
    )
    _stage(repo, "scripts/cage/launch.ps1", "Write-Host hi\n")
    blocking = _blocking(repo, wb, "codex")
    assert len(blocking) == 1
    assert "scripts/cage" in blocking[0]["_reasons"][0]


def test_unrelated_commit_not_blocked(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    wb = _workboard(repo)
    _send(
        wb,
        sender="claude",
        recipient="codex",
        summary="please do not touch scripts/cage while I finish the sandbox",
        kind="coordination",
        task_id="none",
    )
    _stage(repo, "thomas/agriculture/foo.py")
    assert _blocking(repo, wb, "codex") == []


@pytest.mark.parametrize("kind", ["blocker", "scope_change"])
def test_must_read_kind_blocks_regardless_of_path(tmp_path: Path, kind: str) -> None:
    repo = _init_repo(tmp_path)
    wb = _workboard(repo)
    _send(wb, sender="claude", recipient="codex", summary="stop and read", kind=kind, task_id="t")
    _stage(repo, "thomas/anything/unrelated.py")
    blocking = _blocking(repo, wb, "codex")
    assert len(blocking) == 1
    assert kind in blocking[0]["_reasons"][0]


def test_plain_offscope_coordination_does_not_block(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    wb = _workboard(repo)
    _send(wb, sender="claude", recipient="codex", summary="general fyi no paths", kind="coordination", task_id="none")
    _stage(repo, "thomas/x.py")
    assert _blocking(repo, wb, "codex") == []


@pytest.mark.parametrize(
    "summary,requested_action",
    [
        ("do not submit yet", "none"),
        ("landing is on hold", "none"),
        ("coordination needed", "ack before commit"),
    ],
)
def test_unscoped_submission_hold_blocks(tmp_path: Path, summary: str, requested_action: str) -> None:
    repo = _init_repo(tmp_path)
    wb = _workboard(repo)
    _send(
        wb,
        sender="claude",
        recipient="codex",
        summary=summary,
        requested_action=requested_action,
        kind="coordination",
        task_id="none",
    )
    _stage(repo, "feature.py")
    blocking = _blocking(repo, wb, "codex")
    assert len(blocking) == 1
    assert "submit/commit hold directive" in blocking[0]["_reasons"][0]


def test_task_scope_linkage_blocks(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    wb = _workboard(
        repo,
        claims="- agent=codex; scope=thomas/server; task=routes",
        tasks="- task_id=server-lane; agent=codex; scope=thomas/server/routes; summary=routes; status=active",
    )
    _send(
        wb,
        sender="claude",
        recipient="codex",
        summary="heads up on the routes work (no path token)",
        kind="coordination",
        task_id="server-lane",
    )
    _stage(repo, "thomas/server/routes/chat.py")
    assert _blocking(repo, wb, "codex")


def test_messages_to_other_agents_do_not_block_me(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    wb = _workboard(repo)
    _send(wb, sender="codex", recipient="gemini", summary="do not touch scripts/cage", kind="scope_change", task_id="t")
    _stage(repo, "scripts/cage/x.ps1", "Write-Host hi\n")
    assert _blocking(repo, wb, "codex") == []


def test_ack_clears_the_block(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    wb = _workboard(repo)
    mid = _send(wb, sender="claude", recipient="codex", summary="STOP", kind="blocker", task_id="t")
    _stage(repo, "thomas/x.py")
    assert _blocking(repo, wb, "codex")
    ok, _ = message.ack_message(wb, msg_id=mid, actor="codex")
    assert ok
    assert _blocking(repo, wb, "codex") == []


# --- end-to-end cage enforcement via create_submission ----------------------- #
def test_submit_blocked_while_relevant_message_unread(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    wb = _workboard(repo)
    _send(wb, sender="claude", recipient="codex", summary="do not touch scripts/cage", kind="scope_change", task_id="t")
    layout = commit_master.CageLayout(root=tmp_path / "cage")
    layout.ensure()
    _stage(repo, "scripts/cage/thing.ps1", "Write-Host hi\n")
    with pytest.raises(commit_master.InboxBlockedError) as exc:
        commit_master.create_submission(
            layout=layout, repo=repo, agent="codex", message="touch", base="HEAD", workboard=wb
        )
    assert exc.value.blocking
    assert not list(layout.inbox.glob("sub-*"))


def test_submit_succeeds_when_inbox_clear(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    wb = _workboard(repo)
    layout = commit_master.CageLayout(root=tmp_path / "cage")
    layout.ensure()
    _stage(repo, "feature.py")
    sub_dir = commit_master.create_submission(
        layout=layout, repo=repo, agent="codex", message="ok", base="HEAD", workboard=wb
    )
    assert (sub_dir / "submission.json").exists()


def test_submit_unblocked_after_ack(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    wb = _workboard(repo)
    mid = _send(wb, sender="claude", recipient="codex", summary="STOP", kind="blocker", task_id="t")
    layout = commit_master.CageLayout(root=tmp_path / "cage")
    layout.ensure()
    _stage(repo, "feature.py")
    with pytest.raises(commit_master.InboxBlockedError):
        commit_master.create_submission(layout=layout, repo=repo, agent="codex", message="x", base="HEAD", workboard=wb)
    message.ack_message(wb, msg_id=mid, actor="codex")
    sub_dir = commit_master.create_submission(
        layout=layout, repo=repo, agent="codex", message="x", base="HEAD", workboard=wb
    )
    assert (sub_dir / "submission.json").exists()


def test_unrelated_unread_does_not_wedge_submit(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    wb = _workboard(repo)
    _send(wb, sender="claude", recipient="codex", summary="general fyi no paths", kind="coordination", task_id="none")
    layout = commit_master.CageLayout(root=tmp_path / "cage")
    layout.ensure()
    _stage(repo, "feature.py")
    sub_dir = commit_master.create_submission(
        layout=layout, repo=repo, agent="codex", message="ok", base="HEAD", workboard=wb
    )
    assert (sub_dir / "submission.json").exists()
