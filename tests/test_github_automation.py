from __future__ import annotations

from thomas.integrations.github_automation import (
    normalize_ci_status_event,
    normalize_issue_to_task,
    summarize_pr_risk,
)


def test_normalize_issue_to_task_priority_and_state() -> None:
    issue = {
        "number": 12,
        "title": "Patch auth bypass",
        "body": "Security hotfix",
        "state": "closed",
        "html_url": "https://github.com/acme/thomas/issues/12",
        "repository": {"full_name": "acme/thomas"},
        "labels": [{"name": "security"}],
        "assignees": [{"login": "dev1"}],
    }
    task = normalize_issue_to_task(issue)
    assert task["source"] == "github_issue"
    assert task["priority"] == "high"
    assert task["status"] == "done"


def test_summarize_pr_risk_marks_sensitive_paths() -> None:
    pr = {"title": "Touch auth + billing", "draft": False}
    files = [
        {"filename": "thomas/server/routes/auth.py", "additions": 200, "deletions": 50},
        {"filename": "thomas/server/routes/billing.py", "additions": 150, "deletions": 25},
        {"filename": "thomas/core/config.py", "additions": 10, "deletions": 3},
    ]
    risk = summarize_pr_risk(pr, files)
    payload = risk.to_dict()
    assert payload["changed_files"] == 3
    assert payload["total_changes"] == 438
    assert payload["score"] > 0
    assert payload["level"] in {"medium", "high"}
    assert len(payload["sensitive_files"]) >= 2


def test_normalize_ci_status_event_workflow_run() -> None:
    payload = {
        "action": "completed",
        "repository": {"full_name": "acme/thomas"},
        "workflow_run": {
            "name": "CI",
            "status": "completed",
            "conclusion": "failure",
            "html_url": "https://example.test/run/1",
            "head_sha": "abc",
            "run_number": 123,
        },
    }
    status = normalize_ci_status_event(payload)
    assert status["kind"] == "workflow_run"
    assert status["repo"] == "acme/thomas"
    assert status["conclusion"] == "failure"
    assert status["run_number"] == 123
