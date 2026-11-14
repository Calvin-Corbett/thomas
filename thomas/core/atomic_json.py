"""Write a JSON file so that two writers never share a temporary file.

Presence files were written as ``<name>.json.tmp`` then renamed. Every writer
used the SAME temporary name, so two agents writing at once opened one file
(WinError 32 / Errno 13 on Windows) and the claim tool reported "presence gate
failed". Measured with ten simulated agents: one to two claims failed per run
this way. A unique temporary name per write removes the shared file; the rename
itself is retried briefly because Windows refuses to replace a file that a
reader has open at that instant.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

REPLACE_ATTEMPTS = 8
REPLACE_BACKOFF_SECONDS = 0.02


def temp_path_for(path: Path) -> Path:
    """A temporary sibling that is unique to this process and this call."""

    return path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex[:12]}.tmp")


def _replace_with_retry(tmp: Path, path: Path) -> None:
    for attempt in range(REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            # A concurrent reader holds the target open (Windows). The target
            # is not ours to force; wait a moment and try again, then give up
            # loudly rather than leave a half state.
            if attempt == REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(REPLACE_BACKOFF_SECONDS * (attempt + 1))


def read_text_with_retry(path: Path) -> str:
    """The file's text, waiting out a writer: Windows refuses a read too while the file is being replaced.

    Measured under contention, 8% of plain reads failed this way. A caller that takes any read error for "nothing
    there" then acted on that moment as an empty file, and a write that followed kept the emptiness.
    """

    for attempt in range(1, REPLACE_ATTEMPTS):
        try:
            return path.read_text(encoding="utf-8")
        except PermissionError:
            time.sleep(REPLACE_BACKOFF_SECONDS * attempt)
    return path.read_text(encoding="utf-8")


def write_json_atomic(path: Path, payload: Any) -> None:
    """Replace ``path`` with ``payload`` as JSON; never leaves a partial file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = temp_path_for(path)
    replaced = False
    try:
        tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        _replace_with_retry(tmp, path)
        replaced = True
    finally:
        # Do not strand the temporary file in the presence directory.
        if not replaced:
            tmp.unlink(missing_ok=True)
