"""A done claim carries proof, or it is not done: coverage for the phase-1.4
task-1 evidence library (scripts/crew/workboard/claim_evidence.py).

Five contracts, five sections below:

1. Grammar round-trips through parse_evidence/format_evidence_field;
   malformed strings raise ValueError naming the defect.
2. Commit evidence against a real fixture git repo, now with BINDING
   (fix round 1, post-review): landing on dev is necessary but never
   sufficient. An ancestor sha with no task_id/not_before binding attests,
   not verifies -- this is the regression coverage for the reviewer's
   finding that the repo's first commit used to verify for ANY task_id.
   Bound-by-message and bound-by-not_before each get their own test, plus a
   stale-sha-with-a-later-not_before case. Non-ancestor and unknown sha stay
   "failed" regardless of binding, since they never landed.
3. Run evidence against a temp run_store database (never the live one --
   every test here builds its own tmp_path sqlite file via
   run_store.init_db()), with the same binding requirement: landed
   (finalized ok, claimed range present) but unbound attests; bound by
   task_id-in-metadata or by not_before verifies.
4. Gate evidence is always "attested", never "verified" -- phase 1.4 does
   not independently re-run gates to confirm their recorded result, and
   binding params are accepted but ignored for this kind.
5. record_evidence/read_evidence round-trip through the chosen storage (the
   task's Active Task line in a fixture workboard -- never the real
   plans/thomas/WORKBOARD.md). The last test in that section also runs the
   real pinned workboard_claims.evaluate_board() over a line carrying an
   evidence= field, proving in code -- not just in the module docstring --
   that the validator tolerates it.

Phase-1.4 task-2 (evidence at the transition) adds one more section:

6. scripts/crew/tasks/reactivate.py's set_task_status: the `done` transition
   now demands evidence. No evidence refuses (task left byte-for-byte
   unchanged); malformed evidence refuses naming the defect; failed
   verification refuses with the verdict reason; verified and attested
   evidence both proceed and get recorded (attested also prints
   ATTESTED-NOT-VERIFIED). One test proves the run-kind db_path save/restore
   promised in claim_evidence's module docstring: verify_evidence's run-kind
   check re-points run_store's module-global _DB_PATH as a side effect, and
   set_task_status must put it back afterward rather than leaking a fixture
   db path into whatever the process had before.

Task-2's other half -- scripts/crew/workboard/worker.py's auto-done, end to
end through worker.run() (a landed commit passes `commit:<sha>` evidence and
reaches `done`; no landed commit stays in `review` and prints a loud REVIEW
HOLD line, the honest regression from auto-done-on-exit-0) -- is covered in
tests/test_workboard_worker_script.py instead, which is the existing home
for worker.run() end-to-end coverage and already carries the fake-subprocess
machinery those tests need.
"""

from __future__ import annotations

import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from scripts.crew.tasks import reactivate
from scripts.crew.workboard import claim_evidence
from scripts.forge.gates import workboard_claims

from thomas.marketplace.observability import run_store

# ---------------------------------------------------------------------------
# 1. Grammar
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw",
    [
        "commit:abc1234",
        "commit:0123456789abcdef0123456789abcdef01234567",
        "run:abcd1234ef567890abcd1234ef567890:3-9",
        "run:some-run-id:0-0",
        "gate:workboard_claims:0",
        "gate:workboard_claims:1",
    ],
)
def test_evidence_round_trips_through_parse_and_format(raw: str) -> None:
    ev = claim_evidence.parse_evidence(raw)
    assert claim_evidence.format_evidence_field(ev) == raw


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        ("", "empty"),
        ("nocolon", "separator"),
        ("unknownkind:abc1234", "not one of"),
        ("commit:xyz", "hex"),
        ("commit:ab", "hex"),
        ("commit:" + "a" * 41, "hex"),
        ("run:missingcolon", "seq range"),
        ("run:runid:missingdash", "-"),
        ("run:runid:5-2", "greater than"),
        ("run:runid:x-2", "integers"),
        ("gate:missingcolon", "exit_code"),
        ("gate:name:notanint", "integer"),
        ("gate::0", "gate_name"),
    ],
)
def test_malformed_evidence_raises_valueerror_naming_the_defect(raw: str, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        claim_evidence.parse_evidence(raw)


def test_commit_evidence_exposes_its_sha_property() -> None:
    ev = claim_evidence.parse_evidence("commit:abc1234")
    assert ev.sha == "abc1234"
    with pytest.raises(ValueError):
        _ = ev.run_id


def test_run_evidence_exposes_run_id_and_seq_range() -> None:
    ev = claim_evidence.parse_evidence("run:myrun:2-5")
    assert ev.run_id == "myrun"
    assert ev.seq_range == (2, 5)


def test_gate_evidence_exposes_gate_name_and_exit_code() -> None:
    ev = claim_evidence.parse_evidence("gate:workboard_claims:1")
    assert ev.gate_name == "workboard_claims"
    assert ev.exit_code == 1


# ---------------------------------------------------------------------------
# 1b. Delimiter-aware task_id binding (fix round 2, post-review)
#
# Fix round 1 bound task_id with a naive `in` substring check, which a
# re-reviewer showed binds a task through an unrelated one whose id merely
# contains it as a fragment (T-1 through T-12; a numeric id like 122 through
# a dash-joined list like 116-117-122-130; a short GitHub-issue id through
# this repo's real multi-issue directory names). `_task_id_bound_in_text`
# now requires a whole-token match: bounded by string start/end or a
# character outside [A-Za-z0-9_-] on both sides -- and '-' is deliberately
# NOT a boundary, since it is part of this repo's id grammar.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("task_id", "text", "expected"),
    [
        # The reviewer's exact attack shape: a short id is a naive substring
        # of a longer, unrelated one.
        ("T-1", "fixed in T-12 today", False),
        ("T-1", "fixed in T-1 today", True),
        # This repo's real naming: a single-issue id is not the same task as
        # a multi-issue id that happens to contain the same digits, joined
        # by '-' -- which must NOT be treated as a token boundary.
        ("THOMAS-GITHUB-ISSUE-122", "see THOMAS-GITHUB-ISSUES-116-117-122-130 for context", False),
        ("122", "closed 116-117-122-130 in one sweep", False),  # '-' is an id char, not a boundary
        ("122", "see issue 122.", True),  # '.' is a real boundary
        ("demo-task-123", "demo-task-123", True),  # exact match: string start and end are boundaries
        ("demo-task-123", "demo-task-123 landed", True),  # id at the start of the text
        ("demo-task-123", "landed demo-task-123", True),  # id at the end of the text
        ("demo-task-123", "wire up demo-task-123: done", True),  # colon boundary
        ("demo-task-123", "wire up demo-task-123 today", True),  # space boundary
        ("demo-task-123", "wire up demo-task-1234 today", False),  # longer id must not falsely bind
        ("demo-task-123", "wire up xdemo-task-123 today", False),  # id char immediately before
    ],
)
def test_task_id_bound_in_text_is_delimiter_aware(task_id: str, text: str, expected: bool) -> None:
    assert claim_evidence._task_id_bound_in_text(task_id, text) is expected


# ---------------------------------------------------------------------------
# 2. Commit verification against a fixture repo
# ---------------------------------------------------------------------------


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _commit_at(repo: Path, rel_path: str, content: str, message: str, committer_date: str) -> str:
    """Commit with a deterministic author/committer timestamp, so not_before
    binding tests don't depend on wall-clock timing.
    """
    path = repo / rel_path
    path.write_text(content, encoding="utf-8")
    _git(repo, "add", rel_path)
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = committer_date
    env["GIT_COMMITTER_DATE"] = committer_date
    subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


BOUND_TASK_ID = "demo-task-123"
UNRELATED_TASK_ID = "some-other-task"


@pytest.fixture
def fixture_repo(tmp_path: Path) -> dict[str, object]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "dev")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")

    # The repo's FIRST commit -- the reviewer's attack used exactly this
    # position (a commit with no relation whatsoever to any task) to prove
    # that ancestry alone let a commit "verify" for any task_id.
    ancestor_sha = _commit_at(repo, "a.txt", "a\n", "add a.txt", "2020-01-01T00:00:00+00:00")
    bound_msg_sha = _commit_at(
        repo, "d.txt", "d\n", f"wire up support for {BOUND_TASK_ID}", "2020-01-02T00:00:00+00:00"
    )
    # Round-2 fixture: a message naming task T-12. Used to prove a naive
    # substring check would have wrongly bound task T-1 through this commit.
    prefix_collision_sha = _commit_at(repo, "e.txt", "e\n", "closes T-12", "2020-01-03T00:00:00+00:00")
    _commit_at(repo, "b.txt", "b\n", "add b.txt", "2020-01-04T00:00:00+00:00")  # dev's HEAD

    _git(repo, "checkout", "-b", "feature", ancestor_sha)
    non_ancestor_sha = _commit_at(repo, "c.txt", "c\n", "add c.txt", "2020-01-05T00:00:00+00:00")  # never merged
    _git(repo, "checkout", "dev")

    return {
        "root": repo,
        "ancestor": ancestor_sha,
        "bound_msg": bound_msg_sha,
        "prefix_collision": prefix_collision_sha,
        "non_ancestor": non_ancestor_sha,
    }


def test_commit_evidence_ancestor_and_bound_by_message_verifies(fixture_repo: dict[str, object]) -> None:
    ev = claim_evidence.parse_evidence(f"commit:{fixture_repo['bound_msg']}")

    verdict = claim_evidence.verify_evidence(ev, fixture_repo["root"], task_id=BOUND_TASK_ID)  # type: ignore[arg-type]

    assert verdict.status == "verified"
    assert BOUND_TASK_ID in verdict.reason


def test_commit_evidence_bound_by_not_before_verifies(fixture_repo: dict[str, object]) -> None:
    # The commit's own message has no task_id, so this exercises the
    # not_before binding path alone.
    ev = claim_evidence.parse_evidence(f"commit:{fixture_repo['ancestor']}")
    not_before = datetime.fromisoformat("2019-12-31T00:00:00+00:00")  # before the commit's own timestamp

    verdict = claim_evidence.verify_evidence(
        ev,
        fixture_repo["root"],
        task_id=UNRELATED_TASK_ID,
        not_before=not_before,  # type: ignore[arg-type]
    )

    assert verdict.status == "verified"


def test_not_before_as_a_naive_datetime_is_treated_as_utc_not_rejected(fixture_repo: dict[str, object]) -> None:
    """Pin `_ensure_aware`'s documented behavior: a naive `not_before`
    (no tzinfo) never raises when compared against a commit's committer
    timestamp (always tz-aware, from `git log --format=%cI`) -- it is
    coerced to UTC instead.
    """
    ev = claim_evidence.parse_evidence(f"commit:{fixture_repo['ancestor']}")
    naive_not_before = datetime(2019, 12, 31, 0, 0, 0)  # no tzinfo, before the commit's own UTC timestamp
    assert naive_not_before.tzinfo is None

    verdict = claim_evidence.verify_evidence(
        ev,
        fixture_repo["root"],
        task_id=UNRELATED_TASK_ID,
        not_before=naive_not_before,  # type: ignore[arg-type]
    )

    assert verdict.status == "verified"


def test_commit_evidence_does_not_bind_when_task_id_is_a_prefix_of_a_longer_id_in_the_message(
    fixture_repo: dict[str, object],
) -> None:
    """The reviewer's finding as an end-to-end regression test: a commit
    whose message names task T-12 must NOT bind (or verify) for task T-1,
    even though `T-1` is a naive substring of `T-12`.
    """
    ev = claim_evidence.parse_evidence(f"commit:{fixture_repo['prefix_collision']}")

    verdict = claim_evidence.verify_evidence(ev, fixture_repo["root"], task_id="T-1")  # type: ignore[arg-type]

    assert verdict.status == "attested"
    assert verdict.reason == claim_evidence.UNBOUND_COMMIT_REASON


def test_commit_evidence_binds_the_exact_task_id_named_in_the_message(fixture_repo: dict[str, object]) -> None:
    ev = claim_evidence.parse_evidence(f"commit:{fixture_repo['prefix_collision']}")

    verdict = claim_evidence.verify_evidence(ev, fixture_repo["root"], task_id="T-12")  # type: ignore[arg-type]

    assert verdict.status == "verified"
    assert "T-12" in verdict.reason


def test_the_first_commit_regression_attests_not_verifies_for_an_unrelated_task(
    fixture_repo: dict[str, object],
) -> None:
    """Regression test for the reviewer's finding: before this fix, an
    ancestor sha verified as evidence for ANY task_id because commit
    evidence had zero binding to task or time. This is that exact shape --
    the repo's first commit, handed an unrelated task_id, with no
    not_before -- and it must attest, never verify.
    """
    ev = claim_evidence.parse_evidence(f"commit:{fixture_repo['ancestor']}")

    verdict = claim_evidence.verify_evidence(ev, fixture_repo["root"], task_id=UNRELATED_TASK_ID)  # type: ignore[arg-type]

    assert verdict.status == "attested"
    assert verdict.reason == claim_evidence.UNBOUND_COMMIT_REASON


def test_commit_evidence_with_no_binding_params_at_all_attests_not_verifies(
    fixture_repo: dict[str, object],
) -> None:
    ev = claim_evidence.parse_evidence(f"commit:{fixture_repo['ancestor']}")

    verdict = claim_evidence.verify_evidence(ev, fixture_repo["root"])  # type: ignore[arg-type]

    assert verdict.status == "attested"
    assert verdict.reason == claim_evidence.UNBOUND_COMMIT_REASON


def test_commit_evidence_stale_relative_to_not_before_stays_attested(fixture_repo: dict[str, object]) -> None:
    # The commit landed (it's an ancestor) but before the not_before cutoff,
    # so this is the "stale sha" case: landed, unbound, not proof.
    ev = claim_evidence.parse_evidence(f"commit:{fixture_repo['ancestor']}")
    not_before = datetime.fromisoformat("2020-06-01T00:00:00+00:00")  # after the commit's own timestamp

    verdict = claim_evidence.verify_evidence(
        ev,
        fixture_repo["root"],
        task_id=UNRELATED_TASK_ID,
        not_before=not_before,  # type: ignore[arg-type]
    )

    assert verdict.status == "attested"
    assert verdict.reason == claim_evidence.UNBOUND_COMMIT_REASON


def test_commit_evidence_for_a_sha_not_on_dev_fails_even_with_a_matching_task_id(
    fixture_repo: dict[str, object],
) -> None:
    ev = claim_evidence.parse_evidence(f"commit:{fixture_repo['non_ancestor']}")

    verdict = claim_evidence.verify_evidence(ev, fixture_repo["root"], task_id=UNRELATED_TASK_ID)  # type: ignore[arg-type]

    assert verdict.status == "failed"
    assert verdict.reason


def test_commit_evidence_for_an_unknown_sha_fails_without_crashing(fixture_repo: dict[str, object]) -> None:
    ev = claim_evidence.parse_evidence("commit:1234567890abcdef1234567890abcdef12345678")

    verdict = claim_evidence.verify_evidence(ev, fixture_repo["root"])  # type: ignore[arg-type]

    assert verdict.status == "failed"
    assert verdict.reason


# ---------------------------------------------------------------------------
# 3. Run verification against a temp run_store
# ---------------------------------------------------------------------------


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "runs.sqlite3"
    run_store.init_db(db_path)
    # Restore module-level retention/counters so this test's state never
    # bleeds into another test that shares the process.
    monkeypatch.setattr(run_store, "MAX_RUNS", 500)
    monkeypatch.setattr(run_store, "MAX_DB_BYTES", 200 * 1024 * 1024)
    monkeypatch.setattr(run_store, "_PINNED_SKIP_COUNT", 0)
    return db_path


def test_run_evidence_for_a_finalized_ok_run_bound_by_task_id_verifies(store: Path) -> None:
    run_id = run_store.create_run({"session_id": BOUND_TASK_ID})
    run_store.append_event(run_id, "model_request", {"text": "hi"}, t_ms=0, seq=0)
    run_store.append_event(run_id, "model_response", {"text": "hello"}, t_ms=5, seq=1)
    run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)

    ev = claim_evidence.parse_evidence(f"run:{run_id}:0-1")
    verdict = claim_evidence.verify_evidence(ev, Path("."), db_path=store, task_id=BOUND_TASK_ID)

    assert verdict.status == "verified"
    assert BOUND_TASK_ID in verdict.reason


def test_run_evidence_landed_but_unbound_attests_not_verifies(store: Path) -> None:
    """Run-kind counterpart of the reviewer's first-commit attack: a
    finalized-ok run with its full range present has no relation to
    `some-other-task` (no task_id anywhere in its metadata, no not_before)
    -- it must attest, never verify.
    """
    run_id = run_store.create_run({"session_id": "unrelated-session"})
    run_store.append_event(run_id, "model_request", {"text": "hi"}, t_ms=0, seq=0)
    run_store.append_event(run_id, "model_response", {"text": "hello"}, t_ms=5, seq=1)
    run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)

    ev = claim_evidence.parse_evidence(f"run:{run_id}:0-1")
    verdict = claim_evidence.verify_evidence(ev, Path("."), db_path=store, task_id=UNRELATED_TASK_ID)

    assert verdict.status == "attested"
    assert verdict.reason == claim_evidence.UNBOUND_RUN_REASON


def test_run_evidence_with_no_binding_params_at_all_attests_not_verifies(store: Path) -> None:
    run_id = run_store.create_run({"session_id": "s1"})
    run_store.append_event(run_id, "model_request", {"text": "hi"}, t_ms=0, seq=0)
    run_store.append_event(run_id, "model_response", {"text": "hello"}, t_ms=5, seq=1)
    run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)

    ev = claim_evidence.parse_evidence(f"run:{run_id}:0-1")
    verdict = claim_evidence.verify_evidence(ev, Path("."), db_path=store)

    assert verdict.status == "attested"
    assert verdict.reason == claim_evidence.UNBOUND_RUN_REASON


def test_run_evidence_bound_by_not_before_verifies(store: Path) -> None:
    run_id = run_store.create_run({"session_id": "unrelated-session"})
    run_store.append_event(run_id, "model_request", {"text": "hi"}, t_ms=0, seq=0)
    run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)
    started_at = datetime.fromisoformat(run_store.get_run(run_id)["run"]["started_at"])
    not_before = started_at - timedelta(seconds=5)

    ev = claim_evidence.parse_evidence(f"run:{run_id}:0-0")
    verdict = claim_evidence.verify_evidence(
        ev, Path("."), db_path=store, task_id=UNRELATED_TASK_ID, not_before=not_before
    )

    assert verdict.status == "verified"


def test_run_evidence_started_before_not_before_stays_attested(store: Path) -> None:
    run_id = run_store.create_run({"session_id": "unrelated-session"})
    run_store.append_event(run_id, "model_request", {"text": "hi"}, t_ms=0, seq=0)
    run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)
    started_at = datetime.fromisoformat(run_store.get_run(run_id)["run"]["started_at"])
    not_before = started_at + timedelta(hours=1)

    ev = claim_evidence.parse_evidence(f"run:{run_id}:0-0")
    verdict = claim_evidence.verify_evidence(
        ev, Path("."), db_path=store, task_id=UNRELATED_TASK_ID, not_before=not_before
    )

    assert verdict.status == "attested"
    assert verdict.reason == claim_evidence.UNBOUND_RUN_REASON


def test_run_evidence_for_an_unfinalized_run_fails(store: Path) -> None:
    run_id = run_store.create_run({"session_id": "s1"})
    run_store.append_event(run_id, "model_request", {"text": "hi"}, t_ms=0, seq=0)

    ev = claim_evidence.parse_evidence(f"run:{run_id}:0-0")
    verdict = claim_evidence.verify_evidence(ev, Path("."), db_path=store)

    assert verdict.status == "failed"


def test_run_evidence_for_a_claimed_range_missing_from_the_replay_fails(store: Path) -> None:
    run_id = run_store.create_run({"session_id": "s1"})
    run_store.append_event(run_id, "model_request", {"text": "hi"}, t_ms=0, seq=0)
    run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)

    ev = claim_evidence.parse_evidence(f"run:{run_id}:0-5")  # seq 1-5 never happened
    verdict = claim_evidence.verify_evidence(ev, Path("."), db_path=store)

    assert verdict.status == "failed"


def test_run_evidence_for_an_unknown_run_id_fails(store: Path) -> None:
    ev = claim_evidence.parse_evidence("run:does-not-exist:0-0")

    verdict = claim_evidence.verify_evidence(ev, Path("."), db_path=store)

    assert verdict.status == "failed"


def test_run_evidence_without_a_db_path_fails_instead_of_touching_the_live_store(store: Path) -> None:
    # `store` is created only so init_db() has been called with a tmp path in
    # this process; verify_evidence must still refuse to use it implicitly.
    ev = claim_evidence.parse_evidence("run:whatever:0-0")

    verdict = claim_evidence.verify_evidence(ev, Path("."), db_path=None)

    assert verdict.status == "failed"
    assert "db_path" in verdict.reason


# ---------------------------------------------------------------------------
# 4. Gate evidence is attested, never verified
# ---------------------------------------------------------------------------


def test_gate_evidence_is_always_attested_never_verified() -> None:
    ev = claim_evidence.parse_evidence("gate:workboard_claims:0")

    verdict = claim_evidence.verify_evidence(ev, Path("."))

    assert verdict.status == "attested"
    assert "not independently verified" in verdict.reason


def test_gate_evidence_is_attested_even_for_a_nonzero_exit_code() -> None:
    ev = claim_evidence.parse_evidence("gate:workboard_claims:1")

    verdict = claim_evidence.verify_evidence(ev, Path("."))

    assert verdict.status == "attested"


# ---------------------------------------------------------------------------
# 5. record_evidence / read_evidence round-trip on the Active Task line
# ---------------------------------------------------------------------------

_FIXTURE_WORKBOARD_TEXT = """# Fixture Workboard

## Agent Claims
- agent=claude; scope=scripts/crew/workboard; task=phase-1.4-task-1

## Active Tasks
- task_id=demo-task; agent=claude; scope=scripts/crew/workboard; summary=demo task; status=review

## Up For Grabs
- none

## Issues / Blockers
- none
"""


@pytest.fixture
def fixture_workboard(tmp_path: Path) -> Path:
    path = tmp_path / "WORKBOARD.md"
    path.write_text(_FIXTURE_WORKBOARD_TEXT, encoding="utf-8")
    return path


def test_record_and_read_evidence_round_trips_on_the_active_task_line(fixture_workboard: Path) -> None:
    ev = claim_evidence.parse_evidence("commit:abc1234")

    claim_evidence.record_evidence(
        "demo-task",
        ev,
        workboard_path=fixture_workboard,
        recorded_at="2026-08-25T00:00:00+00:00",
    )
    record = claim_evidence.read_evidence("demo-task", workboard_path=fixture_workboard)

    assert record.evidence == ev
    assert record.recorded_at == "2026-08-25T00:00:00+00:00"


def test_read_evidence_for_a_task_with_no_evidence_yet_returns_none(fixture_workboard: Path) -> None:
    record = claim_evidence.read_evidence("demo-task", workboard_path=fixture_workboard)

    assert record.evidence is None
    assert record.recorded_at is None


def test_record_evidence_on_an_unknown_task_id_raises_valueerror(fixture_workboard: Path) -> None:
    ev = claim_evidence.parse_evidence("commit:abc1234")

    with pytest.raises(ValueError, match="demo-task-does-not-exist"):
        claim_evidence.record_evidence("demo-task-does-not-exist", ev, workboard_path=fixture_workboard)


def test_reading_a_malformed_stored_evidence_string_raises_valueerror(fixture_workboard: Path) -> None:
    text = fixture_workboard.read_text(encoding="utf-8")
    text = text.replace(
        "status=review",
        "status=review; evidence=not-a-real-kind:xyz",
    )
    fixture_workboard.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="not one of"):
        claim_evidence.read_evidence("demo-task", workboard_path=fixture_workboard)


def test_recording_evidence_keeps_the_active_task_line_valid_to_the_real_pinned_claims_gate(
    fixture_workboard: Path,
) -> None:
    """The module docstring quotes the pinned validator to argue this. This
    test runs the real validator over a recorded evidence= field instead of
    trusting the quote.
    """
    ev = claim_evidence.parse_evidence("commit:abc1234")
    claim_evidence.record_evidence("demo-task", ev, workboard_path=fixture_workboard)

    violations, _claims, active_tasks, _grabs, _issues = workboard_claims.evaluate_board(fixture_workboard)

    assert violations == []
    assert active_tasks[0].task_id == "demo-task"


# ---------------------------------------------------------------------------
# 6. set_task_status: the `done` transition demands evidence (phase-1.4 task-2)
# ---------------------------------------------------------------------------


def test_set_task_status_to_done_without_evidence_is_refused_and_task_is_left_unchanged(
    fixture_workboard: Path,
) -> None:
    before = fixture_workboard.read_text(encoding="utf-8")

    ok, payload = reactivate.set_task_status(
        fixture_workboard,
        task_id="demo-task",
        status="done",
        actor="claude",
    )

    assert ok is False
    assert "without evidence" in str(payload.get("error"))
    assert fixture_workboard.read_text(encoding="utf-8") == before


def test_set_task_status_to_done_with_malformed_evidence_is_refused_naming_the_defect(
    fixture_workboard: Path,
) -> None:
    before = fixture_workboard.read_text(encoding="utf-8")

    ok, payload = reactivate.set_task_status(
        fixture_workboard,
        task_id="demo-task",
        status="done",
        actor="claude",
        evidence="not-a-real-kind:xyz",
    )

    assert ok is False
    assert "is malformed" in str(payload.get("error"))
    assert "not one of" in str(payload.get("error"))
    assert fixture_workboard.read_text(encoding="utf-8") == before


def test_set_task_status_to_done_with_evidence_that_fails_verification_is_refused_with_reason(
    fixture_workboard: Path, fixture_repo: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    # set_task_status checks commit evidence against reactivate.py's own
    # ROOT (bound to the real Thomas repo at import time) -- point it at the
    # fixture repo so the sha under test is the fixture's, not a sha that
    # merely fails to resolve in the real one for an unrelated reason.
    monkeypatch.setattr(reactivate, "ROOT", fixture_repo["root"])
    before = fixture_workboard.read_text(encoding="utf-8")
    raw = f"commit:{fixture_repo['non_ancestor']}"

    ok, payload = reactivate.set_task_status(
        fixture_workboard,
        task_id="demo-task",
        status="done",
        actor="claude",
        evidence=raw,
    )

    assert ok is False
    assert payload.get("evidence_status") == "failed"
    assert "is not an ancestor" in str(payload.get("error"))
    assert fixture_workboard.read_text(encoding="utf-8") == before


def test_set_task_status_to_done_with_verified_commit_evidence_proceeds_and_is_recorded(
    fixture_workboard: Path, fixture_repo: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(reactivate, "ROOT", fixture_repo["root"])
    raw = f"commit:{fixture_repo['ancestor']}"
    not_before = datetime.fromisoformat("2019-12-31T00:00:00+00:00")  # before the ancestor commit's own timestamp

    ok, payload = reactivate.set_task_status(
        fixture_workboard,
        task_id="demo-task",
        status="done",
        actor="claude",
        evidence=raw,
        evidence_not_before=not_before,
    )

    assert ok, payload
    assert payload["evidence_status"] == "verified"
    text = fixture_workboard.read_text(encoding="utf-8")
    assert "task_id=demo-task" in text
    assert "status=done" in text
    record = claim_evidence.read_evidence("demo-task", workboard_path=fixture_workboard)
    assert record.evidence == claim_evidence.parse_evidence(raw)
    assert record.recorded_at is not None


def test_set_task_status_to_done_with_attested_gate_evidence_proceeds_and_prints_the_label(
    fixture_workboard: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    raw = "gate:workboard_claims:0"

    ok, payload = reactivate.set_task_status(
        fixture_workboard,
        task_id="demo-task",
        status="done",
        actor="claude",
        evidence=raw,
    )

    assert ok, payload
    assert payload["evidence_status"] == "attested"
    assert "ATTESTED-NOT-VERIFIED" in capsys.readouterr().out
    record = claim_evidence.read_evidence("demo-task", workboard_path=fixture_workboard)
    assert record.evidence == claim_evidence.parse_evidence(raw)


def test_set_task_status_to_done_with_run_evidence_restores_the_process_run_store_db_path(
    fixture_workboard: Path, store: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """claim_evidence's module docstring documents that verify_evidence's
    run-kind check re-points run_store's module-global _DB_PATH as a side
    effect of calling init_db(db_path). set_task_status is the call site
    that owns fixing this honestly (see its comment): save the process's
    current _DB_PATH before verifying, restore it after -- so a `done`
    transition carrying run evidence against a throwaway/fixture db never
    leaves a live process (or another test) pointed at the wrong database.
    """
    run_id = run_store.create_run({"session_id": "demo-task"})
    run_store.append_event(run_id, "model_request", {"text": "hi"}, t_ms=0, seq=0)
    run_store.finalize_run(run_id, ok=True, error=None, iterations=1, tool_calls=0, usage=None)

    sentinel_path = store.parent / "unrelated-live-server.sqlite3"
    monkeypatch.setattr(run_store, "_DB_PATH", sentinel_path)

    ok, payload = reactivate.set_task_status(
        fixture_workboard,
        task_id="demo-task",
        status="done",
        actor="claude",
        evidence=f"run:{run_id}:0-0",
        evidence_db_path=store,
    )

    assert ok, payload
    assert payload["evidence_status"] == "verified"  # bound via session_id == task_id
    assert sentinel_path == run_store._DB_PATH
