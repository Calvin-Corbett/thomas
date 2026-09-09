"""Serialized, fail-closed persistence for directed Code action receipts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from thomas.core.config import resolve_thomas_data_dir

from .webhooks_utils import file_lock

_PROCESS_LOCKS: dict[str, threading.RLock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()


def _receipt_path(root: Path) -> Path:
    repo_key = hashlib.sha256(os.path.normcase(str(Path(root).resolve())).encode("utf-8")).hexdigest()
    directory = resolve_thomas_data_dir() / "forge_code" / repo_key
    directory.mkdir(parents=True, exist_ok=True)
    return directory / "action_receipts.json"


def _receipt_key(kind: str, request_id: str) -> str:
    return hashlib.sha256(f"{kind}:{request_id}".encode()).hexdigest()


def _process_lock(path: Path) -> threading.RLock:
    key = os.path.normcase(str(path.resolve()))
    with _PROCESS_LOCKS_GUARD:
        return _PROCESS_LOCKS.setdefault(key, threading.RLock())


def _read_receipts_path(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeError) as exc:
        raise RuntimeError("Code action receipts are unreadable; refusing an unsafe replay") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Code action receipts have an invalid format")
    if any(not isinstance(value, dict) for value in data.values()):
        raise RuntimeError("Code action receipts contain an invalid entry; refusing an unsafe replay")
    return data


def _read_receipts(root: Path) -> dict[str, dict[str, Any]]:
    return _read_receipts_path(_receipt_path(root))


def _action_receipt(root: Path, kind: str, request_id: str) -> dict[str, Any] | None:
    return _read_receipts(root).get(_receipt_key(kind, request_id))


def _write_receipts(path: Path, receipts: dict[str, dict[str, Any]]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(receipts, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def _save_action_receipt(root: Path, kind: str, request_id: str, receipt: dict[str, Any]) -> dict[str, Any]:
    path = _receipt_path(root)
    with _process_lock(path), file_lock(path.with_suffix(".lock")):
        receipts = _read_receipts_path(path)
        receipts[_receipt_key(kind, request_id)] = dict(receipt)
        _write_receipts(path, receipts)
    return receipt


def _delete_action_receipt(root: Path, kind: str, request_id: str) -> None:
    path = _receipt_path(root)
    with _process_lock(path), file_lock(path.with_suffix(".lock")):
        receipts = _read_receipts_path(path)
        if receipts.pop(_receipt_key(kind, request_id), None) is not None:
            _write_receipts(path, receipts)
