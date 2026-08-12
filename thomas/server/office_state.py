"""Durable, bounded server-owned state shared with the live Virtual Office."""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_AGENT_ID_RE = re.compile(r"^(?:agent-(?:[1-9]|1[0-2]))?$")


def normalize_follow_agent_id(value: Any) -> str:
    agent_id = str(value or "").strip().lower()
    if _AGENT_ID_RE.fullmatch(agent_id) is None:
        raise ValueError("follow_agent_id must be empty or one of the live agent-1 through agent-12 ids")
    return agent_id


class OfficeStateStore:
    """Atomic JSON store for the small Office state shared across browser/server."""

    def __init__(self, root: str | Path) -> None:
        self.path = Path(root) / ".thomas" / "office_state.json"
        self._lock = threading.RLock()

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "users": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValueError("Office state could not be read safely") from exc
        if not isinstance(data, dict) or not isinstance(data.get("users", {}), dict):
            raise ValueError("Office state has an invalid shape")
        return data

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            dir=str(self.path.parent), prefix=".office_state_", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_name, self.path)
        except OSError:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    def get(self, *, user_id: str = "default") -> dict[str, Any]:
        owner = str(user_id or "default").strip() or "default"
        with self._lock:
            row = (self._read().get("users") or {}).get(owner)
            state = row if isinstance(row, dict) else {}
            return {
                "follow_agent_id": normalize_follow_agent_id(state.get("follow_agent_id")),
                "updated_at": str(state.get("updated_at") or ""),
            }

    def set_follow_agent(self, agent_id: Any, *, user_id: str = "default") -> dict[str, Any]:
        owner = str(user_id or "default").strip() or "default"
        follow_agent_id = normalize_follow_agent_id(agent_id)
        with self._lock:
            data = self._read()
            users = data.setdefault("users", {})
            users[owner] = {
                "follow_agent_id": follow_agent_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write(data)
            return self.get(user_id=owner)


__all__ = ["OfficeStateStore", "normalize_follow_agent_id"]
