"""Durable self-project asks shared by the servers using one catalog."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any
from uuid import uuid4

from thomas.core import atomic_json
from thomas.server import capacity_ledger_locks, thomas_project
from thomas.server.routes.self_project_listing_cache import read_record

NAME = "self_project_queue.json"


class QueueUnreadable(RuntimeError):
    """Existing queue bytes are not a readable JSON object; never replace them."""


def path(catalog: Path | None = None) -> Path:
    root = Path(catalog) if catalog is not None else Path(thomas_project._catalog_root())
    return root / ".thomas" / "evolve" / "agent" / NAME


def read(catalog: Path | None = None) -> dict[str, Any]:
    file = path(catalog)
    for attempt in range(capacity_ledger_locks.READ_TRIES):
        try:
            data = read_record(file)
            break
        except FileNotFoundError:
            return {"queued": [], "started": [], "given_up": [], "planner": {"enabled": True, "last_scan": 0}}
        except PermissionError:
            if attempt == capacity_ledger_locks.READ_TRIES - 1:
                raise
            time.sleep(capacity_ledger_locks.READ_WAIT_S)
        except OSError as exc:
            if getattr(exc, "winerror", None) not in {32, 33}:
                raise QueueUnreadable("the self-project queue could not be read") from exc
            if attempt == capacity_ledger_locks.READ_TRIES - 1:
                raise PermissionError("the queue is busy") from exc
            time.sleep(capacity_ledger_locks.READ_WAIT_S)
        except (ValueError, UnicodeError) as exc:
            raise QueueUnreadable("the self-project queue could not be read") from exc
    if (
        not isinstance(data, dict)
        or not isinstance(data.get("queued"), list)
        or not isinstance(data.get("started"), list)
        or not isinstance(data.get("given_up"), list)
    ):
        raise QueueUnreadable("the self-project queue could not be read")
    data.setdefault("planner", {"enabled": True, "last_scan": 0})
    return data


def change(catalog: Path | None, update: Callable[[dict[str, Any]], Any]) -> Any:
    file = path(catalog)
    with capacity_ledger_locks.locked(file.parent, file.name):
        data = read(catalog)  # always reread after taking the cross-process lock
        before = json.dumps(data, sort_keys=True)
        result = update(data)
        if json.dumps(data, sort_keys=True) != before:
            atomic_json.write_json_atomic(file, data)
        return result


def new_entry(request: str, settings: dict[str, Any], chat_session_id: str, port: int) -> dict[str, Any]:
    return {
        "id": uuid4().hex,
        "request": request,
        "settings": settings,
        "chat_session_id": chat_session_id,
        "port": port,
        "queued_at": time.time(),
        "tries": 0,
        "last_reason": "",
        "given_up": False,
    }


def enqueue(
    catalog: Path | None, request: str, settings: dict[str, Any], chat_session_id: str, port: int
) -> dict[str, Any]:
    ask = new_entry(request, settings, chat_session_id, port)

    def add(data: dict[str, Any]) -> dict[str, Any]:
        data["queued"].append(ask)
        return {"ok": True, "id": ask["id"], "place": len(data["queued"]), "queued_at": ask["queued_at"]}

    return change(catalog, add)
