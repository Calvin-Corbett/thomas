from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from thomas.cli.commands.webhooks import webhooks


def _write_event(path: Path, payload: dict) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_webhooks_github_issue_sync_from_event_file(tmp_path: Path) -> None:
    event_file = _write_event(
        tmp_path / "issue.json",
        {
            "action": "opened",
            "repository": {"full_name": "acme/thomas"},
            "issue": {
                "number": 42,
                "title": "Fix auth edge case",
                "body": "Need to harden token parsing.",
                "state": "open",
                "html_url": "https://github.com/acme/thomas/issues/42",
                "labels": [{"name": "security"}],
                "assignees": [{"login": "alice"}],
            },
        },
    )
    runner = CliRunner()
    result = runner.invoke(webhooks, ["github-issue-sync", "--event-file", str(event_file), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    task = payload["task"]
    assert task["source"] == "github_issue"
    assert task["source_id"] == "acme/thomas#42"
    assert task["priority"] == "high"
    assert task["status"] == "open"
    assert "security" in task["labels"]


def test_webhooks_github_pr_risk_scan_from_event_file(tmp_path: Path) -> None:
    event_file = _write_event(
        tmp_path / "pr.json",
        {
            "pull_request": {
                "number": 7,
                "title": "Refactor auth + billing checks",
                "html_url": "https://github.com/acme/thomas/pull/7",
                "draft": False,
            },
            "files": [
                {"filename": "thomas/server/routes/auth.py", "additions": 250, "deletions": 40},
                {"filename": "thomas/server/routes/billing.py", "additions": 160, "deletions": 20},
                {"filename": "README.md", "additions": 10, "deletions": 2},
            ],
        },
    )
    runner = CliRunner()
    result = runner.invoke(webhooks, ["github-pr-risk-scan", "--event-file", str(event_file), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    risk = payload["risk"]
    assert payload["pull_request"]["number"] == 7
    assert risk["changed_files"] == 3
    assert risk["total_changes"] == 482
    assert risk["level"] in {"medium", "high"}
    assert risk["score"] >= 1


def test_webhooks_github_ci_status_from_event_file(tmp_path: Path) -> None:
    event_file = _write_event(
        tmp_path / "ci.json",
        {
            "action": "completed",
            "repository": {"full_name": "acme/thomas"},
            "workflow_run": {
                "name": "CI",
                "status": "completed",
                "conclusion": "success",
                "html_url": "https://github.com/acme/thomas/actions/runs/1",
                "head_sha": "abc123",
                "run_number": 99,
            },
        },
    )
    runner = CliRunner()
    result = runner.invoke(webhooks, ["github-ci-status", "--event-file", str(event_file), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    status = payload["status"]
    assert status["kind"] == "workflow_run"
    assert status["repo"] == "acme/thomas"
    assert status["status"] == "completed"
    assert status["conclusion"] == "success"
