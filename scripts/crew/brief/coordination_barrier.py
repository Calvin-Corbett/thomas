"""Fail-closed, read-only unread-P0 coordination barrier."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class CoordinationBlocked(RuntimeError):
    def __init__(self, agent: str, message_ids: list[str]) -> None:
        self.agent = agent
        self.message_ids = tuple(message_ids)
        super().__init__(f"agent {agent!r} has unread P0 message(s): {', '.join(message_ids)}")


@dataclass(frozen=True)
class BarrierSnapshot:
    agent: str
    board_sha256: str
    open_p0_ids: tuple[str, ...]


UnreadReader = Callable[[Path, str], tuple[bool, dict[str, Any]]]
_MESSAGE_HEADING = re.compile(r"^##\s+Agent Message Traffic\b", re.MULTILINE | re.IGNORECASE)


def _default_unread_reader(workboard: Path, agent: str) -> tuple[bool, dict[str, Any]]:
    try:
        from scripts.crew.workboard.message import unread_messages
    except ImportError:  # pragma: no cover
        from crew.workboard.message import unread_messages  # type: ignore
    return unread_messages(workboard, agent=agent)


def require_clear_p0(
    workboard: Path,
    *,
    bound_agent: str,
    unread_reader: UnreadReader = _default_unread_reader,
    allowed_takeover_transaction_id: str = "",
) -> BarrierSnapshot:
    """Refuse a mutation when the bound agent has any open P0 message."""
    agent = str(bound_agent or "").strip()
    if not agent:
        raise CoordinationBlocked("", ["identity-unbound"])
    resolved = Path(workboard).resolve()
    root = (
        resolved.parents[2]
        if resolved.name.casefold() == "workboard.md" and resolved.parent.name.casefold() == "thomas"
        else resolved.parent
    )
    marker_path = root / "runtime" / "coordination" / "workboard_takeover_transaction.json"
    if marker_path.exists():
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            transaction_id = str(marker.get("transaction_id") or "").strip() if isinstance(marker, dict) else ""
        except (OSError, json.JSONDecodeError):
            transaction_id = ""
        if not transaction_id:
            raise CoordinationBlocked(agent, ["takeover-transaction-invalid"])
        if transaction_id != str(allowed_takeover_transaction_id or "").strip():
            raise CoordinationBlocked(agent, [f"takeover-transaction:{transaction_id}"])
    try:
        raw = Path(workboard).read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeError) as exc:
        raise CoordinationBlocked(agent, [f"workboard-unreadable:{type(exc).__name__}"]) from exc
    # Older valid boards predate the optional message section. They have no
    # place an unread P0 could exist, so treat absence as an empty inbox while
    # still failing closed when a present section cannot be parsed.
    if not _MESSAGE_HEADING.search(text):
        return BarrierSnapshot(agent=agent, board_sha256=hashlib.sha256(raw).hexdigest(), open_p0_ids=())
    try:
        ok, payload = unread_reader(Path(workboard), agent)
    except (OSError, RuntimeError, ValueError) as exc:
        raise CoordinationBlocked(agent, ["message-section-invalid"]) from exc
    if not ok:
        raise CoordinationBlocked(agent, ["message-section-invalid"])
    rows = list(payload.get("messages") or [])
    ids = sorted(
        {
            str(row.get("msg_id") or "<missing-id>").strip()
            for row in rows
            if str(row.get("state") or "").strip().casefold() == "open"
            and str(row.get("priority") or "").strip().casefold() == "p0"
        }
    )
    if ids:
        raise CoordinationBlocked(agent, ids)
    return BarrierSnapshot(agent=agent, board_sha256=hashlib.sha256(raw).hexdigest(), open_p0_ids=())
