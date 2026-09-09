"""An unresolvable `dev` ref is not a finding about the evidence (phase-1.4,
whole-branch review fix wave -- coordinator/reviewer finding, CRITICAL,
reproduced).

`claim_evidence._verify_commit` treats ANY nonzero `git merge-base
--is-ancestor <sha> dev` exit as a real "not an ancestor" failure (empty
`reason_code`, a positive finding the evidence sweep can act on). But that
command also exits nonzero when the TARGET ref (`dev`) itself does not
resolve in the checkout -- a shallow clone, a worktree without the branch,
or the common PR-CI shape with only `refs/remotes/origin/dev` and no local
`dev` branch at all. That case was never a finding about the commit sha;
nothing about the sha was ever actually checked. Before this fix, it fell
through to the same unmarked `"failed"` as a genuine non-ancestor sha, so
`claim_cleanup.py --evidence-sweep` expired verified dones on any checkout
where `dev` does not resolve.

Fixed with `claim_evidence._ref_resolves(ref, repo_root)`
(`git rev-parse --verify <ref>^{commit}`), probed on any nonzero merge-base
exit: target-unresolvable now routes to the existing
`REASON_CODE_GIT_UNAVAILABLE` (membership in `UNAVAILABLE_REASON_CODES` --
no new code needed, matches the OSError/db-absent cases already using it).
An unknown or genuinely non-ancestor sha on an otherwise-RESOLVABLE target
is unchanged: still `"failed"` with an empty `reason_code` (T1 contract 2,
pinned) -- the second test below is the regression guard proving the fix
did not widen too far.
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.crew.workboard import claim_evidence, claim_evidence_sweep


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def _head_sha(repo: Path) -> str:
    proc = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def _init_repo_on_branch(tmp_path: Path, branch: str) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(tmp_path, "init", "-b", branch, "repo")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    return repo


TASK_ID = "task-a"


def _board_with_done_evidence(repo: Path, *, sha: str, recorded_at: str) -> Path:
    board = repo / "plans" / "thomas" / "WORKBOARD.md"
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_text(
        "# Fixture Workboard\n\n"
        "## Agent Claims\n"
        "- agent=agent1; scope=foo; task=do the thing\n\n"
        "## Active Tasks\n"
        f"- task_id={TASK_ID}; agent=agent1; scope=foo; summary=do the thing; status=done; "
        f"evidence=commit:{sha}; evidence_recorded_at={recorded_at}\n\n"
        "## Up For Grabs\n"
        "- none\n\n"
        "## Issues / Blockers\n"
        "- none\n",
        encoding="utf-8",
        newline="\n",
    )
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed board")
    return board


def test_a_target_ref_that_does_not_resolve_is_git_unavailable_not_failed(tmp_path: Path) -> None:
    """A checkout with no branch literally named `dev` (the common PR-CI
    shape, a shallow clone, a worktree without the branch) -- the fixture
    here uses `main` as the checked-out branch and never creates `dev` at
    all, mirroring the session scratchpad's `nodev.py` repro."""
    repo = _init_repo_on_branch(tmp_path, "main")
    (repo / "work.txt").write_text("the work\n", encoding="utf-8")
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
    board = _board_with_done_evidence(repo, sha="0" * 40, recorded_at=old)
    real_sha = _head_sha(repo)
    # Re-point the board's evidence at the REAL landed sha (the placeholder
    # above just established the file/commit before we knew the real sha).
    text = board.read_text(encoding="utf-8").replace("commit:" + "0" * 40, f"commit:{real_sha}")
    board.write_text(text, encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture: point evidence at the real sha")

    ev = claim_evidence.parse_evidence(f"commit:{real_sha}")
    verdict = claim_evidence.verify_evidence(ev, repo, task_id=TASK_ID)

    assert verdict.status == "failed"
    assert verdict.reason_code == claim_evidence.REASON_CODE_GIT_UNAVAILABLE
    assert verdict.reason_code in claim_evidence.UNAVAILABLE_REASON_CODES
    assert "dev" in verdict.reason
    assert "does not resolve" in verdict.reason


def test_the_sweep_skips_instead_of_expiring_when_dev_does_not_resolve(tmp_path: Path) -> None:
    repo = _init_repo_on_branch(tmp_path, "main")
    (repo / "work.txt").write_text("the work\n", encoding="utf-8")
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat(timespec="seconds")
    board = _board_with_done_evidence(repo, sha="0" * 40, recorded_at=old)
    real_sha = _head_sha(repo)
    text = board.read_text(encoding="utf-8").replace("commit:" + "0" * 40, f"commit:{real_sha}")
    board.write_text(text, encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture: point evidence at the real sha")

    violations, candidates, skipped = claim_evidence_sweep.evidence_sweep_candidates(
        workboard_path=board,
        ttl_hours=72.0,
        now=datetime.now(timezone.utc),
        repo_root=repo,
        db_path=None,
    )

    assert violations == []
    assert candidates == [], "a verified-but-unreachable-dev done must never be expired"
    assert len(skipped) == 1
    assert skipped[0]["task_id"] == TASK_ID


def test_an_unknown_sha_on_a_resolvable_target_still_fails_regression_guard(tmp_path: Path) -> None:
    """T1 contract 2, pinned, must not be widened by the fix above: on a
    checkout where `dev` DOES resolve, an unknown/non-ancestor sha is still
    a real `"failed"` with an EMPTY `reason_code` -- not GIT_UNAVAILABLE."""
    repo = _init_repo_on_branch(tmp_path, "dev")
    (repo / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "seed commit")

    unknown_sha = "f" * 40
    ev = claim_evidence.parse_evidence(f"commit:{unknown_sha}")

    verdict = claim_evidence.verify_evidence(ev, repo, task_id=TASK_ID)

    assert verdict.status == "failed"
    assert verdict.reason_code == ""
    assert verdict.reason_code not in claim_evidence.UNAVAILABLE_REASON_CODES
