from __future__ import annotations

from pathlib import Path

import pytest

from thomas.server.chat_delegation_artifact_verification import _hidden_completion_review_passes
from thomas.server.chat_delegation_runner import _record_tool_outcome


def test_hidden_review_accepts_verified_nonempty_artifact(tmp_path: Path) -> None:
    (tmp_path / "report.md").write_text("# Reviewed report\n", encoding="utf-8")

    assert _hidden_completion_review_passes(
        "prompt wording is ignored",
        tmp_path,
        ["report.md"],
        "Structured artifact receipt",
        True,
        [],
        succeeded_tools=["fs.write_file", "fs.read_file"],
    )


@pytest.mark.parametrize("relative", ["missing.md", "empty.md", "../escape.md"])
def test_hidden_review_rejects_missing_empty_or_escaping_artifact(tmp_path: Path, relative: str) -> None:
    if relative == "empty.md":
        (tmp_path / relative).write_text("", encoding="utf-8")

    assert not _hidden_completion_review_passes(
        "ignored",
        tmp_path,
        [relative],
        "Structured artifact receipt",
        True,
        [],
    )


def test_prompt_words_do_not_change_artifact_review(tmp_path: Path) -> None:
    (tmp_path / "result.txt").write_text("actual output", encoding="utf-8")
    outcomes = {
        _hidden_completion_review_passes(prompt, tmp_path, ["result.txt"], "receipt", True, [])
        for prompt in ("make a graph", "make a game", "do not make a PDF")
    }

    assert outcomes == {True}


def test_recovered_read_failure_does_not_erase_verified_artifact(tmp_path: Path) -> None:
    (tmp_path / "result.txt").write_text("actual output", encoding="utf-8")

    assert _hidden_completion_review_passes(
        "ignored",
        tmp_path,
        ["result.txt"],
        "receipt",
        True,
        ["fs.read_file"],
        succeeded_tools=["fs.read_file", "fs.write_file"],
    )


def test_failed_write_is_not_masked_by_existing_artifact(tmp_path: Path) -> None:
    (tmp_path / "result.txt").write_text("actual output", encoding="utf-8")

    assert not _hidden_completion_review_passes(
        "ignored",
        tmp_path,
        ["result.txt"],
        "receipt",
        True,
        ["fs.write_file"],
        succeeded_tools=["fs.read_file"],
    )


def test_tool_outcome_keeps_both_success_and_failure_receipts() -> None:
    succeeded: list[str] = []
    failed: list[str] = []
    _record_tool_outcome("fs.write_file", ok=False, succeeded_tools=succeeded, failed_tools=failed)
    _record_tool_outcome("fs.write_file", ok=True, succeeded_tools=succeeded, failed_tools=failed)

    assert succeeded == ["fs.write_file"]
    assert failed == ["fs.write_file"]
