"""Verification must not report evidence it never gathered.

For every task family except `code`, the verification gate was:

    def _generic_checker(work_dir, result_text):
        _ = work_dir
        return VerificationResult(bool(result_text), "general", "deliverable present", ("present",))

The workspace is discarded on the first line. A task passed because the worker
had said something -- any non-empty string. And it reported "deliverable
present" under a check named "present", language that reads like a file was
found when nothing had been looked at.

`run_ruff_check`, directly above it in the same module, already does this
honestly: it marks itself "skipped" when it cannot run. The module docstring
promises "executable proof rather than LLM judgment".
"""

from __future__ import annotations

from thomas.marketplace.orchestrator.verification import _generic_checker


def test_it_names_the_files_it_found(tmp_path) -> None:
    (tmp_path / "report.md").write_text("# findings", encoding="utf-8")
    (tmp_path / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")

    result = _generic_checker(str(tmp_path), "I wrote the report.")

    assert result.passed
    assert result.checks == ("files_present",)
    assert "report.md" in result.evidence and "data.csv" in result.evidence


def test_text_with_no_files_is_named_text_only(tmp_path) -> None:
    """The rubber stamp. It still passes -- for a question answered in prose the
    text IS the deliverable -- but it no longer borrows the word "present"."""
    result = _generic_checker(str(tmp_path), "Here is the answer: 42.")

    assert result.passed
    assert result.checks == ("text_only",)
    # "holds no files", not "inspected none": it looked and found nothing, which
    # is the opposite of the old behaviour where the workspace was discarded
    # unread. Describing it as uninspected would credit the fix to the bug.
    assert "the workspace holds no files" in result.evidence
    assert "inspected" not in result.evidence
    assert "present" not in result.evidence


def test_nothing_at_all_does_not_pass(tmp_path) -> None:
    result = _generic_checker(str(tmp_path), "")

    assert not result.passed
    assert result.checks == ("empty",)


def test_a_workspace_under_a_dot_directory_is_still_read(tmp_path) -> None:
    """Thomas keeps every workspace under ~/.thomas. Filtering hidden entries on
    the absolute path would discard all of them -- the mistake that emptied four
    other scans in this codebase."""
    root = tmp_path / ".thomas" / "workspaces" / "run-1"
    root.mkdir(parents=True)
    (root / "report.md").write_text("# real output", encoding="utf-8")

    result = _generic_checker(str(root), "done")

    assert result.checks == ("files_present",)
    assert "report.md" in result.evidence


def test_hidden_files_inside_the_workspace_are_not_counted_as_deliverables(tmp_path) -> None:
    """A lock file or a cache is not the work."""
    (tmp_path / ".cache").mkdir()
    (tmp_path / ".cache" / "junk").write_text("noise", encoding="utf-8")

    result = _generic_checker(str(tmp_path), "done")

    assert result.checks == ("text_only",)


def test_a_missing_workspace_falls_back_to_the_text(tmp_path) -> None:
    """Must not raise on a path that is not there."""
    result = _generic_checker(str(tmp_path / "gone"), "answered")

    assert result.passed
    assert result.checks == ("text_only",)


def test_no_work_dir_at_all_is_handled(tmp_path) -> None:
    result = _generic_checker("", "answered")

    assert result.checks == ("text_only",)
