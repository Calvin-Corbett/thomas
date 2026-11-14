"""Adjacent ratchet reads share a staging only while green has not changed."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from tests.ratchet_support import candidate, commit, dev_moves, git, make_repo, on_ref
from thomas.server import green_checkout
from thomas.server.precard import review
from thomas.server.ratchet import attempt, merge_integrity, proof, screen
from thomas.server.ratchet.context import Attempt, Context, Hooks
from thomas.server.ratchet.gitrepo import Repo
from thomas.server.ratchet.ledger import Ledger


@pytest.fixture
def ready(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Context, Attempt]:
    repo = make_repo(tmp_path)
    base = git(repo, "rev-parse", "dev")
    sha = on_ref(repo, "refs/heads/fix/widget", base, {"thomas/core/widget.py": "VALUE = 2\n"}, "update widget")
    dev_moves(repo)
    found = screen.screen(Repo(repo), git(repo, "rev-parse", "dev"), candidate(sha, "refs/heads/fix/widget"))
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "greens"))
    green = green_checkout.create_green(repo, "ratchet-stage-test")
    (green.work / "thomas/core/widget.py").write_text("VALUE = 2\n", encoding="utf-8")
    hooks = Hooks(dirty_wait_s=0.0)
    ctx = Context(Repo(repo), Ledger(tmp_path / "ledger.jsonl"), hooks)
    att = Attempt(candidate(sha, "refs/heads/fix/widget"), git(repo, "rev-parse", "dev"), found, green)
    return ctx, att


@pytest.fixture
def stages(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    original = green_checkout._stage_everything

    def counted(green: green_checkout.Green) -> None:
        calls.append(green.execution_id)
        original(green)

    monkeypatch.setattr(green_checkout, "_stage_everything", counted)
    return calls


def test_last_checks_stages_once_and_reports_the_same_files_as_changed_paths(
    ready: tuple[Context, Attempt], stages: list[str]
) -> None:
    ctx, att = ready
    att.tree = green_checkout.green_tree(att.green)
    stages.clear()
    state, reason, files = attempt._last_checks(ctx, att)
    assert (state, reason) == ("", "")
    # Green has not changed since its tree was read just above, so nothing is staged again (2026-10-28,
    # green_checkout._stage_unless_unchanged); test_last_checks_sees_a_write_after_the_proof covers a change.
    assert stages == []
    assert files == green_checkout.changed_paths(att.green)


def test_last_checks_sees_a_write_after_the_proof(ready: tuple[Context, Attempt], stages: list[str]) -> None:
    ctx, att = ready
    att.tree = green_checkout.green_tree(att.green)
    (att.green.work / "README.md").write_text("changed after proof\n", encoding="utf-8")
    stages.clear()
    state, reason, files = attempt._last_checks(ctx, att)
    assert state == "reported" and "changed after its proof" in reason
    assert "README.md" in files
    assert len(stages) == 1


def test_second_look_passes_the_same_patch_without_staging(
    ready: tuple[Context, Attempt], stages: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, att = ready
    att.tree = green_checkout.green_tree(att.green)
    assert attempt._last_checks(ctx, att)[0] == ""
    expected = green_checkout.green_patch(att.green)
    seen: list[str] = []
    monkeypatch.setattr(review, "turned_off", lambda: False)
    monkeypatch.setattr(review, "second_look", lambda _id, _request, checked: seen.append(checked.patch))
    stages.clear()
    attempt._second_look(ctx, att, proof.Verdict(True, "passed"))
    assert seen == [expected]
    assert not stages


def test_the_readers_write_is_caught_by_the_next_checks(
    ready: tuple[Context, Attempt], stages: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx, att = ready
    att.tree = green_checkout.green_tree(att.green)
    assert attempt._last_checks(ctx, att)[0] == ""
    monkeypatch.setattr(review, "turned_off", lambda: False)

    def read_and_write(_id: str, _request: str, _checked: object) -> None:
        (att.green.work / "README.md").write_text("reader changed me\n", encoding="utf-8")

    monkeypatch.setattr(review, "second_look", read_and_write)
    attempt._second_look(ctx, att, proof.Verdict(True, "passed"))
    stages.clear()
    state, reason, files = attempt._last_checks(ctx, att)
    assert state == "reported" and "changed after its proof" in reason
    assert "README.md" in files
    assert len(stages) == 1


@pytest.mark.parametrize("restore_board", [False, True])
def test_prove_green_stages_again_only_if_restoration_writes(
    ready: tuple[Context, Attempt], stages: list[str], monkeypatch: pytest.MonkeyPatch, restore_board: bool
) -> None:
    ctx, att = ready
    if restore_board:
        board = "plans/thomas/WORKBOARD.md"
        (att.green.work / board).write_text("board changed\n", encoding="utf-8")

        original_restore = attempt.restore_left_out

        def restore_with_board(green: green_checkout.Green) -> list[str]:
            original_restore(green)
            green_checkout.restore_paths(green, [board])
            return [board]

        monkeypatch.setattr(attempt, "restore_left_out", restore_with_board)
    monkeypatch.setattr(attempt, "select", lambda *_a, **_kw: attempt.proof_set.ProofSet((), left_out=1))
    stages.clear()
    asyncio.run(attempt.prove_green(ctx, att))
    assert len(stages) == (2 if restore_board else 1)
    assert "plans/thomas/WORKBOARD.md" not in green_checkout.changed_paths(att.green)


def test_wrong_green_stages_once(ready: tuple[Context, Attempt], stages: list[str]) -> None:
    ctx, att = ready
    assert merge_integrity.wrong_green(ctx, att) == ""
    assert len(stages) == 1
