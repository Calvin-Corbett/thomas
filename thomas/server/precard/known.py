"""Which tests already fail on a dev, kept to order a check's re-runs and never to excuse one (spec Part 1 item 2).

A check confirms each failure alone with the change and then on dev. Failures dev is known to have are confirmed
last, so the re-runs go first to the failures that may be the change's own. The record is only a hint: Build teams run
as the account that writes it, so it may be wrong, and nothing read from it excuses a failure; only the re-run on dev,
alone, does. It is keyed by the dev tree, the interpreter and the environment the tests inherit, and kept under the
green root's ``precard-known`` folder, never under ``precard/``, which ``slot.clear_leftovers`` empties.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
import threading
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from thomas.server import green_checkout
from thomas.server.proof import environment

FOLDER = "precard-known"
_KEPT = 400
# A record keeps at most _KEPT test ids, far under this. Anything larger was not written here and is not read.
_MAX_BYTES = 1024 * 1024
_MAX_RECORDS = 200
_RECORD_AGE = 30 * 86400
_TEMP_AGE = 3600
_RECORD_NAME = re.compile(r"[0-9a-f]{64}\.json\Z")
_TEMP_NAME = re.compile(r"\.known-[a-z0-9_]{8}\.tmp\Z")
_lock = threading.RLock()


def key(copy: Any, python: str, extra_env: Mapping[str, str] | None = None) -> str:
    """The record's key for this dev tree, interpreter and inherited environment; "" when the tree cannot be read."""
    try:
        tree = green_checkout.git(copy, "rev-parse", "HEAD^{tree}")
    except (green_checkout.GreenUnavailable, OSError, subprocess.SubprocessError, AttributeError, TypeError):
        return ""  # a hint that cannot be keyed is simply not used
    if tree.returncode != 0 or not tree.stdout.strip():
        return ""
    inherited = sorted((k, v) for k, v in os.environ.items() if not k.upper().startswith(environment._DROPPED))
    extra = sorted((str(k), str(v)) for k, v in (extra_env or {}).items())
    named = json.dumps([tree.stdout.strip(), str(python), inherited, extra])
    return hashlib.sha256(named.encode("utf-8", errors="surrogateescape")).hexdigest()


def _path(name: str) -> Path:
    return green_checkout.green_root() / FOLDER / f"{name}.json"


def _prune(protected: Path) -> None:
    """Discard unused hints and abandoned writes; cleanup is never a check result."""
    records: list[tuple[float, Path]] = []
    try:
        folder = green_checkout.green_root() / FOLDER
        folder_stat = folder.lstat()
        if stat.S_ISLNK(folder_stat.st_mode) or (
            getattr(folder_stat, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
        ):
            return
        if not stat.S_ISDIR(folder_stat.st_mode):
            return
        now = time.time()
        with os.scandir(folder) as entries:
            for entry in entries:
                try:
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    modified = entry.stat(follow_symlinks=False).st_mtime
                except OSError:
                    continue
                path = folder / entry.name
                if _TEMP_NAME.fullmatch(entry.name):
                    if now - modified > _TEMP_AGE:
                        with contextlib.suppress(OSError):
                            if entry.is_file(follow_symlinks=False):
                                path.unlink()
                elif _RECORD_NAME.fullmatch(entry.name):
                    if path == protected:
                        records.append((modified, path))
                    elif now - modified > _RECORD_AGE:
                        with contextlib.suppress(OSError):
                            if entry.is_file(follow_symlinks=False):
                                path.unlink()
                        try:
                            if path.exists():
                                records.append((modified, path))
                        except OSError:
                            pass
                    else:
                        records.append((modified, path))
    except OSError:
        return

    excess = max(0, len(records) - _MAX_RECORDS)
    for _, path in sorted(records, key=lambda item: (item[0], item[1].name)):
        if excess == 0:
            break
        if path == protected:
            continue
        try:
            if not stat.S_ISREG(path.lstat().st_mode):
                continue
            path.unlink()
        except OSError:
            continue
        excess -= 1


def read(name: str) -> frozenset[str]:
    """The tests recorded as failing alone on this key's dev; empty when there is none or it cannot be read.

    Build teams can write the record, so a file too large, or nested too deep to decode, is no record: never an error
    that stops the check.
    """
    if not name:
        return frozenset()
    with _lock:
        try:
            path = _path(name)
            if path.stat().st_size > _MAX_BYTES:
                return frozenset()
            found = json.loads(path.read_text(encoding="utf-8"))
            result = frozenset(str(test) for test in found) if isinstance(found, list) else frozenset()
        except (OSError, ValueError, RecursionError, MemoryError):
            return frozenset()
        if _RECORD_NAME.fullmatch(path.name):
            with contextlib.suppress(OSError, NotImplementedError):
                if stat.S_ISREG(path.lstat().st_mode):
                    os.utime(path)
        _prune(protected=path)
        return result


def remember(name: str, tests: Iterable[str]) -> None:
    """Add *tests* to this key's record. Never raises: a record that cannot be written changes nothing."""
    adding = [str(test) for test in tests]
    if not name or not adding:
        return
    target = _path(name)
    with _lock, contextlib.suppress(OSError):
        target.parent.mkdir(parents=True, exist_ok=True)
        kept = list(dict.fromkeys([*sorted(read(name)), *adding]))[-_KEPT:]
        descriptor, temporary = tempfile.mkstemp(dir=str(target.parent), prefix=".known-", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(kept, handle)
            os.replace(temporary, target)
        finally:
            with contextlib.suppress(OSError):
                os.remove(temporary)
        _prune(protected=target)


__all__ = ["FOLDER", "key", "read", "remember"]
