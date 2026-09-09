"""The failure report must describe the product, not the test suite."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from thomas.server import issue_ledger
from thomas.server.issue_ledger import _issues_path, recent_issues, record_issue


def test_the_suite_does_not_append_to_the_real_ledger() -> None:
    """The contamination this prevents.

    The ledger is what Thomas self-reviews from. The suite drives the same
    worker code paths with fixture prompts, so every run appended entries like
    "do the thing" and "Answer with verified model attribution." to the real
    file — about two thirds of a week's entries were fixtures, and the report
    meant to say "what broke today" was largely reporting that tests ran.
    """
    real = _issues_path(None)
    before = real.read_bytes() if real.exists() else b""

    record_issue(surface="chat-worker", kind="worker_failed", message="do the thing")

    after = real.read_bytes() if real.exists() else b""
    assert after == before, "a test just wrote into the production issue ledger"


def test_a_test_that_targets_a_tmp_ledger_still_works(tmp_path: Path) -> None:
    """The guard is narrow: only the real repo's file is protected, so a test
    exercising the ledger on purpose is unaffected."""
    record_issue(surface="chat-ui", kind="friction", message="deliberate", repo_root=tmp_path)

    rows = recent_issues(limit=10, repo_root=tmp_path)

    assert [r["message"] for r in rows] == ["deliberate"]


def test_the_app_still_records_when_not_under_pytest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Outside the suite nothing is suppressed — the whole point is that real
    failures are still captured."""
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    monkeypatch.setattr(issue_ledger, "_REPO_ROOT", tmp_path)

    record_issue(surface="chat-worker", kind="worker_failed", message="a real failure")

    written = json.loads((tmp_path / "runtime" / "logs" / "issues.jsonl").read_text(encoding="utf-8").strip())
    assert written["message"] == "a real failure"


def test_the_guard_keys_on_the_pytest_marker() -> None:
    """Documents the mechanism so it is obvious why this stops working if the
    env var ever goes away."""
    assert os.environ.get("PYTEST_CURRENT_TEST"), "expected to be running under pytest"
    assert issue_ledger._is_test_run_writing_to_the_real_ledger(_issues_path(None))
    assert not issue_ledger._is_test_run_writing_to_the_real_ledger(Path("/tmp/elsewhere/issues.jsonl"))
