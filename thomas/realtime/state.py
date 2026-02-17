from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional, List, Dict
import time
import uuid


def new_session_id() -> str:
    return f"rt_{uuid.uuid4().hex[:10]}"


@dataclass
class Attachment:
    handle: str
    name: str
    mime: str
    size: int


@dataclass
class ConversationTurn:
    role: str  # user | assistant | system
    text: str
    ts_ms: int


@dataclass
class ConversationState:
    session_id: str
    created_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    mode: str = "balanced"
    turns: list[ConversationTurn] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    pinned_goals: list[dict[str, Any]] = field(default_factory=list)

    def add_turn(self, role: str, text: str):
        self.turns.append(ConversationTurn(role=role, text=text, ts_ms=int(time.time()*1000)))

    def add_attachment(self, a: Attachment):
        self.attachments.append(a)

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_ms": self.created_ms,
            "mode": self.mode,
            "turns": [asdict(t) for t in self.turns[-50:]],
            "attachments": [asdict(a) for a in self.attachments[-50:]],
            "pinned_goals": self.pinned_goals[-50:],
        }
