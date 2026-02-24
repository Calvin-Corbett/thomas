from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping, Sequence


def _safe_string(value: Any) -> str:
    return str(value or "").strip()


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return int(default)


def _to_list(values: Any) -> list[Any]:
    if isinstance(values, list):
        return list(values)
    if isinstance(values, tuple):
        return list(values)
    return []


def _repo_full_name(payload: Mapping[str, Any]) -> str:
    repo = payload.get("repository")
    if isinstance(repo, Mapping):
        return _safe_string(repo.get("full_name"))
    return ""


def normalize_issue_to_task(issue: Mapping[str, Any]) -> dict[str, Any]:
    number = _to_int(issue.get("number"), 0)
    repo = _repo_full_name(issue)
    labels = [
        _safe_string(item.get("name"))
        for item in _to_list(issue.get("labels"))
        if isinstance(item, Mapping) and _safe_string(item.get("name"))
    ]
    assignees = [
        _safe_string(item.get("login"))
        for item in _to_list(issue.get("assignees"))
        if isinstance(item, Mapping) and _safe_string(item.get("login"))
    ]
    state = _safe_string(issue.get("state")).lower() or "open"
    priority = "medium"
    labels_l = {item.lower() for item in labels}
    if {"security", "urgent", "p0", "sev1", "critical"} & labels_l:
        priority = "high"
    elif {"docs", "chore", "nice-to-have", "p3"} & labels_l:
        priority = "low"
    return {
        "source": "github_issue",
        "source_id": f"{repo}#{number}" if repo and number > 0 else "",
        "repo": repo,
        "issue_number": number,
        "title": _safe_string(issue.get("title")),
        "description": _safe_string(issue.get("body")),
        "status": "done" if state == "closed" else "open",
        "priority": priority,
        "labels": labels,
        "assignees": assignees,
        "url": _safe_string(issue.get("html_url")),
        "created_at": _safe_string(issue.get("created_at")),
        "updated_at": _safe_string(issue.get("updated_at")),
    }


_SENSITIVE_FILE_RE = re.compile(
    r"(auth|oauth|token|secret|permission|policy|acl|rbac|payment|billing|invoice|"
    r"database|migration|schema|encryption|crypto|vault|webhook|ci|release|deploy)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PullRequestRisk:
    level: str
    score: int
    summary: str
    changed_files: int
    additions: int
    deletions: int
    total_changes: int
    sensitive_files: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level,
            "score": int(self.score),
            "summary": self.summary,
            "changed_files": int(self.changed_files),
            "additions": int(self.additions),
            "deletions": int(self.deletions),
            "total_changes": int(self.total_changes),
            "sensitive_files": list(self.sensitive_files),
        }


def summarize_pr_risk(pr: Mapping[str, Any], files: Sequence[Mapping[str, Any]]) -> PullRequestRisk:
    changed_files = len(list(files or []))
    additions = sum(_to_int(item.get("additions"), 0) for item in files if isinstance(item, Mapping))
    deletions = sum(_to_int(item.get("deletions"), 0) for item in files if isinstance(item, Mapping))
    total_changes = additions + deletions

    sensitive_files: list[str] = []
    for item in files:
        if not isinstance(item, Mapping):
            continue
        filename = _safe_string(item.get("filename"))
        if filename and _SENSITIVE_FILE_RE.search(filename):
            sensitive_files.append(filename)

    score = 0
    score += min(40, changed_files * 2)
    score += min(40, int(total_changes / 40))
    score += min(20, len(sensitive_files) * 8)

    draft = bool(pr.get("draft", False))
    if draft:
        score = max(0, score - 5)

    if changed_files >= 40 or total_changes >= 2000 or len(sensitive_files) >= 3:
        level = "high"
    elif changed_files >= 12 or total_changes >= 500 or len(sensitive_files) >= 1:
        level = "medium"
    else:
        level = "low"

    summary_bits = [
        f"{changed_files} files",
        f"{total_changes} lines",
    ]
    if sensitive_files:
        summary_bits.append(f"{len(sensitive_files)} sensitive-path touches")
    if draft:
        summary_bits.append("draft")
    summary = ", ".join(summary_bits)

    return PullRequestRisk(
        level=level,
        score=int(min(100, max(0, score))),
        summary=summary,
        changed_files=changed_files,
        additions=additions,
        deletions=deletions,
        total_changes=total_changes,
        sensitive_files=sensitive_files[:25],
    )


def normalize_ci_status_event(payload: Mapping[str, Any]) -> dict[str, Any]:
    repo = _repo_full_name(payload)
    action = _safe_string(payload.get("action"))
    workflow_run = payload.get("workflow_run")
    check_suite = payload.get("check_suite")
    check_run = payload.get("check_run")

    if isinstance(workflow_run, Mapping):
        return {
            "kind": "workflow_run",
            "repo": repo,
            "action": action,
            "status": _safe_string(workflow_run.get("status")),
            "conclusion": _safe_string(workflow_run.get("conclusion")),
            "name": _safe_string(workflow_run.get("name")),
            "html_url": _safe_string(workflow_run.get("html_url")),
            "head_sha": _safe_string(workflow_run.get("head_sha")),
            "run_number": _to_int(workflow_run.get("run_number"), 0),
        }
    if isinstance(check_suite, Mapping):
        return {
            "kind": "check_suite",
            "repo": repo,
            "action": action,
            "status": _safe_string(check_suite.get("status")),
            "conclusion": _safe_string(check_suite.get("conclusion")),
            "head_sha": _safe_string(check_suite.get("head_sha")),
            "html_url": _safe_string(check_suite.get("html_url")),
        }
    if isinstance(check_run, Mapping):
        return {
            "kind": "check_run",
            "repo": repo,
            "action": action,
            "status": _safe_string(check_run.get("status")),
            "conclusion": _safe_string(check_run.get("conclusion")),
            "name": _safe_string(check_run.get("name")),
            "html_url": _safe_string(check_run.get("html_url")),
            "head_sha": _safe_string(check_run.get("head_sha")),
        }
    return {
        "kind": "unknown",
        "repo": repo,
        "action": action,
        "status": "",
        "conclusion": "",
        "name": "",
        "html_url": "",
        "head_sha": "",
    }


def _github_headers(token: str) -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "thomas-github-automation",
    }
    token_value = _safe_string(token)
    if token_value:
        headers["Authorization"] = f"Bearer {token_value}"
    return headers


def fetch_github_json(*, base_url: str, path: str, token: str, timeout_s: float = 20.0) -> Any:
    endpoint = _safe_string(base_url).rstrip("/") + "/" + _safe_string(path).lstrip("/")
    req = urllib.request.Request(endpoint, headers=_github_headers(token))
    with urllib.request.urlopen(req, timeout=max(1.0, float(timeout_s))) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    return json.loads(raw)


def fetch_issue(*, base_url: str, repo: str, issue_number: int, token: str, timeout_s: float = 20.0) -> dict[str, Any]:
    data = fetch_github_json(
        base_url=base_url,
        path=f"/repos/{_safe_string(repo)}/issues/{int(issue_number)}",
        token=token,
        timeout_s=timeout_s,
    )
    if not isinstance(data, Mapping):
        raise RuntimeError("GitHub issue payload is not an object.")
    return dict(data)


def fetch_pull_request(*, base_url: str, repo: str, pr_number: int, token: str, timeout_s: float = 20.0) -> dict[str, Any]:
    data = fetch_github_json(
        base_url=base_url,
        path=f"/repos/{_safe_string(repo)}/pulls/{int(pr_number)}",
        token=token,
        timeout_s=timeout_s,
    )
    if not isinstance(data, Mapping):
        raise RuntimeError("GitHub PR payload is not an object.")
    return dict(data)


def fetch_pull_request_files(
    *,
    base_url: str,
    repo: str,
    pr_number: int,
    token: str,
    timeout_s: float = 20.0,
) -> list[dict[str, Any]]:
    data = fetch_github_json(
        base_url=base_url,
        path=f"/repos/{_safe_string(repo)}/pulls/{int(pr_number)}/files?per_page=100",
        token=token,
        timeout_s=timeout_s,
    )
    if not isinstance(data, list):
        raise RuntimeError("GitHub PR files payload is not an array.")
    out: list[dict[str, Any]] = []
    for item in data:
        if isinstance(item, Mapping):
            out.append(dict(item))
    return out

