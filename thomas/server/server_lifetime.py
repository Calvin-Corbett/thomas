"""Each server start and exit goes in the step log, and a start says when the server before it died without exiting.

On 2026-11-06 Build runs were cut off at twelve moments in one day, about two each time, 15.6 hours of runs in two
days, each recorded only by the next server as "interrupted". None of those servers had drained for a landed-code
reload, and nothing said why they stopped. A marker written at start and closed at a clean exit tells the next start
which it was: a clean exit, or a server that died (a crash, a kill, the machine) with its runs still going.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from thomas.core import step_log
from thomas.core.config import resolve_thomas_data_dir

log = logging.getLogger(__name__)
MARKER_NAME = "server-lifetime.json"


def _marker() -> Path:
    return resolve_thomas_data_dir() / MARKER_NAME


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(data), encoding="utf-8")
    os.replace(temporary, path)


def started(port: int | None = None, *, path: Path | None = None, now: float | None = None) -> dict[str, Any] | None:
    """Note this server's start; return the server before it when that one died without exiting. Never raises."""
    path = path or _marker()
    now = time.time() if now is None else now
    try:
        before = _read(path)
        died = before if before and not before.get("exited") and before.get("pid") != os.getpid() else None
        if died is not None:
            step_log.record(
                "server_died",
                seconds=round(now - float(died.get("started") or now), 3),
                died_pid=died.get("pid"),
                port=died.get("port"),
            )
        step_log.record("server_start", port=port)
        _write(path, {"pid": os.getpid(), "port": port, "started": now, "exited": False})
        return died
    except OSError:
        log.debug("server lifetime marker could not be written", exc_info=True)
        return None


def exited(reason: str = "cleanup", *, path: Path | None = None, now: float | None = None) -> None:
    """Note this server's clean exit. Never raises."""
    path = path or _marker()
    now = time.time() if now is None else now
    try:
        mine = _read(path)
        if mine is None or mine.get("pid") != os.getpid():
            return  # another server has started since; its marker is not ours to close
        step_log.record("server_exit", seconds=round(now - float(mine.get("started") or now), 3), reason=reason)
        _write(path, {**mine, "exited": True, "exited_at": now, "reason": reason})
    except OSError:
        log.debug("server lifetime marker could not be closed", exc_info=True)
