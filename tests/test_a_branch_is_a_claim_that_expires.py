"""A branch is a claim that expires -- an anonymous fork stops being free.

Plan: the internal design record Task 2.

Contracts pinned here:
  1. claim CRUD round-trips (record/get/is_expired, the None-on-missing house
     law, the 60-day cap, the past-date rejection, the trunk-name rejection).
  2. a push CREATING an unclaimed new branch FAILS, naming the branch and the
     remedy command -- proven through a REAL bare-remote push + a real
     pre-push hook, not a synthetic stdin line, so the fixture exercises the
     exact mechanism a live repo would use.
  3. a push CREATING a claimed branch PASSES, same real-push mechanism.
  4. an EXPIRED claim also fails a create-push (a claim must be live, not
     merely once-recorded).
  5. dev/main need no claim; updates to already-existing remote refs (and
     deletions, which present the same way) are never gated.
  6. the asymmetry: an ABSENT claims registry is a loud note-PASS for the
     GATE (infrastructure absence) but a loud REFUSAL to delete anything for
     the SWEEP (fail-closed for destruction) -- same condition, opposite
     defaults, both pinned here.
  7. the sweep: an expired claim gets archived (verified), graveyard-
     recorded, and deleted; an absent claim inside its 7-day grace window is
     left alone; an absent claim beyond grace is swept; an unknowable
     creation time is NEVER treated as beyond grace (fail-closed).
  8. dry-run by default -- nothing is touched without --apply.

Fix round 1 (task-2-review.md) additions:
  9. CRIT-1: a pre-existing archive ref at the same name is NEVER
     overwritten -- the collision is reported per-branch and that branch's
     local ref survives (not deleted), while the sweep continues.
  10. CRIT-2: branch-creation time is the reflog ENTRY's own timestamp, not
      the committer date of the commit it points at -- a branch cut TODAY
      from a base commit that is weeks old still gets its full grace window.

Only fixture repos and fixture remotes (``git init`` / ``git init --bare``)
are used -- never the real Thomas checkout or its real
docs/ops/branch_claims.json / docs/ops/graveyard.json.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
GATE = REPO_ROOT / "scripts" / "forge" / "gates" / "branch_claim_gate.py"

sys.path.insert(0, str(REPO_ROOT))
from scripts.forge import branch_claims, branch_sweep, graveyard  # noqa: E402

_ZERO_SHA = "0" * 40


# ---------------------------------------------------------------------------
# fixture helpers
# ---------------------------------------------------------------------------


def _git(cwd: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)
    return proc.stdout


def _git_env(cwd: Path, env: dict[str, str], *args: str) -> str:
    """Like ``_git``, but with extra environment variables -- used to
    backdate a commit's author/committer date (``GIT_AUTHOR_DATE`` /
    ``GIT_COMMITTER_DATE``) without affecting the reflog entry time a later
    ``checkout -b`` records, which is what CRIT-2's regression test needs."""
    import os

    full_env = {**os.environ, **env}
    proc = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True, env=full_env
    )
    return proc.stdout


def _init_repo(tmp_path: Path, name: str = "repo") -> Path:
    repo = tmp_path / name
    repo.mkdir()
    _git(tmp_path, "init", "-b", "dev", str(repo))
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "f.txt").write_text("seed\n", encoding="utf-8")
    _git(repo, "add", "f.txt")
    _git(repo, "commit", "-m", "seed")
    return repo


def _init_repo_with_bare_remote(tmp_path: Path) -> tuple[Path, Path]:
    """A working repo pushed to a fresh ``git init --bare`` remote, with the
    real branch_claim_gate.py wired as its pre-push hook. Returns
    (repo, remote)."""
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", str(remote))
    repo = _init_repo(tmp_path, "repo")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "push", "origin", "dev")

    hooks_dir = repo / ".git" / "hooks"
    hooks_dir.mkdir(parents=True, exist_ok=True)
    hook = hooks_dir / "pre-push"
    hook.write_text(
        "#!/bin/sh\n" f'exec "{sys.executable}" "{GATE}" --repo-root "{repo}"\n',
        encoding="utf-8",
    )
    hook.chmod(0o755)
    return repo, remote


def _push(repo: Path, branch: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), "push", "origin", branch],
        capture_output=True,
        text=True,
    )


def _write_claims_json(repo: Path, payload: dict) -> None:
    path = branch_claims.path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ===========================================================================
# 1. registry CRUD
# ===========================================================================


def test_a_missing_registry_is_empty_and_get_returns_none(tmp_path: Path) -> None:
    claims = branch_claims.load(tmp_path)
    assert claims.records == ()
    assert claims.get("whatever") is None
    assert claims.is_expired("whatever") is None  # never False on missing -- the house law


def test_record_then_get_round_trips(tmp_path: Path) -> None:
    branch_claims.record_claim(tmp_path, "feature-x", "test-user", "trying a new thing", "2026-09-10")
    claims = branch_claims.load(tmp_path)
    record = claims.get("feature-x")
    assert record is not None
    assert record["branch"] == "feature-x"
    assert record["owner"] == "test-user"
    assert record["purpose"] == "trying a new thing"
    assert record["expires_on"] == "2026-09-10"
    assert "created_on" in record


def test_is_expired_true_false_none_boundary(tmp_path: Path) -> None:
    branch_claims.record_claim(tmp_path, "feature-x", "test-user", "why", "2026-09-10")
    claims = branch_claims.load(tmp_path)
    assert claims.is_expired("feature-x", "2026-09-09") is False
    assert claims.is_expired("feature-x", "2026-09-10") is False  # expiry day itself still live
    assert claims.is_expired("feature-x", "2026-09-11") is True
    assert claims.is_expired("never-claimed", "2026-09-11") is None


def test_newest_record_wins_on_reclaim(tmp_path: Path) -> None:
    branch_claims.record_claim(tmp_path, "feature-x", "test-user", "first purpose", "2026-09-01")
    branch_claims.record_claim(tmp_path, "feature-x", "someone-else", "second purpose", "2026-09-20")
    claims = branch_claims.load(tmp_path)
    record = claims.get("feature-x")
    assert record["owner"] == "someone-else"
    assert record["purpose"] == "second purpose"
    assert claims.is_expired("feature-x", "2026-09-10") is False


def test_expires_on_must_not_already_be_past(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="already in the past"):
        branch_claims.record_claim(tmp_path, "feature-x", "test-user", "why", "2020-01-01")


def test_expires_on_capped_at_60_days_out(tmp_path: Path) -> None:
    import datetime as dt

    today = dt.date.today()
    too_far = (today + dt.timedelta(days=61)).isoformat()
    with pytest.raises(ValueError, match="60 days"):
        branch_claims.record_claim(tmp_path, "feature-x", "test-user", "why", too_far)

    ok_far = (today + dt.timedelta(days=60)).isoformat()
    branch_claims.record_claim(tmp_path, "feature-y", "test-user", "why", ok_far)  # must not raise


def test_trunk_branches_cannot_be_claimed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="trunk"):
        branch_claims.record_claim(tmp_path, "dev", "test-user", "why", "2026-09-10")
    with pytest.raises(ValueError, match="trunk"):
        branch_claims.record_claim(tmp_path, "main", "test-user", "why", "2026-09-10")


def test_malformed_registry_raises_systemexit_not_silent_empty(tmp_path: Path) -> None:
    path = branch_claims.path(tmp_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(SystemExit):
        branch_claims.load(tmp_path)


def test_cli_record_and_list_round_trip(tmp_path: Path) -> None:
    proc = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "forge" / "branch_claims.py"),
            "--repo-root",
            str(tmp_path),
            "record",
            "--branch",
            "cli-branch",
            "--owner",
            "test-user",
            "--purpose",
            "cli test",
            "--expires-on",
            "2026-09-10",
        ],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr

    proc_list = subprocess.run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "forge" / "branch_claims.py"),
            "--repo-root",
            str(tmp_path),
            "list",
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    assert proc_list.returncode == 0, proc_list.stdout + proc_list.stderr
    payload = json.loads(proc_list.stdout)
    assert payload["records"][0]["branch"] == "cli-branch"


# ===========================================================================
# 2/3/4/5. the gate, via a REAL bare remote + a REAL pre-push hook
# ===========================================================================


def test_push_creating_an_unclaimed_branch_fails_naming_it_and_the_remedy(tmp_path: Path) -> None:
    repo, _remote = _init_repo_with_bare_remote(tmp_path)
    _write_claims_json(repo, {"version": 1, "records": []})
    _git(repo, "checkout", "-b", "unclaimed-red-path")
    (repo / "f.txt").write_text("change\n", encoding="utf-8")
    _git(repo, "commit", "-am", "change")

    proc = _push(repo, "unclaimed-red-path")
    combined = proc.stdout + proc.stderr

    assert proc.returncode != 0, combined
    assert "unclaimed-red-path" in combined
    assert "branch_claims.py record" in combined


def test_push_creating_a_claimed_branch_passes(tmp_path: Path) -> None:
    repo, _remote = _init_repo_with_bare_remote(tmp_path)
    branch_claims.record_claim(repo, "claimed-branch", "test-user", "a real reason", "2026-10-01")
    _git(repo, "checkout", "-b", "claimed-branch")
    (repo / "f.txt").write_text("change\n", encoding="utf-8")
    _git(repo, "commit", "-am", "change")

    proc = _push(repo, "claimed-branch")
    combined = proc.stdout + proc.stderr

    assert proc.returncode == 0, combined


def test_push_creating_a_branch_with_an_expired_claim_fails(tmp_path: Path) -> None:
    repo, _remote = _init_repo_with_bare_remote(tmp_path)
    # An already-expired expires_on cannot be created through record_claim
    # (record-time validation rejects it) -- hand-write the registry the
    # same way test_every_enforcing_gate_can_fail.py's siblings document as
    # the only way to reach a garbage/expired record.
    _write_claims_json(
        repo,
        {
            "version": 1,
            "records": [
                {
                    "branch": "expired-branch",
                    "owner": "test-user",
                    "purpose": "old work",
                    "created_on": "2020-01-01",
                    "expires_on": "2020-02-01",
                    "refs": None,
                }
            ],
        },
    )
    _git(repo, "checkout", "-b", "expired-branch")
    (repo / "f.txt").write_text("change\n", encoding="utf-8")
    _git(repo, "commit", "-am", "change")

    proc = _push(repo, "expired-branch")
    combined = proc.stdout + proc.stderr

    assert proc.returncode != 0, combined
    assert "expired-branch" in combined


def test_dev_needs_no_claim(tmp_path: Path) -> None:
    repo, _remote = _init_repo_with_bare_remote(tmp_path)
    # dev was already pushed once in _init_repo_with_bare_remote; push again
    # with a new commit so this is a real create-push test via a second
    # branch instead -- dev itself already exists on the remote by now, so
    # exercise the exemption through the --ref argv form directly, which is
    # the same code path the real hook drives.
    proc = subprocess.run(
        [sys.executable, str(GATE), "--repo-root", str(repo), "--ref", "dev"],
        capture_output=True,
        text=True,
    )
    combined = proc.stdout + proc.stderr
    assert proc.returncode == 0, combined
    assert "PASS" in combined


def test_updating_an_existing_remote_branch_is_never_gated(tmp_path: Path) -> None:
    repo, _remote = _init_repo_with_bare_remote(tmp_path)
    branch_claims.record_claim(repo, "shared-branch", "test-user", "why", "2026-10-01")
    _git(repo, "checkout", "-b", "shared-branch")
    (repo / "f.txt").write_text("v1\n", encoding="utf-8")
    _git(repo, "commit", "-am", "v1")
    first = _push(repo, "shared-branch")
    assert first.returncode == 0, first.stdout + first.stderr

    # Now the claim has "expired" by hand-editing the registry to the past --
    # an UPDATE push to the same, already-existing remote branch must still
    # pass, because only ref CREATION is gated.
    _write_claims_json(
        repo,
        {
            "version": 1,
            "records": [
                {
                    "branch": "shared-branch",
                    "owner": "test-user",
                    "purpose": "why",
                    "created_on": "2020-01-01",
                    "expires_on": "2020-02-01",
                    "refs": None,
                }
            ],
        },
    )
    (repo / "f.txt").write_text("v2\n", encoding="utf-8")
    _git(repo, "commit", "-am", "v2")
    second = _push(repo, "shared-branch")
    assert second.returncode == 0, second.stdout + second.stderr


def test_absent_registry_is_a_loud_note_pass_for_the_gate(tmp_path: Path) -> None:
    """The asymmetry's gate half: no docs/ops/branch_claims.json on disk at
    all (never created) means infrastructure absence, not evidence this push
    is unclaimed -- the gate passes, loudly."""
    repo, _remote = _init_repo_with_bare_remote(tmp_path)
    assert not branch_claims.path(repo).exists()
    _git(repo, "checkout", "-b", "brand-new-nobody-claimed-it")
    (repo / "f.txt").write_text("change\n", encoding="utf-8")
    _git(repo, "commit", "-am", "change")

    proc = _push(repo, "brand-new-nobody-claimed-it")
    combined = proc.stdout + proc.stderr

    assert proc.returncode == 0, combined
    assert "NOTE" in combined
    assert "infrastructure absence" in combined


def test_malformed_registry_is_also_a_loud_note_pass_for_the_gate(tmp_path: Path) -> None:
    repo, _remote = _init_repo_with_bare_remote(tmp_path)
    path = branch_claims.path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json", encoding="utf-8")
    _git(repo, "checkout", "-b", "some-branch")
    (repo / "f.txt").write_text("change\n", encoding="utf-8")
    _git(repo, "commit", "-am", "change")

    proc = _push(repo, "some-branch")
    combined = proc.stdout + proc.stderr

    assert proc.returncode == 0, combined
    assert "NOTE" in combined


def test_present_but_empty_registry_still_enforces(tmp_path: Path) -> None:
    """The other half of the same asymmetry: a registry file that EXISTS,
    parses, and simply has zero records is NOT infrastructure absence -- it
    is a live, working, empty registry, so an unclaimed push still fails."""
    repo, _remote = _init_repo_with_bare_remote(tmp_path)
    _write_claims_json(repo, {"version": 1, "records": []})
    _git(repo, "checkout", "-b", "still-unclaimed")
    (repo / "f.txt").write_text("change\n", encoding="utf-8")
    _git(repo, "commit", "-am", "change")

    proc = _push(repo, "still-unclaimed")
    combined = proc.stdout + proc.stderr

    assert proc.returncode != 0, combined
    assert "still-unclaimed" in combined


# ===========================================================================
# 6/7/8. the sweep
# ===========================================================================


def test_sweep_refuses_to_delete_on_absent_claims_registry(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "some-branch")
    assert not branch_claims.path(repo).exists()

    report = branch_sweep.run_sweep(repo, apply=True)

    assert report.refused
    assert "does not exist" in report.refused_reason
    assert report.deleted == []
    assert report.archived == []


def test_sweep_refuses_to_delete_on_malformed_claims_registry(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    path = branch_claims.path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    report = branch_sweep.run_sweep(repo, apply=True)

    assert report.refused
    assert report.deleted == []


def test_sweep_refuses_to_delete_on_malformed_graveyard(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_claims_json(repo, {"version": 1, "records": []})
    gy_path = graveyard._graveyard_path(repo)  # noqa: SLF001 - test-only direct write, no public path() helper on graveyard
    gy_path.parent.mkdir(parents=True, exist_ok=True)
    gy_path.write_text("{not json", encoding="utf-8")

    report = branch_sweep.run_sweep(repo, apply=True)

    assert report.refused
    assert report.deleted == []


def test_sweep_dry_run_touches_nothing(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_claims_json(
        repo,
        {
            "version": 1,
            "records": [
                {
                    "branch": "expired-branch",
                    "owner": "test-user",
                    "purpose": "old",
                    "created_on": "2020-01-01",
                    "expires_on": "2020-02-01",
                    "refs": None,
                }
            ],
        },
    )
    _git(repo, "checkout", "-b", "expired-branch")

    report = branch_sweep.run_sweep(repo, apply=False)

    assert not report.refused
    assert any(d.branch == "expired-branch" and d.delete for d in report.decisions)
    assert report.deleted == []
    assert report.archived == []
    branches_after = _git(repo, "branch", "--list")
    assert "expired-branch" in branches_after


def test_sweep_archives_records_and_deletes_an_expired_claim(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_claims_json(
        repo,
        {
            "version": 1,
            "records": [
                {
                    "branch": "expired-branch",
                    "owner": "test-user",
                    "purpose": "old",
                    "created_on": "2020-01-01",
                    "expires_on": "2020-02-01",
                    "refs": None,
                }
            ],
        },
    )
    _git(repo, "checkout", "-b", "expired-branch")
    tip_sha = _git(repo, "rev-parse", "expired-branch").strip()
    _git(repo, "checkout", "dev")

    report = branch_sweep.run_sweep(repo, apply=True)

    assert not report.refused
    assert report.archived == ["expired-branch"]
    assert report.deleted == ["expired-branch"]
    assert report.graveyard_records_written == 1
    assert report.errors == []

    resolved = _git(repo, "rev-parse", "refs/archive/branch/expired-branch").strip()
    assert resolved == tip_sha

    branches_after = _git(repo, "branch", "--list")
    assert "expired-branch" not in branches_after

    gy = graveyard.load(repo)
    death = next(r for r in gy.records if r["kind"] == "branch" and r["name"] == "expired-branch")
    assert death["dead_sha"] == tip_sha
    assert death["by"] == "branch-sweep"


def test_sweep_leaves_an_unclaimed_branch_inside_its_grace_window(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_claims_json(repo, {"version": 1, "records": []})
    _git(repo, "checkout", "-b", "brand-new-branch")
    _git(repo, "checkout", "dev")

    report = branch_sweep.run_sweep(repo, apply=True)  # real "now" -- branch was just created

    assert not report.refused
    decision = next(d for d in report.decisions if d.branch == "brand-new-branch")
    assert decision.delete is False
    assert decision.reason == "unclaimed_within_grace"
    assert report.deleted == []


def test_sweep_removes_an_unclaimed_branch_beyond_its_grace_window(tmp_path: Path) -> None:
    import time

    repo = _init_repo(tmp_path)
    _write_claims_json(repo, {"version": 1, "records": []})
    _git(repo, "checkout", "-b", "old-unclaimed-branch")
    _git(repo, "checkout", "dev")

    eight_days_later = time.time() + (8 * 86400)
    report = branch_sweep.run_sweep(repo, apply=True, now=lambda: eight_days_later)

    assert not report.refused
    decision = next(d for d in report.decisions if d.branch == "old-unclaimed-branch")
    assert decision.delete is True
    assert decision.reason == "unclaimed_beyond_grace"
    assert report.deleted == ["old-unclaimed-branch"]


def test_sweep_never_touches_trunk(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path)
    _write_claims_json(repo, {"version": 1, "records": []})

    report = branch_sweep.run_sweep(repo, apply=True)

    decision = next(d for d in report.decisions if d.branch == "dev")
    assert decision.delete is False
    assert decision.reason == "trunk"


def test_unknown_creation_time_is_never_treated_as_beyond_grace(tmp_path: Path) -> None:
    """Hermetic: a fake GitRunner whose reflog is empty for the branch --
    exercises plan_sweep's fail-closed rule directly, without fighting real
    git's reflog timing (branch_custodian.py's precedent for fake-runner
    unit tests)."""
    import datetime as dt

    def fake_git(args):
        if args[:1] == ["for-each-ref"]:
            return "mystery-branch\tdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n"
        if args[:2] == ["log", "-g"]:
            return ""  # no reflog at all -- creation time unknowable
        raise AssertionError(f"unexpected git call: {args}")

    claims = branch_claims.Claims(records=())
    decisions = branch_sweep.plan_sweep(fake_git, claims, today=dt.date(2026, 9, 1))

    decision = next(d for d in decisions if d.branch == "mystery-branch")
    assert decision.delete is False
    assert decision.reason == "unclaimed_creation_time_unknown"


# ===========================================================================
# fix round 1: CRIT-1 (archive collision) and CRIT-2 (grace reads the wrong clock)
# ===========================================================================


def test_sweep_never_overwrites_a_pre_existing_archive_ref_on_collision(tmp_path: Path) -> None:
    """CRIT-1 regression (task-2-review.md): a name that was archived by an
    earlier sweep, then re-created locally with the same branch name and an
    expired claim, must NOT clobber the earlier archive when swept again.
    The earlier archive ref must survive byte-identical, the branch must
    survive un-deleted, and the collision must be named as an error."""
    repo = _init_repo(tmp_path)

    # An archive ref already exists at this name, as if an earlier sweep
    # archived a now-gone branch called "doomed".
    earlier_sha = _git(repo, "rev-parse", "dev").strip()
    _git(repo, "update-ref", "refs/archive/branch/doomed", earlier_sha)

    # "doomed" is re-created locally (a real, if unusual, sequence: the name
    # was reused after its first death) with a fresh commit and an expired
    # claim, so the sweep will try to archive+delete it again.
    _git(repo, "checkout", "-b", "doomed")
    (repo / "f.txt").write_text("second life\n", encoding="utf-8")
    _git(repo, "commit", "-am", "second life")
    new_sha = _git(repo, "rev-parse", "doomed").strip()
    _git(repo, "checkout", "dev")
    assert new_sha != earlier_sha

    _write_claims_json(
        repo,
        {
            "version": 1,
            "records": [
                {
                    "branch": "doomed",
                    "owner": "test-user",
                    "purpose": "second life",
                    "created_on": "2020-01-01",
                    "expires_on": "2020-02-01",
                    "refs": None,
                }
            ],
        },
    )

    report = branch_sweep.run_sweep(repo, apply=True)

    assert report.deleted == []  # never deleted un-archived
    assert report.archived == []  # the NEW archive write never happened
    assert len(report.errors) == 1
    assert "doomed" in report.errors[0]
    assert not report.ok

    # The earlier archive ref survives byte-identical -- not overwritten.
    resolved = _git(repo, "rev-parse", "refs/archive/branch/doomed").strip()
    assert resolved == earlier_sha

    # The branch itself was never deleted.
    branches_after = _git(repo, "branch", "--list")
    assert "doomed" in branches_after


def test_grace_window_uses_the_branch_reflog_entry_time_not_the_base_commits_date(tmp_path: Path) -> None:
    """CRIT-2 regression (task-2-review.md): a branch cut TODAY from a base
    commit that is weeks old must get its full 7-day grace window -- the
    creation time is when the BRANCH was made, not when its base commit was
    authored. Before the fix, `_branch_created_at` read `%ct` (the base
    commit's committer date), so this exact shape was swept immediately."""
    repo = _init_repo(tmp_path)
    # Backdate dev's own tip commit by 30 days -- this is the base the new
    # branch will be cut from.
    _git_env(
        repo,
        {"GIT_AUTHOR_DATE": "2026-06-01T00:00:00", "GIT_COMMITTER_DATE": "2026-06-01T00:00:00"},
        "commit",
        "--allow-empty",
        "-m",
        "old base",
    )
    # The branch itself is created NOW (real wall-clock reflog entry time).
    _git(repo, "checkout", "-b", "fresh-branch-old-base")
    _git(repo, "checkout", "dev")

    _write_claims_json(repo, {"version": 1, "records": []})

    report = branch_sweep.run_sweep(repo, apply=True)  # real "now"

    assert not report.refused
    decision = next(d for d in report.decisions if d.branch == "fresh-branch-old-base")
    assert decision.delete is False
    assert decision.reason == "unclaimed_within_grace"
    assert report.deleted == []

    branches_after = _git(repo, "branch", "--list")
    assert "fresh-branch-old-base" in branches_after


def test_grace_window_still_sweeps_a_genuinely_aged_branch(tmp_path: Path) -> None:
    """True-positive companion to the CRIT-2 regression above: a branch that
    is ACTUALLY old (its own reflog entry is beyond grace, simulated here by
    advancing `now` rather than the base commit's date) is still swept.
    Guards against a fix that broke the grace window in the other direction
    (nothing ever ages out)."""
    import time

    repo = _init_repo(tmp_path)
    _git(repo, "checkout", "-b", "genuinely-old-branch")
    _git(repo, "checkout", "dev")
    _write_claims_json(repo, {"version": 1, "records": []})

    eight_days_later = time.time() + (8 * 86400)
    report = branch_sweep.run_sweep(repo, apply=True, now=lambda: eight_days_later)

    assert not report.refused
    decision = next(d for d in report.decisions if d.branch == "genuinely-old-branch")
    assert decision.delete is True
    assert decision.reason == "unclaimed_beyond_grace"
    assert report.deleted == ["genuinely-old-branch"]


# ===========================================================================
# fix round 1: MIN-1 (invalid branch names) and MIN-2 (--ref double-prefix)
# ===========================================================================


def test_record_claim_rejects_a_git_invalid_branch_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="not a valid git branch name"):
        branch_claims.record_claim(tmp_path, "has space", "test-user", "why", "2026-09-10")


def test_ref_argv_fallback_strips_a_refs_heads_prefix_instead_of_doubling_it(tmp_path: Path) -> None:
    branch_claims.record_claim(tmp_path, "feat/x", "test-user", "why", "2026-09-10")

    proc = subprocess.run(
        [sys.executable, str(GATE), "--repo-root", str(tmp_path), "--ref", "refs/heads/feat/x"],
        capture_output=True,
        text=True,
    )
    combined = proc.stdout + proc.stderr

    assert proc.returncode == 0, combined
    assert "PASS" in combined
