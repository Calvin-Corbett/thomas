"""File primitives for the ticket store: tolerant JSON reads, atomic replace, numbered create-without-overwrite."""

from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPLACE_TRIES = 25
READ_TRIES = 4


def digest(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def read_state(path: Path, tries: int = 1) -> tuple[str, dict[str, Any] | None]:
    """("ok", data) | ("missing", None) | ("bad", None). A file that exists but cannot be read right now (a writer is
    replacing it, a sharing violation on Windows) is "bad", never "missing": it is retried, then reported as it is."""
    for attempt in range(max(1, tries)):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return "missing", None
        except (OSError, ValueError):
            time.sleep(0.005 * (attempt + 1))
            continue
        return ("ok", data) if isinstance(data, dict) else ("bad", None)
    return "bad", None


def read_json(path: Path, tries: int = 1) -> dict[str, Any] | None:
    return read_state(path, tries)[1]


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:10]}.tmp")
    tmp.write_text(text, encoding="utf-8")
    for attempt in range(REPLACE_TRIES):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # a reader has the target open (Windows); wait and retry
            if attempt == REPLACE_TRIES - 1:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(min(0.02 * (attempt + 1), 0.1))


def numbers(folder: Path, prefix: str) -> list[int]:
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    # Any number of digits: the six-digit format is only a minimum width, and a numbered file past 999999 must still be read.
    return sorted(int(x[1:-5]) for x in names if x.startswith(prefix) and x.endswith(".json") and x[1:-5].isdigit())


def create_numbered(folder: Path, prefix: str, build: Callable[[int], bytes], start: int) -> tuple[int, bytes]:
    """Create ``<prefix><n>.json`` for the first free n >= start, WITH its content, atomically: the content goes to a
    temporary file that is hard-linked into place, so a crash can never leave an empty numbered file, and the link fails
    if the number is taken. Only an existing file means "taken": any other OS error is raised, never read as "taken"."""
    folder.mkdir(parents=True, exist_ok=True)
    n = max(start, 1)
    for _ in range(5000):
        payload = build(n)
        tmp = folder / f".{prefix}{os.getpid()}.{uuid.uuid4().hex[:10]}.tmp"
        tmp.write_bytes(payload)
        try:
            os.link(tmp, folder / f"{prefix}{n:06d}.json")
            return n, payload
        except FileExistsError:
            n += 1
        finally:
            tmp.unlink(missing_ok=True)
    raise OSError(f"no free slot in {folder}")
