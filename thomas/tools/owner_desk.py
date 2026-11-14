"""Asking you from a server that cannot show a prompt itself: the owner's desk.

Once the server runs as thomas-agent (Project 4 of the trusted self-change
design) it has no desktop to show the Windows sign-in on, and a hacked server
would not show it anyway. So it files a request instead -- a catalogue card
kind, its details and a content hash, never words -- in the desk's requests
folder, and waits. The desk (scripts/cage/owner_desk.py) runs as you, renders
the card from the pinned catalogue, asks at the Windows sign-in and writes the
answer into a folder the cage account can read but not write.

An answer counts only for exactly what was asked: the same id, kind and content
hash. No answer in time is a no.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

DESK_ENV = "THOMAS_OWNER_DESK"
# Raised limits the desk has recorded (scripts/cage/owner_desk.py), kept beside the
# answers where the cage account can read but never write, so a restart keeps
# them. The dot keeps the name out of the request-id space: no request can be
# answered under it.
GRANTS_NAME = "dial-grants.v1.json"


def enabled() -> bool:
    """True when prompts go through the desk: the server is not running as you."""
    return str(os.environ.get(DESK_ENV) or "").strip() == "1"


def desk_root(root: Path | None = None) -> Path:
    if root is None:
        from thomas.tools.cage_shell import cage_root

        root = cage_root()
    return Path(root) / "desk"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def recorded_grants(root: Path | None = None) -> dict[str, str]:
    """dial -> the highest value you approved at the desk, as the desk recorded it."""
    data = _read(desk_root(root) / "answers" / GRANTS_NAME) or {}
    return {str(dial): str(value) for dial, value in data.items()}


def ask_owner(
    kind: str,
    details: dict[str, object],
    *,
    content_hash: str,
    root: Path | None = None,
    timeout_s: float = 300.0,
    poll_s: float = 0.5,
) -> bool:
    """File the request and wait for your answer. True only for an approval of
    exactly this request. Blocks; use ask_owner_async from a coroutine."""
    base = desk_root(root)
    requests = base / "requests"
    requests.mkdir(parents=True, exist_ok=True)
    rid = uuid.uuid4().hex
    request = requests / f"{rid}.json"
    payload = {
        "id": rid,
        "kind": str(kind),
        "details": {str(k): str(v) for k, v in details.items()},
        "content_hash": str(content_hash),
        "created_at": time.time(),
    }
    staging = requests / f".{rid}.tmp"
    staging.write_bytes(json.dumps(payload).encode("utf-8"))
    os.replace(staging, request)
    deadline = time.monotonic() + timeout_s
    try:
        while time.monotonic() < deadline:
            answer = _read(base / "answers" / f"{rid}.json")
            if answer is not None:
                return (
                    answer.get("id") == rid
                    and answer.get("kind") == payload["kind"]
                    and answer.get("content_hash") == payload["content_hash"]
                    and answer.get("approved") is True
                )
            time.sleep(poll_s)
        return False
    finally:
        try:
            request.unlink(missing_ok=True)
        except OSError:
            pass


async def ask_owner_async(kind: str, details: dict[str, object], **kwargs: Any) -> bool:
    return await asyncio.to_thread(ask_owner, kind, details, **kwargs)


__all__ = ["DESK_ENV", "GRANTS_NAME", "ask_owner", "ask_owner_async", "desk_root", "enabled", "recorded_grants"]
