from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .kernel import CompanionKernel


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class AuditEvent:
    timestamp: str
    event_type: str
    actor: str
    peer_identity: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "actor": self.actor,
            "peer_identity": self.peer_identity,
            "details": dict(self.details),
        }


class CompanionAuditLog:
    def __init__(self, kernel: CompanionKernel):
        self.kernel = kernel
        self.kernel.init_layout()
        self.path = self.kernel.paths.logs_dir / "companion_events.ndjson"
        if not self.path.exists():
            self.path.write_text("", encoding="utf-8")

    def append(
        self,
        event_type: str,
        *,
        actor: str = "api",
        peer_identity: str = "",
        details: dict[str, Any] | None = None,
        timestamp: str = "",
    ) -> dict[str, Any]:
        ev = AuditEvent(
            timestamp=str(timestamp or _now_iso()),
            event_type=str(event_type or "").strip() or "unknown",
            actor=str(actor or "").strip() or "api",
            peer_identity=str(peer_identity or "").strip(),
            details=dict(details or {}),
        ).to_dict()
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(ev, ensure_ascii=True) + "\n")
        return ev

    def list(self, *, limit: int = 100, event_type: str = "") -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        wanted = str(event_type or "").strip()
        lim = max(1, min(2000, int(limit or 100)))
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except Exception:
            lines = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            if wanted and str(payload.get("event_type") or "") != wanted:
                continue
            out.append(payload)
            if len(out) >= lim:
                break
        out.reverse()
        return out
