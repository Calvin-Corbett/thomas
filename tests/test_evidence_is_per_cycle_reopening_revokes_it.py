"""Evidence is per-cycle: leaving `done` revokes it (phase-1.4, fix round --
coordinator/reviewer finding on top of task 4's gate).

The reviewer reproduced a real gap: `reactivate.set_task_status` only ever
WROTE to a task's `evidence=`/`evidence_recorded_at=` fields when entering
`done` (via `claim_evidence.record_evidence`); leaving `done`
(`done -> queued`, `done -> claimed`) rewrote `status=` only, via
`_replace_status_field`, and left the evidence fields sitting on the line
untouched. So a legal round trip -- `done -> queued -> claimed ->
in_progress -> review` -- carried the ORIGINAL cycle's evidence forward
unchanged, and a task hand-flipped straight back to `done` (bypassing
`reactivate.py` entirely, the same shape `scripts/crew/workboard/issue.py`'s
pinned `_set_task_status` could produce) would still find that stale
evidence on the line and pass `workboard_evidence_gate.py`, even though it
proves nothing about the NEW cycle's work.

Ruling: EVIDENCE IS PER-CYCLE -- leaving `done` revokes it. Fixed with
`claim_evidence.strip_evidence` (removes both fields, no-ops if neither is
present) called by `reactivate.set_task_status` on every transition whose
FROM-status is `done`. This file covers, in order:

1. The strip itself: fields gone after `done -> queued`, every OTHER field
   on the line untouched, and the resulting line still valid to the real
   pinned `workboard_claims.evaluate_board`.
2. `set_task_status` wiring: strips (and prints `EVIDENCE REVOKED`) when
   leaving `done`; does not strip when the transition doesn't leave `done`.
3. A legal re-done with FRESH evidence, after a full round trip, passes.
4. The reviewer's exact repro, end to end: verified done -> legal round
   trip all the way back to `review` (every hop through real
   `reactivate.set_task_status`, never hand-edited) -> a hand-flipped
   `status=review` -> `status=done` bypass with NO tooling involved at all
   -> `workboard_evidence_gate.py` now FAILS it (missing evidence), where
   before this fix it would have re-verified the stale-but-real prior-cycle
   commit and passed.
5. THE BLIND WINDOW (a second, deeper reviewer finding, CRITICAL): the strip
   above is necessary but not sufficient. A reopen-then-hand-reflip that
   happens entirely BETWEEN two board commits (the intermediate `queued`
   state never itself committed) reads as `done -> done` in the one board
   diff the gate actually sees -- both sides `"done"` -- which the gate's
   original status-only scoping rule treated as an unchanged standing done
   and skipped. Fixed in `workboard_evidence_gate.py`'s `_done_transitions`
   by adding evidence-equality to the scoping test: in scope whenever new
   status is `done` AND (old status != `done` OR old evidence != new
   evidence). Also closes the identical blind spot for evidence SWAPPED on
   a standing done with no reopen at all.

The phase-1.4 task-3 evidence sweep (`claim_evidence_sweep.py`) drives its
`done -> queued` expiry through this same `reactivate.set_task_status`, so
it inherits the strip automatically; that is verified by re-running its own
test file (`tests/test_a_done_that_cannot_reprove_itself_goes_back_in_the_queue.py`)
unmodified, not duplicated here.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.crew.tasks import reactivate
from scripts.crew.workboard import claim_evidence
from scripts.forge.gates import workboard_claims
from scripts.forge.gates import workboard_evidence_gate as gate

from tests.test_a_task_cannot_land_as_done_without_evidence import (
    _board_path,
    _commit_all,
    _commit_empty,
    _init_repo,
    _stage_board,
)

TASK_ID = "task-a"
AGENT = "agent1"


def _write_full_board(repo: Path, *, status: str) -> Path:
    """Unlike the gate test file's `_write_board` (Active Tasks only), this
    includes an `## Agent Claims` entry matching `AGENT` -- required for
    `reactivate.set_task_status`'s default `require_claims_to_have_active_task`."""
    board = _board_path(repo)
    board.parent.mkdir(parents=True, exist_ok=True)
    board.write_text(
        "# Fixture Workboard\n\n"
        "## Agent Claims\n"
        f"- agent={AGENT}; scope=foo; task=do the thing\n\n"
        "## Active Tasks\n"
        f"- task_id={TASK_ID}; agent={AGENT}; scope=foo; summary=do the thing; status={status}\n\n"
        "## Up For Grabs\n"
        "- none\n\n"
        "## Issues / Blockers\n"
        "- none\n",
        encoding="utf-8",
        newline="\n",
    )
    return board


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    r = _init_repo(tmp_path)
    # reactivate.set_task_status's commit-evidence verification is hardcoded
    # to its own module-level ROOT, not derived from workboard_path -- the
    # same monkeypatch the existing task-2 test file
    # (test_a_done_claim_carries_proof_or_it_is_not_done.py) uses.
    monkeypatch.setattr(reactivate, "ROOT", r)
    return r


def _bind_commit(repo: Path, message: str) -> str:
    """A commit whose message contains TASK_ID as a whole token, ancestor of
    dev -- `commit:<sha>` evidence for it verifies (not just attests)."""
    return _commit_empty(repo, message)


# ---------------------------------------------------------------------------
# 1. The strip itself
# ---------------------------------------------------------------------------


def test_strip_evidence_removes_only_the_evidence_fields_and_stays_valid(repo: Path) -> None:
    board = _write_full_board(repo, status="done")
    ev = claim_evidence.parse_evidence("commit:abc1234")
    claim_evidence.record_evidence(TASK_ID, ev, workboard_path=board, recorded_at="2026-08-25T00:00:00+00:00")
    assert claim_evidence.read_evidence(TASK_ID, workboard_path=board).evidence == ev

    stripped = claim_evidence.strip_evidence(TASK_ID, workboard_path=board)

    assert stripped is True
    record = claim_evidence.read_evidence(TASK_ID, workboard_path=board)
    assert record.evidence is None
    assert record.recorded_at is None
    text = board.read_text(encoding="utf-8")
    assert f"task_id={TASK_ID}" in text
    assert f"agent={AGENT}" in text
    assert "summary=do the thing" in text
    assert "status=done" in text  # strip_evidence never touches status=
    assert "evidence=" not in text
    assert "evidence_recorded_at=" not in text
    violations, _claims, active_tasks, _grabs, _issues = workboard_claims.evaluate_board(board)
    assert violations == []
    assert active_tasks[0].task_id == TASK_ID


def test_strip_evidence_on_a_line_with_no_evidence_is_a_no_op(repo: Path) -> None:
    board = _write_full_board(repo, status="in_progress")
    before = board.read_text(encoding="utf-8")

    stripped = claim_evidence.strip_evidence(TASK_ID, workboard_path=board)

    assert stripped is False
    assert board.read_text(encoding="utf-8") == before


# ---------------------------------------------------------------------------
# 2. set_task_status wiring
# ---------------------------------------------------------------------------


def test_set_task_status_strips_evidence_when_leaving_done(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    board = _write_full_board(repo, status="review")
    sha = _bind_commit(repo, f"{TASK_ID}: land the actual change")
    ok_done, _ = reactivate.set_task_status(board, task_id=TASK_ID, status="done", actor=AGENT, evidence=f"commit:{sha}")
    assert ok_done is True
    assert claim_evidence.read_evidence(TASK_ID, workboard_path=board).evidence is not None
    capsys.readouterr()  # discard done-transition output, only the strip's is under test

    ok_queued, payload = reactivate.set_task_status(board, task_id=TASK_ID, status="queued", actor=AGENT)

    assert ok_queued is True
    assert payload["evidence_stripped"] is True
    record = claim_evidence.read_evidence(TASK_ID, workboard_path=board)
    assert record.evidence is None
    assert record.recorded_at is None
    printed = capsys.readouterr().out
    assert "EVIDENCE REVOKED" in printed
    assert TASK_ID in printed


def test_set_task_status_does_not_strip_when_not_leaving_done(repo: Path) -> None:
    board = _write_full_board(repo, status="claimed")

    ok, payload = reactivate.set_task_status(board, task_id=TASK_ID, status="in_progress", actor=AGENT)

    assert ok is True
    assert payload["evidence_stripped"] is False


# ---------------------------------------------------------------------------
# 3. Legal re-done with fresh evidence passes
# ---------------------------------------------------------------------------


def test_legal_redone_via_set_task_status_with_new_evidence_passes(repo: Path) -> None:
    board = _write_full_board(repo, status="review")
    sha1 = _bind_commit(repo, f"{TASK_ID}: land the actual change (cycle 1)")
    ok, _ = reactivate.set_task_status(board, task_id=TASK_ID, status="done", actor=AGENT, evidence=f"commit:{sha1}")
    assert ok is True

    for target in ("queued", "claimed", "in_progress", "review"):
        ok, _ = reactivate.set_task_status(board, task_id=TASK_ID, status=target, actor=AGENT)
        assert ok is True, f"legal round-trip step to {target} failed"
    assert claim_evidence.read_evidence(TASK_ID, workboard_path=board).evidence is None

    sha2 = _bind_commit(repo, f"{TASK_ID}: land the actual change (cycle 2)")
    ok, payload = reactivate.set_task_status(board, task_id=TASK_ID, status="done", actor=AGENT, evidence=f"commit:{sha2}")

    assert ok is True
    assert payload["evidence_status"] == "verified"
    record = claim_evidence.read_evidence(TASK_ID, workboard_path=board)
    assert record.evidence == claim_evidence.parse_evidence(f"commit:{sha2}")


# ---------------------------------------------------------------------------
# 4. The reviewer's exact repro, end to end, now caught
# ---------------------------------------------------------------------------


def test_the_reviewers_four_step_repro_now_fails_the_gate(repo: Path) -> None:
    board = _write_full_board(repo, status="review")
    sha = _bind_commit(repo, f"{TASK_ID}: land the actual change")
    ok, _ = reactivate.set_task_status(board, task_id=TASK_ID, status="done", actor=AGENT, evidence=f"commit:{sha}")
    assert ok is True

    # Legal round trip all the way back to `review` -- every hop through the
    # real reactivate.set_task_status, never hand-edited.
    for target in ("queued", "claimed", "in_progress", "review"):
        ok, _ = reactivate.set_task_status(board, task_id=TASK_ID, status=target, actor=AGENT)
        assert ok is True, f"legal round-trip step to {target} failed"
    assert claim_evidence.read_evidence(TASK_ID, workboard_path=board).evidence is None

    # Commit the post-round-trip state: this becomes the gate's "old" (HEAD)
    # snapshot -- status=review, no evidence= field anywhere on the line.
    _commit_all(repo, "legal round trip back to review")

    # The bypass: a raw field flip, no set_task_status call, no
    # claim_evidence module touched at all -- the same shape a future
    # writer routed through issue.py's evidence-blind _set_task_status
    # would produce.
    text = board.read_text(encoding="utf-8")
    flipped = text.replace("status=review", "status=done")
    assert flipped != text
    board.write_text(flipped, encoding="utf-8", newline="\n")
    _stage_board(repo)

    result = gate.run_check(repo)

    assert result["ok"] is False
    [violation] = result["violations"]
    assert violation["classification"] == "missing_evidence"
    assert TASK_ID in violation["detail"]


# ---------------------------------------------------------------------------
# THE BLIND WINDOW (coordinator/reviewer finding, CRITICAL, reproduced): the
# per-cycle strip fix above closed the OBVIOUS shape of recycled evidence,
# but not a second, deeper one -- see workboard_evidence_gate.py's module
# docstring and CHANGELOG for the full "why".
# ---------------------------------------------------------------------------


def test_a_reopen_and_reflip_inside_one_uncommitted_diff_is_still_caught(repo: Path) -> None:
    """HEAD carries a genuinely verified done. The working copy reopens it
    through the real tooling (evidence stripped) and is then hand-reflipped
    straight back to `status=done` WITHOUT the intermediate `queued` state
    ever being committed -- so the one board diff the gate reads is simply
    `done` (with evidence) -> `done` (with NO evidence), both sides
    `"done"`. Before the scoping fix (`_done_transitions` in
    workboard_evidence_gate.py compared status alone), that read as an
    unchanged standing done and was skipped entirely -- a done with ZERO
    evidence landed clean.
    """
    board = _write_full_board(repo, status="review")
    sha = _bind_commit(repo, f"{TASK_ID}: land the actual change")
    ok, _ = reactivate.set_task_status(board, task_id=TASK_ID, status="done", actor=AGENT, evidence=f"commit:{sha}")
    assert ok is True
    _commit_all(repo, "board: done, with evidence")

    # The whole round trip happens between two board COMMITS -- the reopen
    # (evidence stripped) is never committed on its own.
    ok, payload = reactivate.set_task_status(board, task_id=TASK_ID, status="queued", actor=AGENT)
    assert ok is True
    assert payload["evidence_stripped"] is True
    text = board.read_text(encoding="utf-8")
    assert "evidence=" not in text

    # Hand-reflip straight back to done -- a bypass writer, no tooling at all.
    flipped = text.replace("status=queued", "status=done")
    assert flipped != text
    board.write_text(flipped, encoding="utf-8", newline="\n")
    _stage_board(repo)

    result = gate.run_check(repo)

    assert result["ok"] is False, "BLIND WINDOW: a done with zero evidence landed clean"
    [violation] = result["violations"]
    assert violation["classification"] == "missing_evidence"
    assert TASK_ID in violation["detail"]


def test_evidence_swapped_on_a_standing_done_with_no_reopen_is_caught(repo: Path) -> None:
    """The identical blind spot let evidence be SWAPPED on a standing done
    with no reopen at all -- a bypass writer edits `evidence=commit:<X>` to
    `evidence=commit:<Y>` in place, status untouched throughout. The old
    status-only scoping rule never even looked at the field to notice.
    """
    board = _write_full_board(repo, status="review")
    sha1 = _bind_commit(repo, f"{TASK_ID}: land the real change")
    ok, _ = reactivate.set_task_status(board, task_id=TASK_ID, status="done", actor=AGENT, evidence=f"commit:{sha1}")
    assert ok is True
    _commit_all(repo, "board: done, with evidence")

    bogus_sha = "f" * 40  # never committed anywhere in this repo
    text = board.read_text(encoding="utf-8")
    swapped = text.replace(f"evidence=commit:{sha1}", f"evidence=commit:{bogus_sha}")
    assert swapped != text
    board.write_text(swapped, encoding="utf-8", newline="\n")
    _stage_board(repo)

    result = gate.run_check(repo)

    assert result["done_transitions_checked"] == 1, "an evidence swap on a standing done must be IN SCOPE"
    assert result["ok"] is False, "BLIND SPOT: a swapped-in bogus commit on a standing done must be caught"
    [violation] = result["violations"]
    assert violation["classification"] == "failed"
    assert TASK_ID in violation["detail"]
