"""A copy that has not changed since it was last staged is not staged again (2026-10-28).

Every read of a copy's change (``changed_paths``, ``changed_status``, ``green_patch``, ``green_tree``) staged the whole
copy again: about six git processes each. Measured 2026-10-28, one hand-in test staged the same unchanged copy 14
times; 43-44% of the most-selected test files' CPU was git processes. A read now stages only when the copy's files,
its index or its base moved since the last staging, and a write that lands while git stages is never taken as staged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.ratchet_support import make_repo
from thomas.server import green_checkout


@pytest.fixture
def green(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> green_checkout.Green:
    repo = make_repo(tmp_path)
    monkeypatch.setenv(green_checkout.GREEN_ROOT_ENV, str(tmp_path / "greens"))
    made = green_checkout.create_green(repo, "staged-once-test")
    (made.work / "thomas/core/widget.py").write_text("VALUE = 2\n", encoding="utf-8")
    return made


@pytest.fixture
def stages(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    original = green_checkout._stage_everything

    def counted(green: green_checkout.Green) -> None:
        calls.append(green.execution_id)
        original(green)

    monkeypatch.setattr(green_checkout, "_stage_everything", counted)
    return calls


def test_reading_an_unchanged_copy_again_stages_it_once(green: green_checkout.Green, stages: list[str]) -> None:
    first = green_checkout.changed_paths(green)
    patch = green_checkout.green_patch(green)
    tree = green_checkout.green_tree(green)

    assert first == green_checkout.changed_paths(green) == ["thomas/core/widget.py"]
    assert "VALUE = 2" in patch and tree == green_checkout.green_tree(green)
    assert len(stages) == 1


def test_a_write_between_reads_is_staged(green: green_checkout.Green, stages: list[str]) -> None:
    green_checkout.changed_paths(green)
    (green.work / "README.md").write_text("changed\n", encoding="utf-8")

    assert "README.md" in green_checkout.changed_paths(green)
    assert len(stages) == 2


def test_a_write_while_git_stages_is_not_taken_as_staged(
    green: green_checkout.Green, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = green_checkout._stage_everything
    late = green.work / "late.txt"

    def staged_then_written(target: green_checkout.Green) -> None:
        original(target)
        if not late.exists():
            late.write_text("written while git staged\n", encoding="utf-8")

    monkeypatch.setattr(green_checkout, "_stage_everything", staged_then_written)
    assert "late.txt" not in green_checkout.changed_paths(green)
    assert "late.txt" in green_checkout.changed_paths(green), "the next read stages again and sees it"


def test_an_index_another_command_changed_is_staged_again(green: green_checkout.Green, stages: list[str]) -> None:
    green_checkout.changed_paths(green)
    green_checkout.git(green, "reset", "-q", green.base)  # the index is the base again; the file is still changed

    assert green_checkout.changed_paths(green) == ["thomas/core/widget.py"]
    assert len(stages) == 2
