"""Operational helpers for the project swarm runner."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from scripts.workboard_claim_ops import claim, release
from scripts.workboard_message import send_message


def workboard_message(workboard: Path, *, sender: str, recipient: str, task_id: str, summary: str) -> None:
    if not workboard.exists():
        return
    send_message(
        workboard,
        sender=sender,
        recipient=recipient,
        task_id=task_id,
        kind="status",
        priority="p1",
        summary=summary,
        require_claims_to_have_active_task=False,
    )


def claim_scope(workboard: Path, *, agent: str, scope: str, task: str, role: str, parent: str) -> None:
    ok, message = claim(
        workboard,
        agent=agent,
        name=agent,
        role=role,
        parent=parent,
        scope=scope,
        task=task,
    )
    if not ok:
        raise ValueError(str(message))


def release_scope(workboard: Path, *, agent: str) -> None:
    release(
        workboard,
        agent=agent,
    )


def _terminate_process_tree(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
            capture_output=True,
            text=True,
            check=False,
        )
    else:
        proc.kill()


def run_command_with_timeout(cmd: list[str], *, cwd: Path, timeout_s: int) -> tuple[int, str, str, bool, float]:
    started = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        text=True,
    )
    if int(timeout_s) <= 0:
        stdout, stderr = proc.communicate()
        return int(proc.returncode or 0), str(stdout or ""), str(stderr or ""), False, time.perf_counter() - started
    try:
        stdout, stderr = proc.communicate(timeout=max(1, int(timeout_s)))
        return int(proc.returncode or 0), str(stdout or ""), str(stderr or ""), False, time.perf_counter() - started
    except subprocess.TimeoutExpired as exc:
        stdout = str(exc.stdout or "")
        stderr = str(exc.stderr or "")
        _terminate_process_tree(proc)
        try:
            tail_out, tail_err = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            tail_out, tail_err = proc.communicate()
        stdout += str(tail_out or "")
        stderr += str(tail_err or "")
        return 124, stdout, stderr, True, time.perf_counter() - started
