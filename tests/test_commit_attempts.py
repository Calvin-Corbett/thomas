"""A landing that loses the race to a neighbour rebases and lands, instead of failing and paying the whole ladder again.

scripts/crew/brief/commit_attempts.py owns the attempts. The neighbour here is real: a script that makes a commit on the
branch with git plumbing, exactly as another agent's landing does, run from inside a gate (the tip moves while the gates
judge), between the commit object and the swap, and at the swap itself. Gates are `python -c` programs that log what they
ran and which base they were handed, so what was re-judged is read off a file. Refusals, the cap and rewrites are in
tests/test_commit_attempts_refusals.py.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from scripts.crew.brief import gate_runner

from tests.commit_lane_support import Lane, git, init_repo, make_lane, mod, program, write
from tests.sleep_support import skip_sleeps


@pytest.fixture
def lane(tmp_path: Path, monkeypatch) -> Lane:
    monkeypatch.setenv(gate_runner.WORKERS_ENV, "1")  # serial order: what each test reads off the log is deterministic
    monkeypatch.delenv("THOMAS_COMMIT_BASE", raising=False)
    return make_lane(tmp_path)


def _count_calls(monkeypatch, name: str) -> list:
    calls: list = []
    real = getattr(mod, name)

    def spy(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(mod, name, spy)
    return calls


def test_a_move_during_the_gates_rebases_and_lands_on_the_neighbours_commit(lane: Lane, monkeypatch) -> None:
    before = lane.head()
    made = _count_calls(monkeypatch, "_create_commit_object")
    gates = (
        ("exception_handler", lane.logging("exception_handler")),  # kept: its inputs are fingerprinted and unchanged
        ("bulk_commit", lane.logging("bulk_commit")),  # judged again: only exception_handler and the guard are kept
        ("mover", lane.logging("mover", *lane.lands_a_neighbour())),
        ("workboard_claims", lane.logging("workboard_claims")),  # reads live state
    )
    result = lane.land(gates)
    assert result.ok is True, (result.blocker_class, result.message, result.gate_output)
    parent = git(lane.repo, "rev-parse", f"{result.commit_sha}^")
    assert lane.subjects() == ["feat: land", "neighbour lands other/n0.txt", "init"]
    assert git(lane.repo, "rev-parse", f"{parent}^") == before  # one neighbour between: linear history
    assert lane.head() == result.commit_sha
    assert len(made) == 1, "a commit object was made on a base the gates had already seen move"
    assert lane.ran().count("exception_handler") == 1  # the fingerprinted gate's pass stood
    assert lane.ran().count("bulk_commit") == 2  # every other gate judged again, selection-only or not
    assert lane.ran().count("mover") == 2 and lane.ran().count("workboard_claims") == 2


def test_gates_are_handed_the_base_their_index_was_built_on_and_a_stale_value_never_leaks(
    lane: Lane, monkeypatch
) -> None:
    monkeypatch.setenv("THOMAS_COMMIT_BASE", "inherited-garbage")
    before = lane.head()
    result = lane.land((("mover", lane.logging("mover", *lane.lands_a_neighbour())),))
    assert result.ok is True, (result.message, result.gate_output)
    after_neighbour = git(lane.repo, "rev-parse", f"{result.commit_sha}^")
    assert lane.bases("mover") == [before, after_neighbour]


def test_a_neighbour_landing_between_the_commit_object_and_the_race_check_rebases(lane: Lane, monkeypatch) -> None:
    real = mod._create_commit_object
    calls = []

    def create_then_neighbour_lands(*args, **kwargs):
        sha = real(*args, **kwargs)
        calls.append(sha)
        if len(calls) == 1:
            lane.neighbour_lands("other/late.txt")
        return sha

    monkeypatch.setattr(mod, "_create_commit_object", create_then_neighbour_lands)
    result = lane.land((("quiet", lane.logging("quiet")),))
    assert result.ok is True, (result.blocker_class, result.message)
    assert len(calls) == 2 and result.commit_sha == calls[1] != calls[0]
    assert lane.subjects()[:2] == ["feat: land", "neighbour lands other/late.txt"]


def test_a_swap_that_loses_to_a_neighbour_at_the_ref_rebases(lane: Lane, monkeypatch) -> None:
    real = mod._update_branch_ref
    calls = []

    def neighbour_wins_the_swap(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            lane.neighbour_lands("other/swap.txt")
        return real(*args, **kwargs)  # the real compare-and-swap: refused, "is at X but expected Y"

    monkeypatch.setattr(mod, "_update_branch_ref", neighbour_wins_the_swap)
    result = lane.land((("quiet", lane.logging("quiet")),))
    assert result.ok is True, (result.blocker_class, result.message)
    assert len(calls) == 2
    assert lane.subjects()[:2] == ["feat: land", "neighbour lands other/swap.txt"]


def test_the_two_proven_no_op_gates_are_left_out_while_the_board_is_not_selected(lane: Lane) -> None:
    gates = (
        ("workboard_evidence", lane.logging("workboard_evidence")),
        ("problem_closure", lane.logging("problem_closure")),
        ("ordinary", lane.logging("ordinary")),
    )
    assert lane.land(gates).ok is True
    assert lane.ran() == ["ordinary"]


def test_a_selected_board_brings_both_no_op_gates_back(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(gate_runner.WORKERS_ENV, "1")
    repo, board = init_repo(
        tmp_path,
        claims=(
            "agent=codex; name=Codex; role=solo; parent=none; scope=src,plans/thomas/WORKBOARD.md; task=Scoped commit",
        ),
    )
    text = board.read_text(encoding="utf-8")
    board.write_text(text.replace("# Workboard", "# Workboard (touched)", 1), encoding="utf-8")
    log = tmp_path / "gates.log"

    def gate(name: str) -> tuple[str, ...]:
        return program(f"open({str(log)!r}, 'a').write({name!r} + chr(10))")

    result = mod.commit_scoped_changes(
        message="chore: board",
        agent="codex",
        repo_root=repo,
        workboard_path=board,
        local_gate_commands=(
            ("workboard_evidence", gate("workboard_evidence")),
            ("problem_closure", gate("problem_closure")),
        ),
    )
    assert result.ok is True, (result.blocker_class, result.message)
    assert log.read_text().split() == ["workboard_evidence", "problem_closure"]


def test_a_dry_run_judges_and_lands_nothing(lane: Lane) -> None:
    before = lane.head()
    result = lane.land((("ordinary", lane.logging("ordinary")),), dry_run=True)
    assert (result.ok, result.dry_run, result.commit_sha) == (True, True, None)
    assert lane.head() == before and lane.ran() == ["ordinary"]


def test_the_live_index_is_realigned_even_when_a_neighbour_holds_the_lock_for_a_moment(lane: Lane, monkeypatch) -> None:
    real = mod._sync_live_index
    attempts = []

    def lock_held_twice(repo_root, selected):
        attempts.append(1)
        if len(attempts) <= 2:
            raise RuntimeError("fatal: Unable to create '.git/index.lock': File exists.")
        return real(repo_root, selected)

    monkeypatch.setattr(mod, "_sync_live_index", lock_held_twice)
    skip_sleeps(monkeypatch)
    result = lane.land((("quiet", lane.logging("quiet")),))
    assert result.ok is True and len(attempts) == 3


def test_a_realign_that_never_succeeds_says_the_commit_did_land(lane: Lane, monkeypatch) -> None:
    def refuse(*args):
        raise RuntimeError("fatal: not a lock")

    monkeypatch.setattr(mod, "_sync_live_index", refuse)
    result = lane.land((("quiet", lane.logging("quiet")),))
    assert (result.ok, result.blocker_class) == (False, "broken_repo_tool")
    assert "the commit landed as " in result.message and lane.head() in result.message


def test_a_gate_that_cannot_start_is_still_a_broken_tool_not_a_refusal(lane: Lane) -> None:
    result = lane.land((("ghost", (str(lane.root / "no-such-program.exe"),)),))
    assert (result.ok, result.blocker_class) == (False, "broken_repo_tool")


def test_three_committers_on_one_repo_land_exactly_once_each(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv(gate_runner.WORKERS_ENV, "2")
    monkeypatch.delenv("THOMAS_COMMIT_BASE", raising=False)
    claims = tuple(
        f"agent=agent{i}; name=A{i}; role=solo; parent=none; scope=src/a{i}; task=Scoped commit {i}" for i in range(3)
    )
    repo, board = init_repo(tmp_path, claims=claims)
    for i in range(3):
        write(repo / "src" / f"a{i}" / "f.py", f"VALUE = {i}\n")
    slow = (("slow", program("import time", "time.sleep(0.6)")),)  # long enough that the three overlap
    results: list = [None] * 3
    start = threading.Barrier(3)

    def land(i: int) -> None:
        start.wait()
        results[i] = mod.commit_scoped_changes(
            message=f"feat: agent {i}",
            agent=f"agent{i}",
            repo_root=repo,
            workboard_path=board,
            local_gate_commands=slow,
        )

    threads = [threading.Thread(target=land, args=(i,)) for i in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=300)
    assert all(r is not None and r.ok for r in results), [(r.blocker_class, r.message) for r in results if r]
    shas = [r.commit_sha for r in results]
    assert len(set(shas)) == 3, "a landing was duplicated"
    rows = git(repo, "log", "--format=%H|%P|%s").splitlines()
    assert len(rows) == 4, rows  # init plus exactly three: none lost, none doubled
    assert all(len(row.split("|")[1].split()) <= 1 for row in rows), "history is not linear"
    for i, r in enumerate(results):
        files = git(repo, "show", "--name-only", "--format=", r.commit_sha).splitlines()
        assert files == [f"src/a{i}/f.py"], files
    assert git(repo, "status", "--porcelain", "--", "src").strip() == ""
