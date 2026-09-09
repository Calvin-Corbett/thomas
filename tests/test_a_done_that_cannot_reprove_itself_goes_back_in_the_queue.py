"""A done that cannot re-prove itself goes back in the queue: coverage for
the phase-1.4 task-3 evidence-sweep (CLI: `claim_cleanup.py --evidence-sweep`;
logic: `scripts/crew/workboard/claim_evidence_sweep.py`, extracted from
`claim_cleanup.py` in fix round 1 to stay under the 800-line cap -- see that
module's docstring for the one-way import).

This is a NEW file, not an extension of
`tests/test_a_done_claim_carries_proof_or_it_is_not_done.py` -- that file is
already 751 lines, and the plan's Global Constraints cap files at 800 lines.

Five contracts, five sections:

1. `verified` evidence never expires, no matter how old its recorded
   timestamp is.
2. `attested` evidence never expires in phase 1.4 (same rule, gate kind).
3. Missing/failed evidence past --ttl-hours expires: a done task with NO
   evidence and NO recorded timestamp at all is the legacy case (predates
   evidence recording) and expires immediately, not gated by --ttl-hours;
   evidence within --ttl-hours does not (yet) expire; a commit that verified
   at done-time but later vanished from `dev` (history rewrite) expires once
   re-verification fails and the recorded timestamp is past TTL.
4. Dry-run (`--evidence-sweep` without `--apply`) prints the would-expire
   list and mutates nothing.
5. The new evidence-sweep path never uses `git blame` -- the blame-based
   detector `_stale_claim_candidates` uses is banned for this feature
   (an uncommitted line reads age-0.00h).

A sixth section covers `--apply`'s side effects end to end: the expired
task is driven done->queued then moved to `## Up For Grabs` annotated with
the failed verdict, the claiming agent's claim is released ONLY when they
have zero remaining active tasks, and the claiming agent is messaged.

A seventh section (fix round 1, post-review) covers EXPIRY REQUIRES POSITIVE
FAILURE: run-kind evidence the sweep cannot re-check because no
`--run-store-db` was given is SKIPPED, never expired, even under `--apply`;
`--run-store-db` lets it actually re-verify (expiring a genuinely-missing
run, never expiring a valid one); and malformed stored evidence is likewise
SKIPPED with a loud human-review note instead of auto-expiring.
"""

from __future__ import annotations

import inspect
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import scripts.crew.workboard.claim_cleanup as mod
import scripts.forge.gates.workboard_claims as gate
from scripts.crew.workboard import claim_evidence
from scripts.crew.workboard import claim_evidence_sweep as sweep

from thomas.marketplace.observability import run_store

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_workboard(
    tmp_path: Path,
    *,
    claims_block: str,
    active_tasks_block: str,
    issues_block: str = "- none",
    up_for_grabs_block: str = "- none",
) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(
        (
            "# Fixture Workboard\n\n"
            "## Agent Claims\n"
            f"{claims_block}\n\n"
            "## Active Tasks\n"
            f"{active_tasks_block}\n\n"
            "## Up For Grabs\n"
            f"{up_for_grabs_block}\n\n"
            "## Issues / Blockers\n"
            f"{issues_block}\n"
        ),
        encoding="utf-8",
    )
    return path


def _done_workboard(tmp_path: Path, *, extra_active: str = "") -> Path:
    active = "- task_id=demo-task; agent=claude; scope=scripts/crew/workboard; summary=demo task; status=done"
    if extra_active:
        active = f"{active}\n{extra_active}"
    return _write_workboard(
        tmp_path,
        claims_block="- agent=claude; scope=scripts/crew/workboard; task=demo task",
        active_tasks_block=active,
    )


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


@pytest.fixture
def sweep_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "dev")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    return repo


# ---------------------------------------------------------------------------
# 1 + 2. verified / attested never expire
# ---------------------------------------------------------------------------


def test_done_task_with_verified_commit_evidence_never_expires(sweep_repo: Path, tmp_path: Path) -> None:
    bound_sha = _commit_at(sweep_repo, "a.txt", "a\n", "wire up demo-task work", "2020-01-01T00:00:00+00:00")
    workboard = _done_workboard(tmp_path)
    claim_evidence.record_evidence(
        "demo-task",
        claim_evidence.parse_evidence(f"commit:{bound_sha}"),
        workboard_path=workboard,
        recorded_at="2020-01-01T00:00:01+00:00",  # ancient relative to `now` below
    )

    violations, candidates, skipped = sweep.evidence_sweep_candidates(
        workboard_path=workboard,
        ttl_hours=0.0001,  # smallest possible TTL -- would expire anything gated by it
        now=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        repo_root=sweep_repo,
        db_path=None,
    )

    assert violations == []
    assert candidates == []
    assert skipped == []


def test_done_task_with_attested_gate_evidence_never_expires_in_phase_1_4(tmp_path: Path) -> None:
    workboard = _done_workboard(tmp_path)
    claim_evidence.record_evidence(
        "demo-task",
        claim_evidence.parse_evidence("gate:workboard_claims:0"),
        workboard_path=workboard,
        recorded_at="2020-01-01T00:00:00+00:00",
    )

    violations, candidates, skipped = sweep.evidence_sweep_candidates(
        workboard_path=workboard,
        ttl_hours=0.0001,
        now=datetime.now(timezone.utc),
        repo_root=Path("."),
        db_path=None,
    )

    assert violations == []
    assert candidates == []
    assert skipped == []


# ---------------------------------------------------------------------------
# 3. missing/failed evidence past TTL expires; the legacy case; the vanished
#    commit
# ---------------------------------------------------------------------------


def test_done_task_with_no_evidence_and_no_timestamp_expires_immediately_as_legacy(tmp_path: Path) -> None:
    workboard = _done_workboard(tmp_path)  # no record_evidence() call at all

    violations, candidates, skipped = sweep.evidence_sweep_candidates(
        workboard_path=workboard,
        ttl_hours=1_000_000.0,  # huge TTL -- proves this is NOT gated by TTL
        now=datetime.now(timezone.utc),
        repo_root=Path("."),
        db_path=None,
    )

    assert violations == []
    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["task_id"] == "demo-task"
    assert candidate["agent"] == "claude"
    assert candidate["verdict_status"] == "missing"
    assert candidate["reason"] == mod.LEGACY_DONE_WITHOUT_EVIDENCE_REASON
    assert candidate["age_hours"] is None


def test_failed_evidence_within_ttl_is_not_yet_a_candidate(sweep_repo: Path, tmp_path: Path) -> None:
    unknown_sha = "1234567890abcdef1234567890abcdef12345678"
    workboard = _done_workboard(tmp_path)
    now = datetime.fromisoformat("2026-01-01T12:00:00+00:00")
    recent = (now - timedelta(hours=1)).isoformat()
    claim_evidence.record_evidence(
        "demo-task",
        claim_evidence.parse_evidence(f"commit:{unknown_sha}"),
        workboard_path=workboard,
        recorded_at=recent,
    )

    violations, candidates, skipped = sweep.evidence_sweep_candidates(
        workboard_path=workboard,
        ttl_hours=72.0,
        now=now,
        repo_root=sweep_repo,
        db_path=None,
    )

    assert violations == []
    assert candidates == []


def test_evidence_that_no_longer_verifies_because_the_commit_vanished_from_dev_expires(
    sweep_repo: Path, tmp_path: Path
) -> None:
    """Regression coverage for the plan's contract 3: a commit that verified
    at done-time but is later dropped from `dev` (history rewrite) must
    expire once the recorded timestamp is past TTL. Simulated with an orphan
    branch that replaces `dev` -- the bound commit is provably gone from its
    ancestry.
    """
    bound_sha = _commit_at(sweep_repo, "a.txt", "a\n", "wire up demo-task work", "2020-01-01T00:00:00+00:00")
    _commit_at(sweep_repo, "b.txt", "b\n", "more work", "2020-01-02T00:00:00+00:00")

    workboard = _done_workboard(tmp_path)
    claim_evidence.record_evidence(
        "demo-task",
        claim_evidence.parse_evidence(f"commit:{bound_sha}"),
        workboard_path=workboard,
        recorded_at="2020-01-03T00:00:00+00:00",
    )

    _git(sweep_repo, "checkout", "--orphan", "rewritten")
    (sweep_repo / "c.txt").write_text("c\n", encoding="utf-8")
    _git(sweep_repo, "add", "c.txt")
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = "2020-01-04T00:00:00+00:00"
    env["GIT_COMMITTER_DATE"] = "2020-01-04T00:00:00+00:00"
    subprocess.run(
        ["git", "commit", "-m", "rewritten history drops the old dev tip"],
        cwd=sweep_repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    _git(sweep_repo, "branch", "-D", "dev")
    _git(sweep_repo, "branch", "-m", "rewritten", "dev")

    violations, candidates, skipped = sweep.evidence_sweep_candidates(
        workboard_path=workboard,
        ttl_hours=1.0,
        now=datetime.fromisoformat("2020-06-01T00:00:00+00:00"),
        repo_root=sweep_repo,
        db_path=None,
    )

    assert violations == []
    assert len(candidates) == 1
    assert candidates[0]["verdict_status"] == "failed"
    assert "not an ancestor" in candidates[0]["reason"]
    assert bound_sha in candidates[0]["reason"]


def test_malformed_stored_evidence_on_a_done_task_is_skipped_not_expired(tmp_path: Path) -> None:
    """Fix round 1, post-review: malformed evidence means no real check ever
    ran (read_evidence raised before parse_evidence could even try) -- it is
    NOT a positive finding that the evidence is bad, so it must be skipped
    for human review, never auto-expired, even far past any TTL.
    """
    workboard = _done_workboard(tmp_path)
    text = workboard.read_text(encoding="utf-8")
    text = text.replace(
        "status=done",
        "status=done; evidence=not-a-real-kind:xyz; evidence_recorded_at=2020-01-01T00:00:00+00:00",
    )
    workboard.write_text(text, encoding="utf-8")

    violations, candidates, skipped = sweep.evidence_sweep_candidates(
        workboard_path=workboard,
        ttl_hours=0.0001,  # tiny TTL -- proves this is not TTL-gated into expiring
        now=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        repo_root=Path("."),
        db_path=None,
    )

    assert violations == []
    assert candidates == []
    assert len(skipped) == 1
    assert skipped[0]["task_id"] == "demo-task"
    assert skipped[0]["agent"] == "claude"
    assert "stored evidence is malformed" in skipped[0]["note"]
    assert sweep.MALFORMED_EVIDENCE_NOTE_SUFFIX in skipped[0]["note"]


def test_malformed_stored_evidence_is_never_expired_by_apply_either(tmp_path: Path, capsys) -> None:
    workboard = _done_workboard(tmp_path)
    text = workboard.read_text(encoding="utf-8")
    text = text.replace(
        "status=done",
        "status=done; evidence=not-a-real-kind:xyz; evidence_recorded_at=2020-01-01T00:00:00+00:00",
    )
    workboard.write_text(text, encoding="utf-8")
    before = workboard.read_text(encoding="utf-8")

    rc = mod.run(["--workboard", str(workboard), "--evidence-sweep", "--apply", "--json"])
    payload = json.loads(capsys.readouterr().out)
    after = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["expired_task_ids"] == []
    assert payload["skipped_count"] == 1
    assert before == after  # task untouched: still done, still in Active Tasks


# ---------------------------------------------------------------------------
# 7. run-kind evidence: EXPIRY REQUIRES POSITIVE FAILURE (fix round 1)
# ---------------------------------------------------------------------------


@pytest.fixture
def run_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "runs.sqlite3"
    run_store.init_db(db_path)
    monkeypatch.setattr(run_store, "MAX_RUNS", 500)
    monkeypatch.setattr(run_store, "MAX_DB_BYTES", 200 * 1024 * 1024)
    monkeypatch.setattr(run_store, "_PINNED_SKIP_COUNT", 0)
    return db_path


def test_run_evidence_without_run_store_db_is_skipped_and_task_stays_untouched(
    tmp_path: Path, run_db: Path, capsys
) -> None:
    run_id = run_store.create_run({"session_id": "demo-task"})
    run_store.append_event(run_id, "model_request", {"text": "hi"}, t_ms=0, seq=0)
    run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)

    workboard = _done_workboard(tmp_path)
    claim_evidence.record_evidence(
        "demo-task",
        claim_evidence.parse_evidence(f"run:{run_id}:0-0"),
        workboard_path=workboard,
        recorded_at="2020-01-01T00:00:00+00:00",  # ancient -- would expire if this were a real failure
    )
    before = workboard.read_text(encoding="utf-8")

    violations, candidates, skipped = sweep.evidence_sweep_candidates(
        workboard_path=workboard,
        ttl_hours=0.0001,
        now=datetime.now(timezone.utc),
        repo_root=Path("."),
        db_path=None,  # no --run-store-db
    )

    assert violations == []
    assert candidates == []
    assert len(skipped) == 1
    assert skipped[0]["note"] == sweep.RUN_DB_UNAVAILABLE_NOTE

    # And --apply through the real CLI must not touch the task either.
    rc = mod.run(["--workboard", str(workboard), "--evidence-sweep", "--apply", "--json"])
    payload = json.loads(capsys.readouterr().out)
    after = workboard.read_text(encoding="utf-8")
    assert rc == 0
    assert payload["expired_task_ids"] == []
    assert before == after


def test_run_evidence_with_run_store_db_and_a_genuinely_missing_run_expires_past_ttl(
    tmp_path: Path, run_db: Path
) -> None:
    workboard = _done_workboard(tmp_path)
    claim_evidence.record_evidence(
        "demo-task",
        claim_evidence.parse_evidence("run:does-not-exist:0-0"),
        workboard_path=workboard,
        recorded_at="2020-01-01T00:00:00+00:00",
    )

    violations, candidates, skipped = sweep.evidence_sweep_candidates(
        workboard_path=workboard,
        ttl_hours=1.0,
        now=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        repo_root=Path("."),
        db_path=run_db,
    )

    assert violations == []
    assert skipped == []
    assert len(candidates) == 1
    assert candidates[0]["verdict_status"] == "failed"
    assert "was not found" in candidates[0]["reason"]


def test_run_evidence_with_run_store_db_and_a_valid_run_never_expires(tmp_path: Path, run_db: Path) -> None:
    run_id = run_store.create_run({"session_id": "demo-task"})
    run_store.append_event(run_id, "model_request", {"text": "hi"}, t_ms=0, seq=0)
    run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)

    workboard = _done_workboard(tmp_path)
    claim_evidence.record_evidence(
        "demo-task",
        claim_evidence.parse_evidence(f"run:{run_id}:0-0"),
        workboard_path=workboard,
        recorded_at="2020-01-01T00:00:00+00:00",
    )

    violations, candidates, skipped = sweep.evidence_sweep_candidates(
        workboard_path=workboard,
        ttl_hours=0.0001,
        now=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        repo_root=Path("."),
        db_path=run_db,
    )

    assert violations == []
    assert candidates == []
    assert skipped == []


def test_commit_evidence_is_skipped_when_git_itself_fails_to_run(
    sweep_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Re-review fix (round 2): the same rule applies on the commit-kind
    side. `_verify_commit`'s `OSError` branch (`git` failing to run at all --
    missing binary, permissions, etc.) is infrastructure absence, not a
    positive finding that the sha is bad -- it must skip, never expire, same
    as run-kind db-absence.
    """
    bound_sha = _commit_at(sweep_repo, "a.txt", "a\n", "wire up demo-task work", "2020-01-01T00:00:00+00:00")
    workboard = _done_workboard(tmp_path)
    claim_evidence.record_evidence(
        "demo-task",
        claim_evidence.parse_evidence(f"commit:{bound_sha}"),
        workboard_path=workboard,
        recorded_at="2020-01-01T00:00:01+00:00",  # ancient -- would expire if this were a real failure
    )
    before = workboard.read_text(encoding="utf-8")

    def _raise_oserror(*_args: object, **_kwargs: object) -> None:
        raise OSError("git executable not found")

    monkeypatch.setattr(claim_evidence.subprocess, "run", _raise_oserror)

    violations, candidates, skipped = sweep.evidence_sweep_candidates(
        workboard_path=workboard,
        ttl_hours=0.0001,
        now=datetime.fromisoformat("2026-01-01T00:00:00+00:00"),
        repo_root=sweep_repo,
        db_path=None,
    )

    assert violations == []
    assert candidates == []
    assert len(skipped) == 1
    assert skipped[0]["task_id"] == "demo-task"
    assert skipped[0]["note"] == sweep.GIT_UNAVAILABLE_NOTE

    # And --apply through the real CLI must not touch the task either.
    rc = mod.run(["--workboard", str(workboard), "--evidence-sweep", "--apply", "--json"])
    after = workboard.read_text(encoding="utf-8")
    assert rc == 0
    assert before == after


# ---------------------------------------------------------------------------
# 4. dry-run mutates nothing
# ---------------------------------------------------------------------------


def test_dry_run_evidence_sweep_prints_candidates_and_mutates_nothing(tmp_path: Path, capsys) -> None:
    workboard = _done_workboard(tmp_path)  # legacy candidate: no evidence at all
    before = workboard.read_text(encoding="utf-8")

    rc = mod.run(["--workboard", str(workboard), "--evidence-sweep", "--json"])
    payload = json.loads(capsys.readouterr().out)
    after = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["applied"] is False
    assert payload["expired_candidate_count"] == 1
    assert payload["expired_candidates"][0]["reason"] == mod.LEGACY_DONE_WITHOUT_EVIDENCE_REASON
    assert before == after


# ---------------------------------------------------------------------------
# 5. no `git blame` in the new path
# ---------------------------------------------------------------------------


def test_evidence_sweep_functions_never_use_git_blame() -> None:
    sources = "".join(
        inspect.getsource(fn)
        for fn in (
            sweep.evidence_sweep_candidates,
            sweep._consider_candidate,
            sweep._malformed_evidence_recorded_at,
            sweep.apply_evidence_sweep,
            mod._run_evidence_sweep,
        )
    )
    assert "blame" not in sources.lower()
    assert "_line_commit_unix(" not in sources  # a mention in a comment is fine; a call is not


# ---------------------------------------------------------------------------
# 6. --apply: done->queued->Up For Grabs, claim release, and the message
# ---------------------------------------------------------------------------


def test_apply_evidence_sweep_moves_expired_task_and_releases_claim_and_messages_agent(
    tmp_path: Path, capsys
) -> None:
    workboard = _done_workboard(tmp_path)  # legacy candidate

    rc = mod.run(
        [
            "--workboard",
            str(workboard),
            "--evidence-sweep",
            "--apply",
            "--reported-by",
            "cleanup-bot",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["ok"] is True
    assert payload["applied"] is True
    assert payload["expired_task_ids"] == ["demo-task"]
    assert payload["released_agents"] == ["claude"]
    assert payload["messaged_agents"] == ["claude"]
    assert "task_id=demo-task; agent=claude;" not in text  # left Active Tasks
    assert "task_id=demo-task" in text  # landed in Up For Grabs
    assert "[evidence expired: legacy done without evidence]" in text
    assert "agent=claude; scope=scripts/crew/workboard; task=demo task" not in text  # claim released
    assert "Agent Message Traffic" in text
    assert "claude" in text.split("Agent Message Traffic", 1)[1]
    assert gate.evaluate(workboard) == []


def test_apply_evidence_sweep_does_not_release_claim_when_agent_has_another_active_task(
    tmp_path: Path, capsys
) -> None:
    other = "- task_id=other-task; agent=claude; scope=scripts/crew/workboard; summary=other task; status=in_progress"
    workboard = _done_workboard(tmp_path, extra_active=other)

    rc = mod.run(["--workboard", str(workboard), "--evidence-sweep", "--apply", "--json"])
    payload = json.loads(capsys.readouterr().out)
    text = workboard.read_text(encoding="utf-8")

    assert rc == 0
    assert payload["expired_task_ids"] == ["demo-task"]
    assert payload["released_agents"] == []
    assert "agent=claude; scope=scripts/crew/workboard; task=demo task" in text  # claim retained
    assert "task_id=other-task; agent=claude;" in text  # untouched
    assert gate.evaluate(workboard) == []
