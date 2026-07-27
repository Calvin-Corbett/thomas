"""Structured worker-result and observed-file contracts."""

from __future__ import annotations

from pathlib import Path

from thomas.server.chat_delegation_deliverable import (
    _artifacts_from_created,
    _build_result_summary,
    _resolve_created,
    _snapshot_workspace_files,
    _workspace_mtimes,
)
from thomas.server.chat_delegation_result_policy import worker_text_is_confirmed_answer


def test_workspace_snapshot_lists_real_files_only(tmp_path: Path) -> None:
    (tmp_path / "livecheck.txt").write_text("hi", encoding="utf-8")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "index.html").write_text("<html>", encoding="utf-8")
    (tmp_path / ".hidden").write_text("x", encoding="utf-8")

    files = _snapshot_workspace_files(tmp_path)
    assert "livecheck.txt" in files
    assert "sub/index.html" in files
    assert ".hidden" not in files


def test_workspace_mtimes_prunes_runtime_and_dependency_trees(tmp_path: Path) -> None:
    (tmp_path / "thomas").mkdir()
    (tmp_path / "thomas" / "server.py").write_text("print('ok')", encoding="utf-8")
    (tmp_path / "node_modules" / "pkg").mkdir(parents=True)
    (tmp_path / "node_modules" / "pkg" / "index.js").write_text("heavy", encoding="utf-8")

    mtimes = _workspace_mtimes(tmp_path, ignored_parts=frozenset({"node_modules"}))

    assert "thomas/server.py" in mtimes
    assert "node_modules/pkg/index.js" not in mtimes


def test_result_summary_preserves_model_answer_without_prompt_classification() -> None:
    answer = "## Result\n\nThe model-authored answer stays intact."
    summaries = {
        _build_result_summary([answer], [], [], prompt=prompt)
        for prompt in ("make a graph", "make a game", "send an email", "create a PDF")
    }

    assert summaries == {answer}


def test_result_summary_leads_with_actual_created_files() -> None:
    summary = _build_result_summary(["Finished."], ["fs.write_file"], ["nested/report.md"])

    assert summary.startswith("Created nested/report.md.")
    assert _artifacts_from_created(["nested/report.md"]) == [
        {
            "path": "nested/report.md",
            "name": "report.md",
            "type": "md",
            "actions": ["open", "download"],
        }
    ]


def test_failed_tool_receipt_is_presented_structurally() -> None:
    summary = _build_result_summary(
        ["The worker's explanation."],
        ["email.send"],
        [],
        failed_tools=["email.send"],
    )

    assert summary.startswith("Tool failures: email.send.")
    assert "The worker's explanation." in summary


def test_worker_done_status_does_not_depend_on_prose_keywords() -> None:
    for text in ("On it.", "Done.", "Here is a detailed answer.", "Production is live."):
        assert worker_text_is_confirmed_answer([text], prompt="arbitrary")
    assert not worker_text_is_confirmed_answer([""], prompt="arbitrary")
    assert not worker_text_is_confirmed_answer(["answer"], failed_tools=["tool.failure"])


def test_resolve_created_uses_only_current_attempt_file_diff(tmp_path: Path) -> None:
    (tmp_path / "old.txt").write_text("old", encoding="utf-8")
    baseline = _workspace_mtimes(tmp_path)
    (tmp_path / "new.txt").write_text("new", encoding="utf-8")

    created = _resolve_created(tmp_path, baseline, ["I created imaginary.pdf"], [])

    assert created == ["new.txt"]
