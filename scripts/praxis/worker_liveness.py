"""A worker's own "I am alive and idle" record. stdlib only.

It replaces the idle heartbeat rows the worker used to post on the board, and it replaced a first
attempt that called ``agent_presence.heartbeat_session``. That call resolves a session from the
environment, but a worker never registers one: with no session in the environment it did nothing, and
when the worker was spawned from an agent's shell it inherited that agent's session id and beat the
PARENT's session file, forcing it to ``state=active`` (so a dead parent looked alive and takeover
checks could be blocked). This file is written under the worker's own state directory, is keyed by the
worker's own agent id and pid, and never reads or writes any session.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def liveness_path(state_dir: Path, agent: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", agent.strip()) or "worker"
    return state_dir / f"{safe}.liveness.json"


def read_liveness(state_dir: Path, agent: str) -> dict[str, object]:
    try:
        payload = json.loads(liveness_path(state_dir, agent).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def beat(state_dir: Path, agent: str, *, now: datetime | None = None) -> dict[str, object]:
    """Record one idle heartbeat for ``agent`` and return what was written (atomic replace)."""
    state_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).replace(microsecond=0).isoformat()
    previous = read_liveness(state_dir, agent)
    mine = previous.get("pid") == os.getpid()
    record: dict[str, object] = {
        "agent": agent,
        "pid": os.getpid(),
        "state": "idle",
        "started_at": previous.get("started_at", stamp) if mine else stamp,
        "last_beat_at": stamp,
        "beats": int(previous.get("beats", 0) or 0) + 1 if mine else 1,
    }
    path = liveness_path(state_dir, agent)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(record, sort_keys=True), encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    return record
