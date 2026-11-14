"""Pause: one saved switch that stops everything Thomas starts by himself.

While paused the server stays up and Chat still answers, but nothing Thomas would start on his own starts: engines,
daily autoruns, the queue of planned projects, scheduled jobs, the idle sweep and any new Build or Code run. A run that
is already going is not ended. Resume lets it all start again.

The flag is a small file, ``paused.json``, in the data folder, so it survives a restart and a server that starts while
paused starts nothing of its own. Every caller asks :func:`paused` on its own next cycle, so Resume needs no restart.

A read never raises. A missing file means not paused. A file that cannot be read or understood also means not paused,
and says so once in the log: a broken file must not stop Thomas for good.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from thomas.core.atomic_json import read_text_with_retry, write_json_atomic
from thomas.core.config import resolve_thomas_data_dir

log = logging.getLogger(__name__)

FILE_NAME = "paused.json"
REFUSAL = "Thomas is paused. Press Resume on the Plugins page."

_warned_for: str | None = None


def pause_path() -> Path:
    """Where the flag lives: ``paused.json`` in the data folder, worked out on every call."""
    return resolve_thomas_data_dir() / FILE_NAME


def _empty() -> dict[str, Any]:
    return {"paused": False, "since": None, "reason": ""}


def state() -> dict[str, Any]:
    """``{"paused": bool, "since": iso string or None, "reason": str}``. Never raises."""
    global _warned_for
    path = pause_path()
    try:
        if not path.is_file():
            _warned_for = None
            return _empty()
        data = json.loads(read_text_with_retry(path))
        if not isinstance(data, dict):
            raise ValueError("the file does not hold an object")
        _warned_for = None
        if not data.get("paused"):
            return _empty()
        since = data.get("since")
        return {
            "paused": True,
            "since": since if isinstance(since, str) and since else None,
            "reason": str(data.get("reason") or ""),
        }
    except (OSError, ValueError) as exc:
        if _warned_for != str(path):
            _warned_for = str(path)
            log.warning("Pause file %s cannot be read, so Thomas is not paused: %s", path, exc)
        return _empty()


def paused() -> bool:
    """True while Thomas is paused."""
    return bool(state()["paused"])


def pause(reason: str = "") -> dict[str, Any]:
    """Pause Thomas and keep the first time and reason if it already is. Returns the new state."""
    current = state()
    if current["paused"]:
        return current
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    write_json_atomic(pause_path(), {"paused": True, "since": now, "reason": str(reason or "")[:500]})
    return state()


def resume() -> dict[str, Any]:
    """Let Thomas start work again. Returns the new state."""
    path = pause_path()
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        write_json_atomic(path, _empty())
    return state()
