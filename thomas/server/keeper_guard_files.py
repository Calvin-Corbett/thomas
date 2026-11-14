"""Write exclusive keeper files, sync them and check their SHA-256 by reading back."""

from __future__ import annotations

import hashlib
import io
import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import BinaryIO, Iterator

__all__ = ["CHUNK", "remove", "new_file", "write_all", "read_back"]
CHUNK = 1024 * 1024
log = logging.getLogger(__name__)
_warned_read = False


def remove(path: Path, what: str) -> bool:
    """Remove an existing file, warning if it cannot be removed."""
    try:
        path.unlink(missing_ok=True)
        return True
    except OSError:
        log.warning("could not remove %s %s", what, path, exc_info=True)
        return False


@contextmanager
def new_file(path: Path) -> Iterator[BinaryIO]:
    """Create exclusively; sync on success and clean a partial write on failure."""
    try:
        handle = open(path, "xb+", buffering=0)
    except PermissionError:
        handle = open(path, "xb")
    complete = False
    try:
        yield handle
        handle.flush()
        os.fsync(handle.fileno())
        complete = True
    finally:
        try:
            handle.close()
        finally:
            if not complete:
                remove(path, "partial capture")


def write_all(handle: BinaryIO, data: bytes) -> None:
    """Write all bytes even if the stream accepts only a portion per call."""
    view = memoryview(data)
    while view:
        count = handle.write(view)
        if count is None or count <= 0:
            raise OSError("incomplete keeper write")
        view = view[count:]


def read_back(handle: BinaryIO) -> str | None:
    """Hash what was written; create-only handles cannot be read back."""
    global _warned_read
    digest = hashlib.sha256()
    try:
        handle.seek(0)
        while data := handle.read(CHUNK):
            digest.update(data)
    except (PermissionError, io.UnsupportedOperation):
        if not _warned_read:
            log.warning("keeper file is create-only; cannot read back its hash")
            _warned_read = True
        return None
    return digest.hexdigest()
