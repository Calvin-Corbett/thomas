"""Deterministic exit codes and machine-readable run logs for headless CLI runs.

Contract (CAP-078, Level 2):

Exit codes
    0  success
    1  agent/task error (an ``AGENT_ERROR`` event or a failed completion)
    2  usage/config error (unknown model profile, invalid configuration)
    3  timeout or interrupted run

Run log format
    One JSON summary object per run, appended as a single JSONL line to the
    path given by ``--run-log <path>`` or the ``THOMAS_RUN_LOG`` environment
    variable (the CLI flag wins when both are set). Each record contains:
    ``timestamp`` (UTC ISO-8601, run start), ``prompt``, ``model_profile``,
    ``model``, ``outcome`` (success|agent_error|usage_error|timeout),
    ``exit_code``, ``duration_s``, ``error`` (null on success), and
    ``artifacts`` (list of output paths when produced).

    Records are written with a single ``O_APPEND`` OS-level write so a line is
    never interleaved or torn by concurrent runs. Log-write failures never
    change the run's exit code: the failure is noted on stderr and the run
    result stands.

This module sits at the bottom of the CLI dependency tree and must not import
from ``thomas.server``, ``thomas.agent``, or ``thomas.tools``.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXIT_SUCCESS = 0
EXIT_AGENT_ERROR = 1
EXIT_USAGE_ERROR = 2
EXIT_TIMEOUT = 3

OUTCOME_SUCCESS = "success"
OUTCOME_AGENT_ERROR = "agent_error"
OUTCOME_USAGE_ERROR = "usage_error"
OUTCOME_TIMEOUT = "timeout"

RUN_LOG_ENV_VAR = "THOMAS_RUN_LOG"

_EXIT_CODES: dict[str, int] = {
    OUTCOME_SUCCESS: EXIT_SUCCESS,
    OUTCOME_AGENT_ERROR: EXIT_AGENT_ERROR,
    OUTCOME_USAGE_ERROR: EXIT_USAGE_ERROR,
    OUTCOME_TIMEOUT: EXIT_TIMEOUT,
}


def exit_code_for_outcome(outcome: str) -> int:
    """Map an outcome string onto the deterministic exit-code contract.

    Unknown outcomes map to ``EXIT_AGENT_ERROR`` so a bad label can never
    masquerade as success.
    """
    return _EXIT_CODES.get(str(outcome or "").strip().lower(), EXIT_AGENT_ERROR)


def resolve_run_log_path(cli_value: str | None = None) -> Path | None:
    """Resolve the run-log destination: ``--run-log`` flag, then env var."""
    raw = str(cli_value or "").strip() or str(os.environ.get(RUN_LOG_ENV_VAR) or "").strip()
    if not raw:
        return None
    return Path(raw).expanduser()


def append_run_record(path: Path, record: dict[str, Any]) -> bool:
    """Append ``record`` to ``path`` as one JSONL line. Never raises.

    The full line is emitted through a single ``os.write`` on a descriptor
    opened with ``O_APPEND`` so records from concurrent runs stay whole.
    Returns ``True`` on success; on failure a note is written to stderr and
    ``False`` is returned so callers keep their exit code unchanged.
    """
    try:
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        parent = path.parent
        if str(parent):
            parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_APPEND)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)
        return True
    except (OSError, TypeError, ValueError) as exc:
        sys.stderr.write(f"[run-log] failed to write run log to {path}: {exc}\n")
        return False


class HeadlessRunRecorder:
    """Collects metadata for one headless execution and finalizes it.

    Create the recorder as early as possible in the command so usage/config
    failures are captured too; call :meth:`finish` exactly once per exit path.
    ``finish`` returns the deterministic exit code for ``outcome`` and, when a
    run-log destination is configured, appends the JSONL summary record.
    """

    def __init__(self, prompt: str, run_log_flag: str | None = None) -> None:
        self.prompt = prompt
        self.path = resolve_run_log_path(run_log_flag)
        self.started_at = datetime.now(timezone.utc)
        self._t0 = time.monotonic()
        self.model_profile: str = ""
        self.model_id: str = ""
        self.artifacts: list[str] = []

    def finish(self, outcome: str, *, error: str | None = None) -> int:
        exit_code = exit_code_for_outcome(outcome)
        record: dict[str, Any] = {
            "timestamp": self.started_at.isoformat(),
            "prompt": self.prompt,
            "model_profile": self.model_profile,
            "model": self.model_id,
            "outcome": outcome,
            "exit_code": exit_code,
            "duration_s": round(time.monotonic() - self._t0, 3),
            "error": error or None,
            "artifacts": [str(item) for item in self.artifacts],
        }
        if self.path is not None:
            append_run_record(self.path, record)
        return exit_code
