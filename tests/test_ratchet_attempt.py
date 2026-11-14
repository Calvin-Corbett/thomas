"""One candidate on today's dev: merged in a green, proven in the cage, and handed to your card."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from tests.ratchet_support import FakeCage, candidate, dev_moves, extra_candidate, git, make_repo, on_ref, submissions
from thomas.server import green_checkout
from thomas.server.ratchet.attempt import Context, DevMoved, Hooks, prove_candidate
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.ledger import Ledger
from thomas.server.ratchet.proof_set import ARCHITECTURE_TEST

EXTRA = "tests/test_extra.py::test_extra"
ARCH = f"{ARCHITECTURE_TEST}::test_architecture"


def _ctx(repo: Path, tmp_path: Path, cage: FakeCage) -> Context:
    hooks = Hooks(run_caged=cage, runner_alive=lambda: True, dirty_wait_s=0.0)
    return Context(repo=Repo(repo), ledger=Ledger(tmp_path / "ratchet" / "ledger.jsonl"), hooks=hooks)


def _kinds(cage: FakeCage) -> set[str]:
    """base, cand, prnt, land or halt: the kinds of green the cage was asked to end."""
    return {green.split("-")[1] for green in cage.ended}


def test_a_clean_candidate_is_proven_in_the_cage_and_waits_for_your_card(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    cage = FakeCage()
    ctx = _ctx(repo, tmp_path, cage)

    state = asyncio.run(prove_candidate(ctx, candidate(sha, "refs/heads/fix/extra")))

    assert state == "awaiting_card"
    [submission] = submissions()
    meta = json.loads((submission / "submission.json").read_text(encoding="utf-8"))
    assert meta["summary"].splitlines()[0] == f"ratchet: land fix/extra ({sha[:12]})"
    assert sorted(meta["files"]) == ["tests/test_extra.py", "thomas/core/extra.py"]  # the board edit is left out
    states = [e["state"] for e in ctx.ledger.events()]
    assert states == ["proving", "settling", "awaiting_card"]
    root = green_checkout.green_root()
    assert cage.calls and all(Path(cwd).is_relative_to(root) for _, cwd in cage.calls)
    assert set(cage.labels) == {"base", "cand"}
    assert _kinds(cage) == {"base", "cand"}  # nothing either green started is left running
    assert not list((root / "work").iterdir())  # no green and no proof folder left behind


def test_a_new_failure_is_reported_and_nothing_is_submitted(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    cage = FakeCage({"cand": {"tests/test_extra.py"}})
    ctx = _ctx(repo, tmp_path, cage)

    assert asyncio.run(prove_candidate(ctx, candidate(sha))) == "reported"
    assert f"1 new failure(s): {EXTRA}" in ctx.ledger.latest()[sha]["reason"]
    assert submissions() == []
    assert "cand" in _kinds(cage)  # a green that is never settled is still ended


def test_a_failure_dev_already_has_does_not_block(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    ctx = _ctx(repo, tmp_path, FakeCage({"base": {ARCHITECTURE_TEST}, "cand": {ARCHITECTURE_TEST}}))

    assert asyncio.run(prove_candidate(ctx, candidate(sha))) == "awaiting_card"


def test_a_failure_dev_has_only_sometimes_does_not_excuse_the_candidate(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    cage = FakeCage({"base": {ARCHITECTURE_TEST}, "cand": {ARCHITECTURE_TEST}}, alone={ARCH})
    ctx = _ctx(repo, tmp_path, cage)

    assert asyncio.run(prove_candidate(ctx, candidate(sha))) == "reported"
    assert f"1 new failure(s): {ARCH}" in ctx.ledger.latest()[sha]["reason"]


def test_a_failure_that_passes_alone_still_blocks_and_is_named(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    ctx = _ctx(repo, tmp_path, FakeCage({"cand": {"tests/test_extra.py"}}, alone={EXTRA}))

    assert asyncio.run(prove_candidate(ctx, candidate(sha))) == "reported"
    event = ctx.ledger.latest()[sha]
    assert event["proof"]["flaky"] == [EXTRA] and "pass when run alone" in event["reason"]


def test_a_candidate_that_deletes_a_passing_test_file_is_reported(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    files = {"tests/test_widget.py": None, "thomas/core/extra.py": "X = 1\n"}
    sha = on_ref(repo, "refs/heads/drop", base, files, "drop a test file")
    dev_moves(repo)
    ctx = _ctx(repo, tmp_path, FakeCage())

    assert asyncio.run(prove_candidate(ctx, candidate(sha))) == "reported"
    reason = ctx.ledger.latest()[sha]["reason"]
    assert reason == "1 test(s) that pass on dev are gone or skipped: tests/test_widget.py::test_widget"


def test_a_board_edit_dev_made_too_is_left_out_not_sent_to_a_repair(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo, "another session claims work", {"plans/thomas/WORKBOARD.md": "claimed by dev\n"})
    cage = FakeCage()
    ctx = _ctx(repo, tmp_path, cage)  # no repairs: a conflict counted here would leave it queued

    assert asyncio.run(prove_candidate(ctx, candidate(sha, "refs/heads/fix/extra"))) == "awaiting_card"
    [submission] = submissions()
    meta = json.loads((submission / "submission.json").read_text(encoding="utf-8"))
    assert sorted(meta["files"]) == ["tests/test_extra.py", "thomas/core/extra.py"]
    assert set(cage.labels) == {"base", "cand"}


def test_work_the_running_copy_holds_waits_before_any_green(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    (repo / "thomas" / "core" / "extra.py").write_text("X = 0\n", encoding="utf-8")  # another session's work
    cage = FakeCage()
    ctx = _ctx(repo, tmp_path, cage)

    assert asyncio.run(prove_candidate(ctx, candidate(sha))) == "queued"
    reason = ctx.ledger.latest()[sha]["reason"]
    assert reason == "waiting: the running copy has uncommitted work in thomas/core/extra.py"
    assert cage.calls == [] and cage.ended == []


def test_already_on_dev_and_conflicts_spend_no_green(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    same = on_ref(repo, "refs/heads/same", base, {"thomas/core/widget.py": "VALUE = 2\n"}, "same")
    clash = on_ref(repo, "refs/heads/clash", base, {"thomas/core/widget.py": "VALUE = 3\n"}, "clash")
    dev_moves(repo, "dev fixes it", {"thomas/core/widget.py": "VALUE = 2\n"})
    cage = FakeCage()
    ctx = _ctx(repo, tmp_path, cage)

    assert asyncio.run(prove_candidate(ctx, candidate(same, "refs/heads/same"))) == "already_on_dev"
    assert asyncio.run(prove_candidate(ctx, candidate(clash, "refs/heads/clash"))) == "queued"
    assert "1 conflict(s)" in ctx.ledger.latest()[clash]["reason"]
    assert cage.calls == []
    assert ctx.ledger.latest()[same]["archive"] == {"refs/heads/same": "copied to refs/archive/ratchet/heads/same"}
    assert git(repo, "rev-parse", "refs/heads/same") == same  # the branch itself is never deleted


def test_a_green_that_starts_with_a_file_missing_is_refused_before_anything_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_green can exit 0 with a tracked file never written (a path Windows would not take). Scratch run
    9c handed that hole in as a deletion its candidate never made, and the proof passed it."""
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    cage = FakeCage()
    ctx = _ctx(repo, tmp_path, cage)
    made = green_checkout.create_green

    def holed(blue: Path, execution_id: str) -> green_checkout.Green:
        green = made(blue, execution_id)
        (green.work / "thomas" / "core" / "old.py").unlink()  # the checkout that did not write one file
        return green

    monkeypatch.setattr(green_checkout, "create_green", holed)

    with pytest.raises(green_checkout.GreenUnavailable) as refused:
        asyncio.run(prove_candidate(ctx, candidate(sha)))

    assert "starts with 1 file(s) already changed" in str(refused.value)
    assert "thomas/core/old.py" in str(refused.value)
    assert submissions() == [] and cage.calls == []
    assert not list((green_checkout.green_root() / "work").iterdir())  # the holed green is gone


def test_a_green_that_holds_more_than_the_candidates_change_is_reported_before_a_proof(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    cage = FakeCage()
    ctx = _ctx(repo, tmp_path, cage)
    applied = green_checkout.apply_candidate

    def and_a_deletion(green: green_checkout.Green, commit: str, *, pick: bool = False) -> list[str]:
        conflicts = applied(green, commit, pick=pick)
        (green.work / "thomas" / "core" / "old.py").unlink()  # nothing the candidate touches
        return conflicts

    monkeypatch.setattr(green_checkout, "apply_candidate", and_a_deletion)

    assert asyncio.run(prove_candidate(ctx, candidate(sha))) == "reported"
    reason = ctx.ledger.latest()[sha]["reason"]
    assert reason == (
        "what green holds is not the candidate's change: thomas/core/old.py is deleted, "
        "and the candidate does not delete it"
    )
    assert submissions() == [] and cage.calls == []  # no proof was spent on it


def test_dev_moving_during_the_proof_stops_the_attempt(tmp_path: Path) -> None:
    repo = make_repo(tmp_path)
    sha = extra_candidate(repo)
    dev_moves(repo)
    cage = FakeCage(during=lambda label: dev_moves(repo, "someone landed") if label == "cand" else None)
    ctx = _ctx(repo, tmp_path, cage)

    with pytest.raises(DevMoved):
        asyncio.run(prove_candidate(ctx, candidate(sha)))
    assert submissions() == []
