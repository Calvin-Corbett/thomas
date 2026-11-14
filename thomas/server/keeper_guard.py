"""Keep a green until its work has a verified keeper receipt.

The operator creates drop\\captures in advance: thomas-agent has
(RD,WD,RA,REA,X,S) there and (RA) on drop; OWNER RIGHTS has (OI)(IO)(R).
The writer can create and read captures, but cannot rewrite or delete them.
"""

from __future__ import annotations

import errno
import hashlib
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from thomas.core.process_alive import process_alive
from thomas.server import green_checkout, green_handoff
from thomas.server import keeper_guard_capture as capture
from thomas.server import keeper_guard_files as files
from thomas.server import serve_instance_guard as instance_guard

if TYPE_CHECKING:
    from collections.abc import Iterator

log = logging.getLogger(__name__)
KEEPER_DROP = Path(r"C:\ProgramData\ThomasCage\keeper\drop")
DROP_ENV = "THOMAS_KEEPER_DROP"
CAPTURES = "captures"
RESERVE_NAME = "keeper-reserve.bin"
RESERVE_BYTES = 256 * 1024 * 1024
FAILED_NAME = "capture-failed.json"
LOCK_NAME = "keeper-removing.lock"
LOCK_STALE_S = 3600
CAPTURE_ERRORS = (OSError, green_checkout.GreenUnavailable, ValueError, TypeError, LookupError, AttributeError, RuntimeError, ArithmeticError, ImportError, subprocess.SubprocessError)  # fmt: skip


class GreenKept(OSError):
    """A green could not be saved and must survive for another sweep."""


def drop_folder() -> Path:
    """Tests alone may redirect the operator-managed drop."""
    # Only a pytest run can redirect the real keeper drop; no runtime setting moves it.
    return (
        Path(os.environ[DROP_ENV])
        if os.environ.get("PYTEST_CURRENT_TEST") and os.environ.get(DROP_ENV)
        else KEEPER_DROP
    )


def capture_folders() -> list[Path]:
    drop = drop_folder() / CAPTURES
    try:
        available = drop.is_dir()
    except OSError as exc:
        log.warning("keeper drop %s cannot be reached: %s", drop, exc)
        available = False
    return ([drop] if available else []) + [green_checkout.green_root().parent / CAPTURES]


def _stamp() -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())


def keep_reserve() -> None:
    """Keep emergency free space beside the green root, never in the create-only drop."""
    if RESERVE_BYTES <= 0:
        return
    path = green_checkout.green_root().parent / CAPTURES / RESERVE_NAME
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() or shutil.disk_usage(path.parent).free < 2 * RESERVE_BYTES:
            return
        with files.new_file(path) as stream:
            stream.truncate(RESERVE_BYTES)
    except FileExistsError:
        return
    except OSError as exc:
        log.warning("keeper reserve could not be made: %s", exc)


def _receipt(
    green: green_checkout.Green,
    selection: tuple[list[str], list[str], list[dict[str, str]]],
    add: list[str],
    gone: list[str],
    changed: bool,
    patch: str | None,
    sha: str | None,
    size: int,
) -> dict[str, object]:
    reason = (
        "settled: its run is over"
        if (green.git_dir / green_checkout.SETTLED_NAME).exists()
        else "kept: it held unfinished work"
        if (green.git_dir / green_checkout.KEPT_NAME).exists()
        else "removed before its run settled"
    )
    staged = set(add + gone)
    return {
        "execution": green.execution_id,
        "base": green.base,
        "files": [p for p in selection[0] if p in staged],
        "left_out": sorted(p for p in selection[1] if p in staged),
        "not_saved": selection[2],
        "reason": reason,
        "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "changed": changed,
        "patch": patch,
        "sha256": sha,
        "bytes": size,
        "apply_with": capture.APPLY_WITH if patch else "",
    }


def _save_in(
    folder: Path,
    green: green_checkout.Green,
    selection: tuple[list[str], list[str], list[dict[str, str]]],
    add: list[str],
    gone: list[str],
    index: Path,
    changed: bool,
) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    stem = f"{green.execution_id}-{_stamp()}"
    for suffix in range(1, 10001):
        name = stem if suffix == 1 else f"{stem}-{suffix}"
        receipt = folder / f"{name}.json"
        patch = folder / f"{name}.patch"
        if receipt.exists() or (changed and patch.exists()):
            continue
        sha, size = None, 0
        try:
            if changed:
                with files.new_file(patch) as stream:
                    sha, size = capture.write_patch(green, index, stream)
                    read = files.read_back(stream)
                    if read is not None and read != sha:
                        raise OSError("patch read-back does not match")
            record = _receipt(green, selection, add, gone, changed, patch.name if changed else None, sha, size)
            data = json.dumps(record, ensure_ascii=False).encode("utf-8")
            with files.new_file(receipt) as stream:
                files.write_all(stream, data)
                read = files.read_back(stream)
                if read is not None and read != hashlib.sha256(data).hexdigest():
                    raise OSError("receipt read-back does not match")
            return receipt
        except FileExistsError:
            if changed:
                files.remove(patch, "unused patch")
            continue
        except CAPTURE_ERRORS:
            # The drop cannot grant delete access; partial patches there remain inert.
            if changed:
                files.remove(patch, "failed patch")
            raise
    raise OSError("keeper capture names exhausted")


def _save(
    green: green_checkout.Green,
    selection: tuple[list[str], list[str], list[dict[str, str]]],
    add: list[str],
    gone: list[str],
    index: Path,
    changed: bool,
) -> Path:
    failures: list[tuple[Path, OSError]] = []
    for folder in capture_folders():
        try:
            return _save_in(folder, green, selection, add, gone, index, changed)
        except OSError as exc:
            log.warning("keeper capture in %s failed: %s", folder, exc)
            failures.append((folder, exc))
    number = errno.ENOSPC if any(capture.disk_full(e) for _, e in failures) else errno.EIO
    raise OSError(number, "no capture folder took it: " + "; ".join(f"{p}: {e}" for p, e in failures))


def capture_green(green: green_checkout.Green) -> Path | None:
    """Save real green work, never a half-created or scratch checkout."""
    if (
        green.execution_id.startswith(green_handoff.SCRATCH_PREFIX)
        or green_checkout._metadata(green.git_dir) is None
        or not green.work.exists()
    ):
        return None
    selected, left_out, not_saved = capture.changes(green)
    add, gone = capture.sort_out(green, selected + left_out, not_saved)
    index = green.git_dir / f"keeper-capture-{os.getpid()}-{threading.get_ident()}.index"
    try:
        capture.stage(green, add, gone, index)
        return _save(green, (selected, left_out, not_saved), add, gone, index, capture.differs(green, index))
    finally:
        files.remove(index, "capture index")


def _failure(green: green_checkout.Green, exc: Exception) -> None:
    record = {
        "reason": "green kept: capture failed",
        "at": datetime.now(timezone.utc).isoformat(),
        "error": type(exc).__name__,
        "message": str(exc),
    }
    path = green.git_dir / FAILED_NAME
    temp = green.git_dir / f".{FAILED_NAME}.{os.getpid()}.tmp"
    try:
        temp.write_text(json.dumps(record), encoding="utf-8")
        os.replace(temp, path)
    except OSError as error:
        log.warning("green %s failure record could not be written: %s", green.execution_id, error)
        files.remove(temp, "failure record temporary file")


def _clear_rebuilt(green: green_checkout.Green) -> None:
    try:
        folders = capture.rebuilt(green)
    except CAPTURE_ERRORS as exc:
        log.warning("green %s rebuildable folders could not be listed: %s", green.execution_id, exc)
        return
    for name in folders:
        path = green.work / name.rstrip("/")
        try:
            if capture.linked(green.work, name.rstrip("/")):
                log.warning("green %s rebuildable folder %s is a link; not removed", green.execution_id, name)
                continue
            shutil.rmtree(path, onexc=green_checkout._force_writable)
        except OSError as exc:
            log.warning("green %s rebuildable folder %s could not be removed: %s", green.execution_id, name, exc)


def before_delete(green: green_checkout.Green) -> Path | None:
    try:
        try:
            receipt = capture_green(green)
        except CAPTURE_ERRORS as exc:
            if not capture.disk_full(exc):
                raise
            reserve = green_checkout.green_root().parent / CAPTURES / RESERVE_NAME
            if not reserve.exists() or not files.remove(reserve, "keeper reserve"):
                raise
            receipt = capture_green(green)
        files.remove(green.git_dir / FAILED_NAME, "failure record")
        return receipt
    except CAPTURE_ERRORS as exc:
        log.warning("green %s is kept: %s", green.execution_id, exc)
        _failure(green, exc)
        _clear_rebuilt(green)
        raise GreenKept(f"green {green.execution_id} is kept: {exc}") from exc


def _remover_runs(pid: int | None, started_at: object) -> bool:
    """A live PID may belong to another process after the remover exits.
    Keep older locks when the OS cannot establish who owns that PID."""
    if pid is None or not process_alive(pid):
        return False
    if not isinstance(started_at, (int, float)):
        return True
    current = instance_guard.process_started_at(pid)
    return current is None or abs(current - started_at) <= instance_guard.START_TOLERANCE_S


@contextmanager
def removing(green: green_checkout.Green) -> Iterator[Path | None]:
    """Lock, capture and delete a green, replacing the reserve after deletion."""
    lock = green.git_dir / LOCK_NAME
    own_started_at = instance_guard.process_started_at(os.getpid())
    acquired = False
    if green.git_dir.is_dir():
        for attempt in range(2):
            try:
                with open(lock, "x", encoding="utf-8") as stream:
                    json.dump({"pid": os.getpid(), "started_at": own_started_at, "at": time.time()}, stream)
                acquired = True
                break
            except FileExistsError as exc:
                try:
                    data = json.loads(lock.read_text(encoding="utf-8"))
                    age = time.time() - float(data.get("at", 0))
                    pid = int(data.get("pid"))
                    started_at = data.get("started_at")
                except (OSError, ValueError, TypeError, AttributeError):
                    try:
                        age = time.time() - lock.stat().st_mtime
                    except OSError as stat_error:
                        raise GreenKept("being removed by another caller") from stat_error
                    pid = started_at = None
                if age < LOCK_STALE_S or _remover_runs(pid, started_at):
                    raise GreenKept("being removed by another caller") from exc
                if attempt:
                    raise GreenKept("being removed by another caller") from exc
                log.warning("stale keeper removal lock age %.0fs pid %s: removing", age, pid)
                if not files.remove(lock, "stale removal lock"):
                    raise GreenKept("being removed by another caller") from exc
    deleted = False
    try:
        yield before_delete(green)
        deleted = True
    finally:
        if acquired:
            files.remove(lock, "removal lock")
        if deleted:
            keep_reserve()


__all__ = ("KEEPER_DROP", "DROP_ENV", "CAPTURES", "RESERVE_NAME", "RESERVE_BYTES", "FAILED_NAME", "LOCK_NAME", "LOCK_STALE_S", "CAPTURE_ERRORS", "GreenKept", "drop_folder", "capture_folders", "keep_reserve", "capture_green", "before_delete", "removing")  # fmt: skip
