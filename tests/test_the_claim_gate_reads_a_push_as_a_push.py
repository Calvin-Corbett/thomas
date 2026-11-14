"""The claim gate takes a real pre-push run with nothing staged as nothing to judge, and judges everything at commit time.

Proves scripts.forge.gates.workboard_agent_claim and scripts.forge.gates._commit_base: an agent with no claim passes on a
real pre-push range (pre-commit's own signals, both refs, a range that exists and holds a commit) with nothing staged,
through the audited push fallback of scripts.crew.brief.push_claim. The to-ref alone, refs with no pre-push signal, a
range that is empty or unreadable, a staged file, an unresolved issue, another agent's overlapping claim, and a git
error all still stop it; an agent that holds a claim takes the claim branch.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import scripts.crew.brief.push_claim as push_claim
import scripts.forge.gates.workboard_agent_claim as gate

CLEAN = (
    "# Thomas Workboard\n\n## Agent Claims (Active)\n\n{claims}\n\n## Active Tasks\n\n{tasks}\n\n"
    "## Issues / Blockers\n\n{issues}\n\n## Up For Grabs\n\n- none\n"
)
SIGNALS = (
    "PRE_COMMIT_FROM_REF",
    "PRE_COMMIT_TO_REF",
    "PRE_COMMIT_REMOTE_NAME",
    "PRE_COMMIT_REMOTE_URL",
    "PRE_COMMIT_HOOK_STAGE",
)


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return done.stdout.strip()


@pytest.fixture
def repo(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    _git(work, "init", "-q")
    _git(work, "config", "user.email", "t@example.com")
    _git(work, "config", "user.name", "t")
    for n in (1, 2):
        (work / "f.txt").write_text(f"{n}\n")
        _git(work, "add", "-A")
        _git(work, "commit", "-qm", f"c{n}")
    monkeypatch.setattr(gate, "ROOT", work)
    return work


def _board(tmp_path: Path, *, claims="- none", tasks="- none", issues="- none") -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(CLEAN.format(claims=claims, tasks=tasks, issues=issues), encoding="utf-8")
    return path


def _run(
    board: Path, monkeypatch, capsys, *, env: dict[str, str], stage_real_file: str | None = None
) -> tuple[int, dict]:
    for key in ("AGENT_ID", "THOMAS_AGENT_ID", "THOMAS_AGENT_NAME", "CLAUDE_AGENT_ID", *SIGNALS):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.delenv(gate.FALLBACK_SCOPE_ENV, raising=False)
    monkeypatch.delenv(gate.FALLBACK_REASON_ENV, raising=False)
    monkeypatch.setenv("AGENT_ID", "claude")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setattr(gate, "_runtime_protection_disabled", lambda: False)
    if stage_real_file:
        (gate.ROOT / stage_real_file).write_text("staged\n")
        _git(gate.ROOT, "add", stage_real_file)
    code = gate.run(["--workboard", str(board), "--enforce-staged-scope", "--json"])
    return code, json.loads(capsys.readouterr().out.strip().splitlines()[-1])


PUSH = {"PRE_COMMIT_FROM_REF": "HEAD~1", "PRE_COMMIT_TO_REF": "HEAD", "PRE_COMMIT_HOOK_STAGE": "pre-push"}


def test_a_commit_time_run_with_no_claim_is_refused(repo, tmp_path, monkeypatch, capsys) -> None:
    code, payload = _run(_board(tmp_path), monkeypatch, capsys, env={})
    assert code == 1
    assert "no active workboard claim" in payload["error"]


def test_a_real_pre_push_run_with_nothing_staged_passes_with_no_claim(repo, tmp_path, monkeypatch, capsys) -> None:
    code, payload = _run(_board(tmp_path), monkeypatch, capsys, env=PUSH)
    assert code == 0, payload
    assert payload["scope_source"] == "explicit_fallback"
    assert payload["fallback_reason"] == push_claim.PUSH_REASON


def test_pre_commits_own_remote_pair_is_enough_to_say_pre_push(repo, tmp_path, monkeypatch, capsys) -> None:
    env = {"PRE_COMMIT_FROM_REF": "HEAD~1", "PRE_COMMIT_TO_REF": "HEAD"}
    env |= {"PRE_COMMIT_REMOTE_NAME": "origin", "PRE_COMMIT_REMOTE_URL": "x"}
    code, payload = _run(_board(tmp_path), monkeypatch, capsys, env=env)
    assert code == 0, payload


@pytest.mark.parametrize(
    "env",
    [
        {"PRE_COMMIT_TO_REF": "HEAD", "PRE_COMMIT_HOOK_STAGE": "pre-push"},
        {"PRE_COMMIT_TO_REF": "HEAD"},
        {"PRE_COMMIT_FROM_REF": "HEAD~1", "PRE_COMMIT_TO_REF": "HEAD"},
        {**PUSH, "PRE_COMMIT_FROM_REF": "0" * 40},
        {**PUSH, "PRE_COMMIT_FROM_REF": "HEAD"},
        {**PUSH, "PRE_COMMIT_FROM_REF": "no-such-ref"},
    ],
)
def test_anything_short_of_a_real_pre_push_range_still_demands_a_claim(
    repo, tmp_path, monkeypatch, capsys, env
) -> None:
    code, payload = _run(_board(tmp_path), monkeypatch, capsys, env=env)
    assert code == 1
    assert "no active workboard claim" in payload["error"]


def test_a_commit_time_run_with_the_push_variables_set_and_a_staged_file_still_fails(
    repo, tmp_path, monkeypatch, capsys
) -> None:
    code, payload = _run(_board(tmp_path), monkeypatch, capsys, env=PUSH, stage_real_file="g.txt")
    assert code == 1
    assert "no active workboard claim" in payload["error"]


def test_a_staged_file_cannot_ride_on_the_push_fallback(repo, tmp_path, monkeypatch, capsys) -> None:
    board = _board(tmp_path)
    env = {**PUSH, gate.FALLBACK_SCOPE_ENV: push_claim.PUSH_SCOPE, gate.FALLBACK_REASON_ENV: push_claim.PUSH_REASON}
    code, payload = _run(board, monkeypatch, capsys, env=env, stage_real_file="g.txt")
    assert code == 1
    assert payload["staged_files_outside_scope"] == ["g.txt"]


def test_a_git_error_refuses_instead_of_reading_nothing_staged(repo, tmp_path, monkeypatch, capsys) -> None:
    board = _board(
        tmp_path,
        claims="- agent=claude; scope=thomas; task=work",
        tasks="- task_id=t1; agent=claude; scope=thomas; summary=work; status=active",
    )
    monkeypatch.setattr(gate, "ROOT", tmp_path / "not-a-repo-and-not-there")
    code, payload = _run(board, monkeypatch, capsys, env=PUSH)
    assert code == 1
    assert "could not list the staged files" in payload["error"]


def test_a_git_error_does_not_pass_a_push_with_no_claim(repo, tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(gate, "ROOT", tmp_path / "not-a-repo-and-not-there")
    code, _payload = _run(_board(tmp_path), monkeypatch, capsys, env=PUSH)
    assert code == 1


def test_an_agent_that_holds_a_claim_takes_the_claim_branch_on_a_push(repo, tmp_path, monkeypatch, capsys) -> None:
    board = _board(
        tmp_path,
        claims="- agent=claude; scope=thomas; task=work",
        tasks="- task_id=t1; agent=claude; scope=thomas; summary=work; status=active",
    )
    code, payload = _run(board, monkeypatch, capsys, env=PUSH)
    assert code == 0, payload
    assert payload["scope_source"] == "workboard_claim"


def test_another_agents_overlapping_claim_still_stops_a_push(repo, tmp_path, monkeypatch, capsys) -> None:
    board = _board(
        tmp_path,
        claims="- agent=codex; scope=.; task=everything",
        tasks="- task_id=t1; agent=codex; scope=.; summary=s; status=active",
    )
    code, payload = _run(board, monkeypatch, capsys, env=PUSH)
    assert code == 1
    assert payload["conflicting_agents"] == ["codex"]


def test_an_unresolved_issue_owned_by_the_agent_still_stops_a_push(repo, tmp_path, monkeypatch, capsys) -> None:
    issue = "- issue_id=i1; task_id=t1; reporter=codex; owner=claude; state=open; summary=broken"
    task = "- task_id=t1; agent=codex; scope=thomas; summary=s; status=blocked"
    board = _board(tmp_path, claims="- agent=codex; scope=thomas; task=s", tasks=task, issues=issue)
    code, payload = _run(board, monkeypatch, capsys, env=PUSH)
    assert code == 1
    assert payload["unresolved_issue_ids"] == ["i1"]
