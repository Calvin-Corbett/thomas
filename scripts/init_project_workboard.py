#!/usr/bin/env python3
"""Bootstrap a project-local workboard layout for a repo."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

try:
    from scripts.workboard_paths import (
        ROOT,
        command_catalog_path_for,
        default_workboard_path,
        problem_dir_for,
        resolve_workboard_path,
        swarm_dir_for,
        task_plan_dir_for,
        worker_log_dir_for,
    )
except ImportError:  # pragma: no cover
    from workboard_paths import (  # type: ignore
        ROOT,
        command_catalog_path_for,
        default_workboard_path,
        problem_dir_for,
        resolve_workboard_path,
        swarm_dir_for,
        task_plan_dir_for,
        worker_log_dir_for,
    )


WORKBOARD_TEMPLATE = """# Project Workboard

## Agent Claims (Active)

- none

## Active Tasks

- none

## Up For Grabs

- none

## Issues / Blockers

- none

## Agent Message Traffic

- none

## Swarm Sessions

- none

## Task Plans

- none

## Task Problems

- none

## Inactive Agents

- none

## Agent Sessions

- none

## Task Specialist Routing

- none

## Supporting Docs (Not Plan Sources)

- none
"""

COMMAND_CATALOG_TEMPLATE = {
    "default": [],
    "task_prefixes": {},
    "tasks": {},
}


def _write_text(path: Path, text: str, *, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: dict[str, object], *, force: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a reusable project-local workboard scaffold.")
    parser.add_argument("--repo-root", default=str(ROOT), help="Repository root for the workboard scaffold.")
    parser.add_argument(
        "--workboard",
        default="",
        help="Optional workboard path. Defaults to the repo-local .thomas/WORKBOARD.md layout.",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing scaffold files.")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    repo_root = Path(str(args.repo_root)).expanduser()
    if not repo_root.is_absolute():
        repo_root = (ROOT / repo_root).resolve()
    else:
        repo_root = repo_root.resolve()

    workboard_path = resolve_workboard_path(
        str(args.workboard or default_workboard_path(repo_root)),
        repo_root=repo_root,
    )
    workboard_dir = workboard_path.parent
    task_dir = task_plan_dir_for(workboard_path, repo_root=repo_root)
    problem_dir = problem_dir_for(workboard_path, repo_root=repo_root)
    swarm_dir = swarm_dir_for(workboard_path, repo_root=repo_root)
    coordination_dir = workboard_dir / "coordination"
    worker_dir = worker_log_dir_for(workboard_path, repo_root=repo_root)
    catalog_path = command_catalog_path_for(workboard_path, repo_root=repo_root)

    for directory in (workboard_dir, task_dir, problem_dir, swarm_dir, coordination_dir, worker_dir):
        directory.mkdir(parents=True, exist_ok=True)

    _write_text(workboard_path, WORKBOARD_TEMPLATE.rstrip() + "\n", force=bool(args.force))
    _write_json(catalog_path, COMMAND_CATALOG_TEMPLATE, force=bool(args.force))

    payload = {
        "ok": True,
        "repo_root": str(repo_root),
        "workboard": str(workboard_path),
        "workboard_dir": str(workboard_dir),
        "tasks_dir": str(task_dir),
        "problems_dir": str(problem_dir),
        "swarm_dir": str(swarm_dir),
        "coordination_dir": str(coordination_dir),
        "workers_dir": str(worker_dir),
        "command_catalog": str(catalog_path),
        "force": bool(args.force),
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Project workboard init: PASS")
        print(f"- workboard: {workboard_path}")
        print(f"- command catalog: {catalog_path}")
        print(f"- scaffold root: {workboard_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
