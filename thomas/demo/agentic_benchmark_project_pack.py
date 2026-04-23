from __future__ import annotations

import hashlib
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from thomas.demo.agentic_benchmark_core import _read_json, load_agentic_task_pack
from thomas.demo.agentic_benchmark_endurance_runtime import copy_workspace_snapshot

ROOT = Path(__file__).resolve().parents[2]


def load_project_pack(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    base = load_agentic_task_pack(path)
    if str(base.get("type") or "").strip() != "project":
        raise ValueError("Project pack type must be `project`.")
    fixture_path = str(payload.get("fixture_path") or "").strip()
    if not fixture_path:
        raise ValueError("Project pack must define fixture_path.")
    task_fixture_by_id: dict[str, str] = {}
    for raw_task in list(payload.get("tasks") or []):
        if not isinstance(raw_task, dict):
            continue
        task_fixture = str(raw_task.get("fixture_path") or "").strip()
        if task_fixture:
            task_fixture_by_id[str(raw_task.get("id") or "").strip()] = task_fixture
    tasks: list[dict[str, Any]] = []
    for task in list(base.get("tasks") or []):
        task_copy = dict(task)
        task_fixture = task_fixture_by_id.get(str(task_copy.get("id") or "").strip())
        if task_fixture:
            task_copy["fixture_path"] = task_fixture
        tasks.append(task_copy)
    return {
        **base,
        "fixture_path": fixture_path,
        "tasks": tasks,
    }


def resolve_task_fixture_root(task_pack: Mapping[str, Any], task: Mapping[str, Any]) -> Path:
    task_fixture = str(task.get("fixture_path") or task_pack.get("fixture_path") or "").strip()
    candidate = Path(task_fixture)
    if not candidate.is_absolute():
        candidate = (ROOT / candidate).resolve()
    return candidate


def git_in_workspace(workspace_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", "-C", str(workspace_root), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"git {' '.join(args)} failed")
    return proc


def prepare_project_workspace(fixture_root: Path, workspace_root: Path) -> None:
    copy_workspace_snapshot(fixture_root, workspace_root)
    git_in_workspace(workspace_root, "init")
    git_in_workspace(workspace_root, "config", "user.email", "benchmark@example.com")
    git_in_workspace(workspace_root, "config", "user.name", "Benchmark Runner")
    git_in_workspace(workspace_root, "add", "-A")
    git_in_workspace(workspace_root, "commit", "-m", "Initial benchmark fixture")


def snapshot_tree(root: Path) -> dict[str, str]:
    snapshot: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        snapshot[rel] = digest
    return snapshot
