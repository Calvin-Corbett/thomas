"""A run that delivered nothing must not have its narrative graded instead.

The Exhaustive panel builds each grader's prompt from the artifacts found in the
workspace. When that list was empty the grader was told "This is answer-only; do
not call tools" -- the same instruction a task with no deliverables gets. So a
run that was required to produce files and produced none had its ACCOUNT of the
work graded, by a panel whose own instructions say to grade the deliverables and
not the worker narrative.

Empty said two opposite things: "nothing was expected" and "everything expected
is missing". Until today the second was also being caused by a path bug that
emptied the evidence list for every workspace under `~/.thomas` -- which is
where all of them live.
"""

from __future__ import annotations

from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1] / "thomas" / "server" / "exhaustive_runtime.py"


def _review_body() -> str:
    text = RUNTIME.read_text(encoding="utf-8")
    return text.split("async def _review", 1)[1].split("\n    async def ", 1)[0]


def test_the_two_kinds_of_empty_are_told_apart() -> None:
    body = _review_body()

    assert "artifacts_missing" in body
    assert "bool(expected_artifact_paths) and not artifact_rows" in body


def test_a_grader_is_told_when_required_work_is_absent() -> None:
    body = _review_body()

    assert "the workspace contains none of it" in body
    assert "however convincing the account of it reads" in body


def test_the_missing_case_names_what_was_required() -> None:
    """A grader that is told only 'something is missing' cannot weigh it."""
    body = _review_body()

    assert "expected_artifact_paths[:5]" in body


def test_a_task_with_no_expected_artifacts_is_still_answer_only() -> None:
    """The honest answer-only case must survive: not every task makes files."""
    body = _review_body()

    assert "This is answer-only; do not call tools. " in body


def test_a_task_with_artifacts_still_reads_them() -> None:
    body = _review_body()

    assert "fs.list_dir and fs.read_file" in body
    assert "not the worker narrative" in body


def test_the_branches_are_mutually_exclusive() -> None:
    """artifact_rows wins, then missing, then answer-only -- so a run with real
    files is never told its work is absent."""
    body = _review_body()
    present = body.index("fs.list_dir and fs.read_file")
    missing = body.index("the workspace contains none of it")
    answer_only = body.index("This is answer-only")

    assert present < missing < answer_only
