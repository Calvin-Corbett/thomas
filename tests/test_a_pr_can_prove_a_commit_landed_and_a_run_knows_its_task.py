"""Phase 2 batch 1, recon #6 + #7a: the two disclosed gaps in the phase-1.4
claims-verification system close.

Split out of tests/test_a_done_claim_carries_proof_or_it_is_not_done.py (the
file this evidence library's other coverage lives in) purely to stay under
monolith_guard's 800-line unbaselined-changed-file soft limit -- adding these
cases in place would have pushed that file from 750 to 878 lines. No shared
state with that file; fixtures below are self-contained duplicates of the
same shapes (`_git`/`_commit_at`/`fixture_repo`/`store`) rather than a
cross-file import, so this file can be read and understood on its own.

1. Ordered fallback ref resolution (recon #6): `claim_evidence.py`'s
   `VERIFY_TARGET_BRANCH` was a bare `"dev"`, so a PR-CI checkout with only
   `refs/remotes/origin/dev` always downgraded to an honest-but-unverified
   `git_unavailable` skip. `_resolve_verify_target_branch` now tries an
   ordered, FULLY QUALIFIED fallback (`refs/heads/dev`,
   `refs/remotes/origin/dev`, `refs/remotes/dev-origin/dev`) before giving
   up. Covered here: origin/dev-only now verifies; nothing resolving stays
   the same honest skip; when both `dev` and `origin/dev` resolve and
   disagree, `dev` wins (the order is pinned, not incidental).
1b. Qualified-ref spoofing (fix round 5, review I-1): the first version of
    this fallback used bare names, so a LOCAL branch created with any
    fallback's exact name (git allows slashes -- `git branch dev-origin/dev`
    is legal) shadowed the intended ref (`refs/heads` wins git's
    disambiguation over a same-named remote-tracking ref), verifying
    attacker/accidental garbage and hard-failing real evidence. Covered
    here: a local `dev-origin/dev` branch no longer wins when the real
    `refs/remotes/dev-origin/dev` also exists; a local `dev-origin/dev`
    branch alone (no qualified ref resolves) stays the honest
    `git_unavailable` skip, never a verification against garbage.
2. Run-kind task_id column binding (recon #7a): `start_chat_v2_run` now
   accepts an optional `task_id`, stamped through to a real `task_id` column
   on the run_store `runs` table. Covered here: a run created WITH a task_id
   is readable back through `get_run`'s metadata and binds by exact token;
   the same T-1/T-12 whole-token discipline that protects commit-kind
   binding applies to this column too; a run created WITHOUT one falls back
   to `not_before` only, never fabricating a binding.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from scripts.crew.workboard import claim_evidence

from thomas.marketplace.observability import run_store

BOUND_TASK_ID = "demo-task-123"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _commit_at(repo: Path, rel_path: str, content: str, message: str, committer_date: str) -> str:
    path = repo / rel_path
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", rel_path)
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = committer_date
    env["GIT_COMMITTER_DATE"] = committer_date
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True, capture_output=True, text=True, env=env)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _init_repo(repo: Path, *, branch: str) -> None:
    repo.mkdir()
    _git(repo, "init", "-b", branch)
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")


# ---------------------------------------------------------------------------
# 1. Ordered fallback ref resolution
# ---------------------------------------------------------------------------


@pytest.fixture
def fixture_repo_pr_shaped(tmp_path: Path) -> dict[str, object]:
    """Mirrors the common GitHub Actions PR-CI shape: only a remote-tracking
    `refs/remotes/origin/dev` resolves, no local `dev` branch exists at all
    (the checked-out branch here is deliberately named something else)."""
    repo = tmp_path / "repo"
    _init_repo(repo, branch="pr-branch")
    sha = _commit_at(repo, "a.txt", "a\n", f"wire up {BOUND_TASK_ID}", "2020-01-01T00:00:00+00:00")
    _git(repo, "update-ref", "refs/remotes/origin/dev", sha)
    return {"root": repo, "sha": sha}


def test_commit_evidence_verifies_via_origin_dev_fallback_on_a_pr_shaped_checkout(
    fixture_repo_pr_shaped: dict[str, object],
) -> None:
    ev = claim_evidence.parse_evidence(f"commit:{fixture_repo_pr_shaped['sha']}")

    verdict = claim_evidence.verify_evidence(ev, fixture_repo_pr_shaped["root"], task_id=BOUND_TASK_ID)  # type: ignore[arg-type]

    assert verdict.status == "verified"
    assert "origin/dev" in verdict.reason


def test_resolve_verify_target_branch_returns_none_when_nothing_resolves(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, branch="pr-branch")
    _commit_at(repo, "a.txt", "a\n", "add a.txt", "2020-01-01T00:00:00+00:00")

    assert claim_evidence._resolve_verify_target_branch(repo) is None


def test_resolve_verify_target_branch_prefers_dev_over_origin_dev_when_both_resolve(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo(repo, branch="dev")
    dev_sha = _commit_at(repo, "a.txt", "a\n", "add a.txt", "2020-01-01T00:00:00+00:00")
    # origin/dev points at an unrelated orphan history -- proves local `dev`
    # wins the fallback order even though origin/dev also resolves.
    _git(repo, "checkout", "--orphan", "unrelated")
    other_sha = _commit_at(repo, "z.txt", "z\n", "unrelated origin history", "2020-02-01T00:00:00+00:00")
    _git(repo, "update-ref", "refs/remotes/origin/dev", other_sha)
    _git(repo, "checkout", "dev")
    assert dev_sha  # sanity: dev's own commit exists

    target = claim_evidence._resolve_verify_target_branch(repo)

    assert target == "refs/heads/dev"


def test_a_local_branch_named_dev_origin_dev_does_not_shadow_the_real_remote_ref(tmp_path: Path) -> None:
    """Review I-1's repro: a local branch can be created with the exact same
    name as the third fallback entry (`git branch dev-origin/dev` is legal
    -- slashes are allowed in branch names). Before the fully-qualified fix,
    `refs/heads/dev-origin/dev` shadowed `refs/remotes/dev-origin/dev` (git's
    disambiguation prefers refs/heads), so an attacker/accidental local
    branch silently became the verification target. The qualified path must
    resolve the real remote-tracking ref, ignoring the same-named local one.
    """
    repo = tmp_path / "repo"
    _init_repo(repo, branch="pr-branch")
    legit_sha = _commit_at(repo, "a.txt", "a\n", f"wire up {BOUND_TASK_ID}", "2020-01-01T00:00:00+00:00")
    _git(repo, "update-ref", "refs/remotes/dev-origin/dev", legit_sha)
    # A LOCAL branch with the exact same name, pointing at unrelated garbage.
    _git(repo, "checkout", "--orphan", "attacker")
    garbage_sha = _commit_at(repo, "z.txt", "z\n", "attacker history", "2020-02-01T00:00:00+00:00")
    _git(repo, "branch", "dev-origin/dev", "attacker")
    _git(repo, "checkout", "pr-branch")

    target = claim_evidence._resolve_verify_target_branch(repo)
    assert target == "refs/remotes/dev-origin/dev"

    legit_ev = claim_evidence.parse_evidence(f"commit:{legit_sha}")
    legit_verdict = claim_evidence.verify_evidence(legit_ev, repo, task_id=BOUND_TASK_ID)
    assert legit_verdict.status == "verified"

    garbage_ev = claim_evidence.parse_evidence(f"commit:{garbage_sha}")
    garbage_verdict = claim_evidence.verify_evidence(garbage_ev, repo, task_id=BOUND_TASK_ID)
    assert garbage_verdict.status == "failed"
    assert garbage_verdict.reason_code == ""  # a real "not an ancestor" finding, not infrastructure absence


def test_a_local_branch_named_dev_origin_dev_alone_stays_git_unavailable_not_verified_against_garbage(
    tmp_path: Path,
) -> None:
    """No qualified ref resolves here -- only a same-NAMED local branch does
    -- so this must be the honest `git_unavailable` skip, never a
    verification (true or false) against the local branch's garbage history.
    """
    repo = tmp_path / "repo"
    _init_repo(repo, branch="pr-branch")
    _commit_at(repo, "seed.txt", "seed\n", "seed", "2020-01-01T00:00:00+00:00")
    _git(repo, "checkout", "--orphan", "attacker")
    garbage_sha = _commit_at(repo, "z.txt", "z\n", "attacker history", "2020-02-01T00:00:00+00:00")
    _git(repo, "branch", "dev-origin/dev", "attacker")
    _git(repo, "checkout", "pr-branch")

    assert claim_evidence._resolve_verify_target_branch(repo) is None

    ev = claim_evidence.parse_evidence(f"commit:{garbage_sha}")
    verdict = claim_evidence.verify_evidence(ev, repo, task_id=BOUND_TASK_ID)

    assert verdict.status == "failed"
    assert verdict.reason_code == claim_evidence.REASON_CODE_GIT_UNAVAILABLE


# ---------------------------------------------------------------------------
# 1c. The last ref trick: a branch literally NAMED "refs/heads/dev" (T3
# review, "next touch" ruling, phase-2 batch-2 task 1)
# ---------------------------------------------------------------------------
#
# Review I-1's fix (1b above) qualified the fallback names so a same-named
# LOCAL branch (e.g. `dev-origin/dev`) could not shadow a same-named
# REMOTE-TRACKING ref. But qualifying the name only moved the DWIM surface
# one level, because `_ref_resolves` used to check existence with `git
# rev-parse --verify <ref>^{commit}`, and `rev-parse` disambiguates a name
# that fails its OWN exact lookup by retrying it under `refs/heads/`,
# `refs/tags/`, etc. (gitrevisions(7)). `git branch refs/heads/dev
# <startpoint>` is legal -- slashes are allowed in branch names -- and git
# stores it at `refs/heads/refs/heads/dev`. Asking `rev-parse` to resolve
# `refs/heads/dev` when the REAL `refs/heads/dev` branch is absent then
# found that nested branch via its `refs/heads/<name>` fallback rule and
# verified against it -- reproduced by hand before this fix: `git rev-parse
# --verify refs/heads/dev^{commit}` exits 0 against the attacker's garbage
# commit, while `git show-ref --verify refs/heads/dev` correctly fails
# ("not a valid ref") because show-ref performs no fallback disambiguation
# at all. The fix (`_ref_resolves` now uses `show-ref --verify`, and
# `_verify_commit` passes the resolved SHA -- never the ref name -- to
# `merge-base`, exact-path end to end) is covered by the two tests below.


def test_a_nested_refs_heads_dev_branch_never_stands_in_for_an_absent_real_dev(tmp_path: Path) -> None:
    """The real `refs/heads/dev` is absent; only a local branch literally
    NAMED `refs/heads/dev` (pointing at garbage) exists, stored by git at
    `refs/heads/refs/heads/dev`. Must be the honest `git_unavailable` skip,
    never a verification (true or false) against the nested branch.
    """
    repo = tmp_path / "repo"
    _init_repo(repo, branch="pr-branch")
    _commit_at(repo, "seed.txt", "seed\n", "seed", "2020-01-01T00:00:00+00:00")
    _git(repo, "checkout", "--orphan", "attacker")
    garbage_sha = _commit_at(repo, "z.txt", "z\n", "attacker history", "2020-02-01T00:00:00+00:00")
    _git(repo, "branch", "refs/heads/dev", "attacker")
    _git(repo, "checkout", "pr-branch")

    assert claim_evidence._resolve_verify_target_branch(repo) is None

    ev = claim_evidence.parse_evidence(f"commit:{garbage_sha}")
    verdict = claim_evidence.verify_evidence(ev, repo, task_id=BOUND_TASK_ID)

    assert verdict.status == "failed"
    assert verdict.reason_code == claim_evidence.REASON_CODE_GIT_UNAVAILABLE


def test_the_real_dev_wins_even_with_a_nested_refs_heads_dev_branch_also_present(tmp_path: Path) -> None:
    """The REAL `dev` branch exists this time, alongside the same nested
    `refs/heads/refs/heads/dev` attacker branch as above. The real branch
    must win: it verifies the legit commit and genuinely fails (not
    `git_unavailable`) on the attacker's unrelated commit.
    """
    repo = tmp_path / "repo"
    _init_repo(repo, branch="pr-branch")
    legit_sha = _commit_at(repo, "a.txt", "a\n", f"wire up {BOUND_TASK_ID}", "2020-01-01T00:00:00+00:00")
    _git(repo, "branch", "dev", "pr-branch")
    _git(repo, "checkout", "--orphan", "attacker")
    garbage_sha = _commit_at(repo, "z.txt", "z\n", "attacker history", "2020-02-01T00:00:00+00:00")
    _git(repo, "branch", "refs/heads/dev", "attacker")
    _git(repo, "checkout", "pr-branch")

    target = claim_evidence._resolve_verify_target_branch(repo)
    assert target == "refs/heads/dev"

    legit_ev = claim_evidence.parse_evidence(f"commit:{legit_sha}")
    legit_verdict = claim_evidence.verify_evidence(legit_ev, repo, task_id=BOUND_TASK_ID)
    assert legit_verdict.status == "verified"

    garbage_ev = claim_evidence.parse_evidence(f"commit:{garbage_sha}")
    garbage_verdict = claim_evidence.verify_evidence(garbage_ev, repo, task_id=BOUND_TASK_ID)
    assert garbage_verdict.status == "failed"
    assert garbage_verdict.reason_code == ""  # a real "not an ancestor" finding, not infrastructure absence


# ---------------------------------------------------------------------------
# 2. Run-kind task_id column binding
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "runs.sqlite3"
    run_store.init_db(db_path)
    monkeypatch.setattr(run_store, "MAX_RUNS", 500)
    monkeypatch.setattr(run_store, "MAX_DB_BYTES", 200 * 1024 * 1024)
    monkeypatch.setattr(run_store, "_PINNED_SKIP_COUNT", 0)
    return db_path


def test_run_created_with_task_id_is_readable_in_metadata_and_binds_verified(store: Path) -> None:
    run_id = run_store.create_run({"session_id": "unrelated-session", "task_id": BOUND_TASK_ID})
    run_store.append_event(run_id, "model_request", {"text": "hi"}, t_ms=0, seq=0)
    run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)

    assert run_store.get_run(run_id)["run"]["task_id"] == BOUND_TASK_ID

    ev = claim_evidence.parse_evidence(f"run:{run_id}:0-0")
    verdict = claim_evidence.verify_evidence(ev, Path("."), db_path=store, task_id=BOUND_TASK_ID)

    assert verdict.status == "verified"
    assert BOUND_TASK_ID in verdict.reason


def test_run_task_id_column_does_not_bind_through_a_longer_id_that_contains_it(store: Path) -> None:
    """The run-kind counterpart of claim_evidence's commit-kind T-1/T-12
    regression test: a run stamped with task_id `T-12` must NOT bind (or
    verify) for task `T-1`, even though `T-1` is a naive substring of `T-12`.
    """
    run_id = run_store.create_run({"session_id": "unrelated-session", "task_id": "T-12"})
    run_store.append_event(run_id, "model_request", {"text": "hi"}, t_ms=0, seq=0)
    run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)

    ev = claim_evidence.parse_evidence(f"run:{run_id}:0-0")
    verdict = claim_evidence.verify_evidence(ev, Path("."), db_path=store, task_id="T-1")

    assert verdict.status == "attested"
    assert verdict.reason == claim_evidence.UNBOUND_RUN_REASON


def test_run_created_without_task_id_falls_back_to_not_before_only(store: Path) -> None:
    """No task_id stamped (create_run's default -- the honest-absence path
    every caller of start_chat_v2_run takes today): the run's task_id column
    is None, so binding can only succeed via not_before, never by name.
    """
    run_id = run_store.create_run({"session_id": "unrelated-session"})
    run_store.append_event(run_id, "model_request", {"text": "hi"}, t_ms=0, seq=0)
    run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)

    assert run_store.get_run(run_id)["run"]["task_id"] is None

    ev = claim_evidence.parse_evidence(f"run:{run_id}:0-0")

    unbound = claim_evidence.verify_evidence(ev, Path("."), db_path=store, task_id=BOUND_TASK_ID)
    assert unbound.status == "attested"
    assert unbound.reason == claim_evidence.UNBOUND_RUN_REASON

    started_at = datetime.fromisoformat(run_store.get_run(run_id)["run"]["started_at"])
    not_before = started_at - timedelta(seconds=5)
    verified = claim_evidence.verify_evidence(
        ev, Path("."), db_path=store, task_id=BOUND_TASK_ID, not_before=not_before
    )
    assert verified.status == "verified"
