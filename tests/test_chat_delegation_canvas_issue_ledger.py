"""Canvas failures must reach the issue ledger so the self-review can see them.

Before this, `_start_canvas_worker_delegation` called `fail_execution` on canvas
failure without ever recording an issue, so `/api/issues` and `/api/self-review`
were blind to the exact class of failure observed live (a chart that renders then
dies in review -> `canvas_failed`).
"""

from __future__ import annotations

import tempfile

from thomas.server.chat_delegation import _record_canvas_issue
from thomas.server.issue_ledger import recent_issues


def test_record_canvas_issue_writes_to_ledger() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _record_canvas_issue("exec-abc", "make me a bar chart of fuel costs", "canvas_failed", tmp)
        rows = recent_issues(limit=10, repo_root=tmp)
        assert len(rows) == 1
        row = rows[0]
        assert row["surface"] == "chat-worker"
        assert row["kind"] == "canvas_failed"
        assert row["context"]["execution_id"] == "exec-abc"
        assert row["context"]["blocker"] == "canvas_failed"
        assert "fuel costs" in row["context"]["task"]


def test_record_canvas_issue_captures_every_blocker() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        _record_canvas_issue("e1", "p", "canvas_failed", tmp)
        _record_canvas_issue("e2", "p", "model_runtime_missing", tmp)
        _record_canvas_issue("e3", "p", "canvas_review_failed", tmp)
        rows = recent_issues(limit=10, repo_root=tmp)
        assert len(rows) == 3
        assert all(r["kind"] == "canvas_failed" for r in rows)
        assert {r["context"]["blocker"] for r in rows} == {
            "canvas_failed",
            "model_runtime_missing",
            "canvas_review_failed",
        }
