#!/usr/bin/env python3
"""Shared path helpers for project-local workboard layouts."""

from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKBOARD_FILENAME = "WORKBOARD.md"
PROJECT_DIRNAME = ".thomas"
PROJECT_WORKBOARD_REL = Path(PROJECT_DIRNAME) / WORKBOARD_FILENAME
LEGACY_WORKBOARD_REL = Path("plans") / "thomas" / WORKBOARD_FILENAME
LEGACY_COORDINATION_REL = Path("runtime") / "coordination"
LEGACY_WORKER_LOG_REL = Path("runtime") / "workers"
WORKBOARD_ENV_KEYS: tuple[str, ...] = ("THOMAS_WORKBOARD_PATH", "WORKBOARD_PATH")


def _coerce_repo_root(repo_root: Path | str | None = None) -> Path:
    if repo_root is None:
        return ROOT
    candidate = Path(str(repo_root)).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (ROOT / candidate).resolve()


def _resolve_under_root(value: str | Path, *, repo_root: Path) -> Path:
    candidate = Path(str(value)).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (repo_root / candidate).resolve()


def default_workboard_path(repo_root: Path | str | None = None) -> Path:
    root = _coerce_repo_root(repo_root)
    for key in WORKBOARD_ENV_KEYS:
        raw = str(os.getenv(key) or "").strip()
        if raw:
            return _resolve_under_root(raw, repo_root=root)

    project_workboard = (root / PROJECT_WORKBOARD_REL).resolve()
    legacy_workboard = (root / LEGACY_WORKBOARD_REL).resolve()
    if project_workboard.exists():
        return project_workboard
    if legacy_workboard.exists():
        return legacy_workboard
    return project_workboard


def resolve_workboard_path(
    workboard_path: str | Path | None = None,
    *,
    repo_root: Path | str | None = None,
) -> Path:
    root = _coerce_repo_root(repo_root)
    if workboard_path is None or not str(workboard_path).strip():
        return default_workboard_path(root)
    return _resolve_under_root(workboard_path, repo_root=root)


def is_legacy_workboard_path(
    workboard_path: str | Path | None = None,
    *,
    repo_root: Path | str | None = None,
) -> bool:
    root = _coerce_repo_root(repo_root)
    resolved = resolve_workboard_path(workboard_path, repo_root=root)
    return resolved == (root / LEGACY_WORKBOARD_REL).resolve()


def repo_root_for(
    workboard_path: str | Path | None = None,
    *,
    repo_root: Path | str | None = None,
) -> Path:
    root = _coerce_repo_root(repo_root)
    resolved = resolve_workboard_path(workboard_path, repo_root=root)
    if is_legacy_workboard_path(resolved, repo_root=root):
        return root
    if resolved.parent.name == PROJECT_DIRNAME:
        return resolved.parent.parent.resolve()
    try:
        resolved.relative_to(root)
        return root
    except ValueError:
        return resolved.parent.resolve()


def repo_relative_or_absolute(
    path: Path,
    *,
    repo_root: Path | str | None = None,
) -> str:
    root = _coerce_repo_root(repo_root)
    resolved = path.resolve()
    try:
        return resolved.relative_to(root).as_posix()
    except ValueError:
        return str(resolved)


def workboard_dir_for(
    workboard_path: str | Path | None = None,
    *,
    repo_root: Path | str | None = None,
) -> Path:
    return resolve_workboard_path(workboard_path, repo_root=repo_root).parent


def coordination_dir_for(
    workboard_path: str | Path | None = None,
    *,
    repo_root: Path | str | None = None,
) -> Path:
    root = _coerce_repo_root(repo_root)
    if is_legacy_workboard_path(workboard_path, repo_root=root):
        return (root / LEGACY_COORDINATION_REL).resolve()
    return workboard_dir_for(workboard_path, repo_root=root) / "coordination"


def worker_log_dir_for(
    workboard_path: str | Path | None = None,
    *,
    repo_root: Path | str | None = None,
) -> Path:
    root = _coerce_repo_root(repo_root)
    if is_legacy_workboard_path(workboard_path, repo_root=root):
        return (root / LEGACY_WORKER_LOG_REL).resolve()
    return workboard_dir_for(workboard_path, repo_root=root) / "workers"


def command_catalog_path_for(
    workboard_path: str | Path | None = None,
    *,
    repo_root: Path | str | None = None,
) -> Path:
    return workboard_dir_for(workboard_path, repo_root=repo_root) / "worker_command_catalog.json"


def swarm_dir_for(
    workboard_path: str | Path | None = None,
    *,
    repo_root: Path | str | None = None,
) -> Path:
    return workboard_dir_for(workboard_path, repo_root=repo_root) / "swarm"


def task_plan_dir_for(
    workboard_path: str | Path | None = None,
    *,
    repo_root: Path | str | None = None,
) -> Path:
    return workboard_dir_for(workboard_path, repo_root=repo_root) / "tasks"


def problem_dir_for(
    workboard_path: str | Path | None = None,
    *,
    repo_root: Path | str | None = None,
) -> Path:
    return workboard_dir_for(workboard_path, repo_root=repo_root) / "problems"


def task_plan_root_token_for(
    workboard_path: str | Path | None = None,
    *,
    repo_root: Path | str | None = None,
) -> str:
    root = _coerce_repo_root(repo_root)
    return repo_relative_or_absolute(task_plan_dir_for(workboard_path, repo_root=root), repo_root=root)


def problem_root_token_for(
    workboard_path: str | Path | None = None,
    *,
    repo_root: Path | str | None = None,
) -> str:
    root = _coerce_repo_root(repo_root)
    return repo_relative_or_absolute(problem_dir_for(workboard_path, repo_root=root), repo_root=root)


def temp_task_creator_scope_for(
    workboard_path: str | Path | None = None,
    *,
    repo_root: Path | str | None = None,
) -> str:
    root = _coerce_repo_root(repo_root)
    return repo_relative_or_absolute(
        coordination_dir_for(workboard_path, repo_root=root) / "temp-task-creator",
        repo_root=root,
    )
