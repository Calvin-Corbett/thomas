"""Part 4's pass line is read from the window's record, dev and the outbox (spec section 8, Goal and pass line).

Its own tmp record, outbox and git repo.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from scripts.cage import self_change_checks as checks
from scripts.cage.window_record import Record
from scripts.praxis import window_audit as wa

from tests.green_support import git, make_blue


@pytest.fixture
def world(tmp_path: Path) -> tuple[Path, Record, Path]:
    repo = make_blue(tmp_path)
    git(repo, "checkout", "-q", "-b", "dev")
    (tmp_path / "record").mkdir()
    (tmp_path / "outbox").mkdir()
    return repo, Record(tmp_path / "record"), tmp_path / "outbox"


def _land(repo: Path, outbox: Path, sid: str, value: int) -> str:
    parent = git(repo, "rev-parse", "dev")
    (repo / "thomas" / "fix_me.py").write_text(f"VALUE = {value}\n", encoding="utf-8")
    git(repo, "add", "-A")
    trailers = [("Thomas-Committed-By", "self-change-promoter"), ("Thomas-Submission-Id", sid)]
    commit = checks.make_commit(repo, git(repo, "write-tree"), parent, f"self-fix: {sid}", trailers)
    git(repo, "update-ref", "refs/heads/dev", commit, parent)
    git(repo, "reset", "-q", "--hard", "dev")
    (outbox / f"{sid}.verdict.json").write_text(json.dumps({"status": "landed"}), encoding="utf-8")
    return commit


def _window_landing(record: Record, sid: str, commit: str, *, after: bool = True, **over: object) -> None:
    record.event("landing_intent", window_id="w", sid=sid, commit=commit)
    evidence = {"window_id": "w", "sid": sid, "commit": commit, "tree": "t" * 40, "change": "c" * 64,
                "check_job": "j" * 24, "check_verdict": "PASSED", "check_tree": "t" * 40, "second_look": "SAFE",
                "second_look_change": "c" * 64}  # fmt: skip
    evidence.update(over)
    record.event("landed", **evidence)
    if after:
        record.event("after_check", sid=sid, commit=commit, verdict="PASSED", why="", findings=[])


def test_one_sign_in_that_landed_two_proven_changes_meets_the_line(world: tuple[Path, Record, Path]) -> None:
    repo, record, outbox = world
    record.event("window_opened", window_id="w")
    for n, sid in enumerate(("self-thomas-a", "self-thomas-b"), 2):
        _window_landing(record, sid, _land(repo, outbox, sid, n))

    result = wa.audit(record.root, repo, outbox)

    assert result["pass_line_met"] is True and result["landings_per_sign_in"] == 2.0


@pytest.mark.parametrize("missing", ["second_look", "check_job"])
def test_a_landing_without_its_evidence_misses_the_line(world: tuple[Path, Record, Path], missing: str) -> None:
    repo, record, outbox = world
    record.event("window_opened", window_id="w")
    _window_landing(record, "self-thomas-a", _land(repo, outbox, "self-thomas-a", 2), **{missing: ""})
    result = wa.audit(record.root, repo, outbox)
    assert result["unproven"] == ["self-thomas-a"] and result["pass_line_met"] is False


@pytest.mark.parametrize(
    "over",
    [
        {"second_look_change": "d" * 64},  # a second look of another derivation (2026-10-14 review, WS-R1)
        {"second_look_change": ""},
        {"check_verdict": "FAILED"},
        {"check_verdict": ""},
        {"check_tree": "u" * 40},  # a check of another tree
        {"check_tree": ""},
    ],
)
def test_a_landing_whose_evidence_is_not_for_what_landed_misses_the_line(
    world: tuple[Path, Record, Path], over: dict[str, str]
) -> None:
    """2026-10-14 review (A5): the audit took any check job and the word SAFE as proof, so a landing on a second look of
    an older change counted as proven."""
    repo, record, outbox = world
    record.event("window_opened", window_id="w")
    _window_landing(record, "self-thomas-a", _land(repo, outbox, "self-thomas-a", 2), **over)
    result = wa.audit(record.root, repo, outbox)
    assert result["unproven"] == ["self-thomas-a"] and result["pass_line_met"] is False


def test_a_landing_never_checked_after_it_landed_misses_the_line(world: tuple[Path, Record, Path]) -> None:
    repo, record, outbox = world
    record.event("window_opened", window_id="w")
    _window_landing(record, "self-thomas-a", _land(repo, outbox, "self-thomas-a", 2))
    _window_landing(record, "self-thomas-b", _land(repo, outbox, "self-thomas-b", 3), after=False)
    result = wa.audit(record.root, repo, outbox)
    assert result["not_checked_after_landing"] == ["self-thomas-b"] and result["pass_line_met"] is False


def test_a_change_landed_twice_or_missing_from_dev_misses_the_line(world: tuple[Path, Record, Path]) -> None:
    repo, record, outbox = world
    record.event("window_opened", window_id="w")
    _window_landing(record, "self-thomas-a", _land(repo, outbox, "self-thomas-a", 2))
    _land(repo, outbox, "self-thomas-a", 3)
    _window_landing(record, "self-thomas-b", "f" * 40)

    result = wa.audit(record.root, repo, outbox)

    assert result["landed_twice"] == ["self-thomas-a"] and result["lost"] == ["self-thomas-b"]
    assert result["pass_line_met"] is False


def test_a_landing_the_promoter_stopped_inside_and_never_settled_misses_the_line(
    world: tuple[Path, Record, Path],
) -> None:
    repo, record, outbox = world
    record.event("window_opened", window_id="w")
    record.event("landing_intent", window_id="w", sid="self-thomas-a", commit="e" * 40)
    assert wa.audit(record.root, repo, outbox)["unsettled_landings"] == 1
