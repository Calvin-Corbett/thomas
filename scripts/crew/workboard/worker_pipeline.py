#!/usr/bin/env python3
"""Command-pipeline execution machinery for the workboard worker loop.

Split out of scripts/crew/workboard/worker.py (which had grown past the
monolith guard's unbaselined 800-line soft limit) so the split has a real
seam: everything here is about resolving which shell commands a task runs
and executing/logging them, with zero dependency back on worker.py's own
loop/CLI code. worker.py imports and re-exports every name defined here
under its original spot, so no external caller needed to change.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class AssignedTask:
    line_no: int
    task_id: str
    scope: str
    summary: str


@dataclass(frozen=True)
class CommandRun:
    command: str
    returncode: int
    elapsed_seconds: float
    timed_out: bool
    stdout: str
    stderr: str


class _SafeFormatDict(dict):
    def __missing__(self, key: str) -> str:  # pragma: no cover - defensive
        return "{" + key + "}"


def _quote_for_shell(value: str) -> str:
    token = str(value or "")
    if os.name == "nt":
        return subprocess.list2cmdline([token])
    return shlex.quote(token)


def _norm(value: str) -> str:
    return str(value or "").strip().lower()


def _sanitize_token(text: str) -> str:
    chars: list[str] = []
    for ch in str(text or "").strip().lower():
        if ch.isalnum():
            chars.append(ch)
        else:
            chars.append("-")
    out = "".join(chars).strip("-")
    while "--" in out:
        out = out.replace("--", "-")
    return out or "worker"


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _coerce_commands(raw: object, *, label: str) -> list[str]:
    out: list[str] = []
    if isinstance(raw, str):
        token = str(raw).strip()
        if token:
            out.append(token)
        return out
    if isinstance(raw, list):
        for idx, item in enumerate(raw, start=1):
            if not isinstance(item, str):
                raise ValueError(f"{label}[{idx}] must be a string command")
            token = str(item).strip()
            if token:
                out.append(token)
        return out
    if raw is None:
        return out
    raise ValueError(f"{label} must be a string or list of strings")


def _load_command_catalog(path: Path | None) -> tuple[bool, dict[str, object]]:
    payload: dict[str, object] = {
        "tasks": {},
        "task_prefixes": [],
        "default": [],
    }
    if path is None:
        return True, payload
    if not path.exists():
        return False, {"error": f"catalog file not found: {path}"}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, {"error": f"failed to parse catalog json: {exc}"}
    if not isinstance(raw, dict):
        return False, {"error": "catalog root must be a JSON object"}

    tasks_raw = raw.get("tasks", {})
    if tasks_raw is None:
        tasks_raw = {}
    if not isinstance(tasks_raw, dict):
        return False, {"error": "`tasks` must be a JSON object"}
    task_commands: dict[str, list[str]] = {}
    for task_id, commands_raw in tasks_raw.items():
        task_key = _norm(str(task_id))
        if not task_key:
            continue
        commands = _coerce_commands(commands_raw, label=f"tasks.{task_id}")
        if commands:
            task_commands[task_key] = commands

    prefixes_raw = raw.get("task_prefixes", {})
    if prefixes_raw is None:
        prefixes_raw = {}
    if not isinstance(prefixes_raw, dict):
        return False, {"error": "`task_prefixes` must be a JSON object"}
    prefix_rows: list[tuple[str, list[str]]] = []
    for prefix, commands_raw in prefixes_raw.items():
        prefix_key = _norm(str(prefix))
        if not prefix_key:
            continue
        commands = _coerce_commands(commands_raw, label=f"task_prefixes.{prefix}")
        if commands:
            prefix_rows.append((prefix_key, commands))
    prefix_rows.sort(key=lambda item: (-len(item[0]), item[0]))

    default_commands = _coerce_commands(raw.get("default"), label="default")
    payload["tasks"] = task_commands
    payload["task_prefixes"] = prefix_rows
    payload["default"] = default_commands
    return True, payload


def _resolve_task_commands(
    *,
    task: AssignedTask,
    catalog: dict[str, object],
    cli_default_commands: Sequence[str],
) -> tuple[list[str], str]:
    task_key = _norm(task.task_id)
    task_map = dict(catalog.get("tasks") or {})
    if task_key in task_map:
        return list(task_map[task_key]), "catalog.tasks"

    prefix_rows: list[tuple[str, list[str]]] = []
    for item in list(catalog.get("task_prefixes") or []):
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str) and isinstance(item[1], list):
            prefix_rows.append((item[0], [str(x) for x in item[1]]))
    for prefix, commands in prefix_rows:
        if task_key.startswith(_norm(prefix)):
            return list(commands), f"catalog.task_prefixes:{prefix}"

    defaults = [str(item).strip() for item in list(cli_default_commands or []) if str(item).strip()]
    if defaults:
        return defaults, "cli.default"

    catalog_defaults = [str(item).strip() for item in list(catalog.get("default") or []) if str(item).strip()]
    if catalog_defaults:
        return catalog_defaults, "catalog.default"
    return [], "none"


def _render_command(template: str, context: dict[str, str]) -> str:
    safe_context = {key: _quote_for_shell(value) for key, value in context.items()}
    return str(template).format_map(_SafeFormatDict(safe_context)).strip()


def _trim_log(text: str, *, limit: int = 2000) -> str:
    payload = str(text or "")
    if len(payload) <= limit:
        return payload
    return payload[:limit] + "...<trimmed>"


def _run_command_pipeline(
    *,
    commands: Sequence[str],
    context: dict[str, str],
    timeout_seconds: float,
) -> tuple[bool, dict[str, object]]:
    runs: list[CommandRun] = []
    timeout = None if float(timeout_seconds) <= 0 else float(timeout_seconds)
    for idx, template in enumerate(commands, start=1):
        rendered = _render_command(template, context)
        if not rendered:
            return False, {"error": f"command #{idx} rendered to empty text"}
        started = time.monotonic()
        try:
            completed = subprocess.run(
                rendered,
                cwd=ROOT,
                shell=True,
                text=True,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
            elapsed = time.monotonic() - started
            run = CommandRun(
                command=rendered,
                returncode=int(completed.returncode),
                elapsed_seconds=float(elapsed),
                timed_out=False,
                stdout=_trim_log(completed.stdout or ""),
                stderr=_trim_log(completed.stderr or ""),
            )
            runs.append(run)
            if run.returncode != 0:
                return False, {"runs": runs, "failed_index": idx, "failed_command": rendered}
        except subprocess.TimeoutExpired as exc:
            elapsed = time.monotonic() - started
            run = CommandRun(
                command=rendered,
                returncode=124,
                elapsed_seconds=float(elapsed),
                timed_out=True,
                stdout=_trim_log(str(exc.stdout or "")),
                stderr=_trim_log(str(exc.stderr or "")),
            )
            runs.append(run)
            return False, {"runs": runs, "failed_index": idx, "failed_command": rendered, "timed_out": True}

    return True, {"runs": runs}


def _write_run_log(
    *,
    log_root: Path,
    agent: str,
    task: AssignedTask,
    command_source: str,
    runs: Sequence[CommandRun],
    ok: bool,
) -> str:
    agent_slug = _sanitize_token(agent)
    task_slug = _sanitize_token(task.task_id)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = log_root / agent_slug
    path.mkdir(parents=True, exist_ok=True)
    log_path = path / f"{stamp}-{task_slug}.log"
    lines: list[str] = [
        f"agent={agent}",
        f"task_id={task.task_id}",
        f"scope={task.scope}",
        f"summary={task.summary}",
        f"command_source={command_source}",
        f"ok={str(bool(ok)).lower()}",
        f"created_at={_now_iso()}",
        "",
    ]
    for idx, run in enumerate(runs, start=1):
        lines.extend(
            [
                f"[command {idx}] {run.command}",
                f"returncode={run.returncode}; elapsed_seconds={run.elapsed_seconds:.3f}; timed_out={str(run.timed_out).lower()}",
                "--- stdout ---",
                run.stdout,
                "--- stderr ---",
                run.stderr,
                "",
            ]
        )
    log_path.write_text("\n".join(lines), encoding="utf-8")
    return str(log_path)
