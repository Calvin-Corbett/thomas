"""What a landing does with a refusal, a rewrite and a selection that changed while the branch moved under it.

Companion to tests/test_commit_attempts.py (the rebases themselves). A refusal from a gate that ran while the tip moved is
not trusted at first; the same words again after the landing rebased are real; attempts that run out on a refusal that keeps
changing report the gate's refusal, not a race; a branch that was rewritten is never rebased onto.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.crew.brief import commit_attempts, gate_runner

from tests.commit_lane_support import Lane, make_lane


@pytest.fixture
def lane(tmp_path: Path, monkeypatch) -> Lane:
    monkeypatch.setenv(gate_runner.WORKERS_ENV, "1")  # serial order: what each test reads off the log is deterministic
    monkeypatch.delenv("THOMAS_COMMIT_BASE", raising=False)
    return make_lane(tmp_path)


def _rewrite_lines(lane: Lane) -> list[str]:
    """Lines for a gate that rewrites the branch: the same tree under a history with no parent.

    The working tree still reads clean against it, so only the question "is the old tip an ancestor of the new one" can tell
    this is a rewrite and not a neighbour landing."""
    return [
        "import subprocess",
        f"git = lambda *a: subprocess.run(['git', *a], cwd={str(lane.repo)!r}, capture_output=True, text=True, check=True).stdout.strip()",
        "tree = git('rev-parse', 'HEAD^{tree}')",
        "root = git('-c', 'user.name=N', '-c', 'user.email=n@example.invalid', 'commit-tree', tree, '-m', 'rewritten history')",
        "git('update-ref', 'refs/heads/master', root)",
    ]


def test_a_refusal_from_a_gate_that_ran_while_the_tip_moved_is_not_final(lane: Lane) -> None:
    gates = (("judge", lane.logging("judge", *lane.lands_a_neighbour(fail=True))),)
    result = lane.land(gates)
    assert result.ok is True, (result.blocker_class, result.message, result.gate_output)
    assert lane.ran() == ["judge", "judge"]  # refused once while the tip moved, judged again on the new base, passed


def test_a_refusal_at_a_stable_tip_is_final_and_comes_back_at_once(lane: Lane) -> None:
    before = lane.head()
    result = lane.land((("judge", lane.logging("judge", "print('really no')", code=1)),))
    assert (result.ok, result.blocker_class, result.gate_name) == (False, "local_gate_failed", "judge")
    assert "really no" in result.gate_output
    assert lane.ran() == ["judge"]  # not retried
    assert lane.head() == before


def test_after_the_attempt_cap_the_landing_is_a_branch_race_and_nothing_of_it_lands(lane: Lane, monkeypatch) -> None:
    monkeypatch.setattr(commit_attempts, "MAX_ATTEMPTS", 2)
    result = lane.land((("mover", lane.logging("mover", *lane.lands_a_neighbour(times=9))),))  # passes, moves the tip
    assert (result.ok, result.blocker_class) == (False, "branch_race")
    assert lane.ran() == ["mover", "mover"]
    assert "feat: land" not in lane.subjects()
    assert (lane.repo / "src" / "app.py").read_text() == 'print("changed")\n'  # the work is still there to land again


def test_a_refusal_that_comes_back_word_for_word_after_a_rebase_is_real_and_final(lane: Lane) -> None:
    result = lane.land((("judge", lane.logging("judge", *lane.lands_a_neighbour(times=9, fail=True))),))
    assert (result.ok, result.blocker_class, result.gate_name) == (False, "local_gate_failed", "judge")
    assert result.gate_output == "spurious refusal"  # the agent reads why, not "the branch moved"
    assert lane.ran() == ["judge", "judge"]  # not three: the second attempt confirmed it
    assert "feat: land" not in lane.subjects()


def test_a_refusal_that_keeps_changing_stops_at_the_cap_and_is_reported_as_the_gates_refusal(
    lane: Lane, monkeypatch
) -> None:
    monkeypatch.setattr(commit_attempts, "MAX_ATTEMPTS", 3)
    result = lane.land((("judge", lane.logging("judge", *lane.lands_a_neighbour(times=9, fail=True, vary=True))),))
    assert (result.ok, result.blocker_class, result.gate_name) == (False, "local_gate_failed", "judge")
    assert "judged while the branch moved, on 3 attempts" in result.message
    assert lane.ran() == ["judge"] * 3
    assert result.gate_output.startswith("spurious refusal ")


def test_a_branch_that_was_rewritten_rather_than_advanced_is_not_rebased_onto(lane: Lane) -> None:
    result = lane.land((("rewriter", lane.logging("rewriter", *_rewrite_lines(lane))),))
    assert (result.ok, result.blocker_class) == (False, "branch_race")
    assert lane.subjects() == ["rewritten history"]  # the rewritten branch was left exactly as it was found


def test_a_race_that_ends_a_refusing_landing_still_tells_the_agent_which_gate_said_no(lane: Lane) -> None:
    lines = [*_rewrite_lines(lane), "print('refused: unread mail')"]
    result = lane.land((("rewriter", lane.logging("rewriter", *lines, code=1)),))
    assert (result.ok, result.blocker_class, result.gate_name) == (False, "branch_race", "rewriter")
    assert result.gate_output == "refused: unread mail"


def test_a_selection_that_changed_during_the_landing_fails_closed(lane: Lane) -> None:
    sneak = [*lane.lands_a_neighbour(), f"open({str(lane.repo / 'src' / 'extra.py')!r}, 'w').write('x = 1')"]
    result = lane.land((("mover", lane.logging("mover", *sneak)),))
    assert (result.ok, result.blocker_class) == (False, "branch_race")
    assert "selected paths changed" in result.message
