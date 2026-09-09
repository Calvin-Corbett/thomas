"""Execution helpers for repo-scoped research experiments."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

from .research_models import ResearchProgramConfig, ResearchRunRecord, compare_metric, utc_now_iso
from .research_store import list_research_runs, resolve_repo_root, save_research_run


def _normalize_rel_path(path_value: str) -> str:
    return str(path_value or "").replace("\\", "/").strip().lstrip("./")


def _normalize_scope(scopes: list[str]) -> list[str]:
    rows: list[str] = []
    for item in scopes:
        cleaned = _normalize_rel_path(item).strip("/")
        if cleaned:
            rows.append(cleaned)
    return rows


def _within_editable_scope(path_value: str, editable_paths: list[str]) -> bool:
    if not editable_paths:
        return True
    normalized_path = _normalize_rel_path(path_value)
    if not normalized_path:
        return False
    for allowed in _normalize_scope(editable_paths):
        if normalized_path == allowed or normalized_path.startswith(f"{allowed}/"):
            return True
    return False


def _best_previous_metric(runs: list[ResearchRunRecord], goal: str) -> float | None:
    values = [row.metric_value for row in runs if row.status == "completed" and row.metric_value is not None]
    if not values:
        return None
    if goal == "minimize":
        return min(float(value) for value in values)
    return max(float(value) for value in values)


def _build_run_id(label: str) -> str:
    safe_label = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(label or "").strip()).strip("-")
    safe_label = "-".join(part for part in safe_label.split("-") if part)[:40] or "run"
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    return f"{stamp}-{safe_label}"


def _run_git(repo_root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", *args],
            cwd=str(repo_root),
            text=True,
            capture_output=True,
            check=False,
        )
    except FileNotFoundError:
        return None


def _git_head(repo_root: Path) -> str:
    proc = _run_git(repo_root, "rev-parse", "HEAD")
    if not proc or proc.returncode != 0:
        return ""
    return str(proc.stdout or "").strip()


def _git_changed_files(repo_root: Path) -> list[str]:
    proc = _run_git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    if not proc or proc.returncode != 0:
        return []
    rows: list[str] = []
    for raw_line in str(proc.stdout or "").splitlines():
        body = raw_line[3:] if len(raw_line) >= 4 else raw_line
        candidate = body.split(" -> ", 1)[-1].strip()
        normalized = _normalize_rel_path(candidate)
        if normalized:
            rows.append(normalized)
    deduped: list[str] = []
    seen: set[str] = set()
    for item in rows:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _git_diff_patch(repo_root: Path) -> str:
    proc = _run_git(repo_root, "diff", "--binary", "--relative", "HEAD", "--")
    if not proc or proc.returncode != 0:
        return ""
    return str(proc.stdout or "")


def _read_metric_from_json(repo_root: Path, metric_path: str, metric_key: str) -> float:
    target = (repo_root / metric_path).resolve()
    payload = json.loads(target.read_text(encoding="utf-8"))
    current = payload
    for part in [segment for segment in str(metric_key or "").split(".") if segment]:
        if not isinstance(current, dict) or part not in current:
            raise KeyError(f"metric key not found: {metric_key}")
        current = current[part]
    return float(current)


def _command_argv(command_text: str) -> list[str]:
    if os.name == "nt":
        shell = os.environ.get("COMSPEC") or "cmd.exe"
        return [shell, "/d", "/s", "/c", command_text]
    return ["/bin/sh", "-lc", command_text]


def _compute_verdict(
    *,
    status: str,
    metric_value: float | None,
    frontier_value: float | None,
    best_previous_value: float | None,
    goal: str,
) -> str:
    if status == "blocked":
        return "blocked_scope"
    if status == "failed":
        return "evaluation_failed"
    if metric_value is None:
        return "no_metric"
    if frontier_value is None:
        return "candidate_seed"
    if compare_metric(metric_value, frontier_value, goal):
        return "candidate_promote"
    if metric_value == frontier_value:
        return "ties_frontier"
    if best_previous_value is not None and compare_metric(metric_value, best_previous_value, goal):
        return "new_best_unpromoted"
    return "below_frontier"


def execute_research_run(
    repo_root: str | Path | None,
    config: ResearchProgramConfig,
    *,
    label: str = "",
    metric_value: float | None = None,
    eval_cmd_override: str = "",
    notes: str = "",
) -> ResearchRunRecord:
    """Run or record a research experiment and persist its artifact."""
    resolved_root = resolve_repo_root(repo_root)
    run_label = str(label or "").strip() or "candidate"
    run_id = _build_run_id(run_label)
    changed_files = _git_changed_files(resolved_root)
    disallowed_files = [path for path in changed_files if not _within_editable_scope(path, config.editable_paths)]
    prior_runs = list_research_runs(resolved_root)
    best_previous_value = _best_previous_metric(prior_runs, config.metric_goal)
    frontier_value = config.baseline_value if config.baseline_value is not None else best_previous_value

    stdout_text = ""
    stderr_text = ""
    patch_text = _git_diff_patch(resolved_root)
    duration_seconds: float | None = None
    exit_code: int | None = None
    status = "completed"
    selected_command = str(eval_cmd_override or config.evaluation_command or "").strip()

    if disallowed_files:
        status = "blocked"
    elif metric_value is None and selected_command:
        argv = _command_argv(selected_command)
        started = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                cwd=str(resolved_root),
                text=True,
                capture_output=True,
                timeout=max(1, int(config.runtime_budget_seconds or 300)),
                check=False,
            )
            duration_seconds = time.monotonic() - started
            exit_code = int(proc.returncode)
            stdout_text = str(proc.stdout or "")
            stderr_text = str(proc.stderr or "")
            if proc.returncode != 0:
                status = "failed"
            elif config.metric_path:
                metric_value = _read_metric_from_json(resolved_root, config.metric_path, config.metric_key)
        except subprocess.TimeoutExpired as exc:
            status = "failed"
            duration_seconds = time.monotonic() - started
            stdout_text = str(exc.stdout or "")
            stderr_text = str(exc.stderr or "")
            exit_code = None
        except (FileNotFoundError, PermissionError, json.JSONDecodeError, KeyError, OSError, ValueError) as exc:
            status = "failed"
            duration_seconds = time.monotonic() - started
            stderr_text = f"{type(exc).__name__}: {exc}"
            exit_code = None

    verdict = _compute_verdict(
        status=status,
        metric_value=metric_value,
        frontier_value=frontier_value,
        best_previous_value=best_previous_value,
        goal=config.metric_goal,
    )
    run = ResearchRunRecord(
        run_id=run_id,
        created_at=utc_now_iso(),
        label=run_label,
        status=status,
        metric_name=config.metric_name,
        metric_goal=config.metric_goal,
        metric_value=metric_value,
        baseline_value=config.baseline_value,
        frontier_value=frontier_value,
        best_previous_value=best_previous_value,
        verdict=verdict,
        decision="pending",
        repo_root=str(resolved_root),
        evaluation_command=selected_command,
        metric_path=config.metric_path,
        metric_key=config.metric_key,
        editable_paths=list(config.editable_paths),
        changed_files=changed_files,
        disallowed_files=disallowed_files,
        runtime_budget_seconds=int(config.runtime_budget_seconds),
        duration_seconds=duration_seconds,
        exit_code=exit_code,
        git_head=_git_head(resolved_root),
        notes=notes,
    )
    save_research_run(
        resolved_root,
        run,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        patch_text=patch_text,
    )
    return run
