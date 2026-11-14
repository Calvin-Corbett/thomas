"""Windows Search leaves Thomas's own busy folders alone (2026-10-28).

On your PC Windows Search used 18-19% of the processor re-indexing files Thomas writes every few seconds: the
checkout's ``runtime`` (575,360 files) and ``.thomas`` (4,701 files, 699 MB) are inside the indexed scope (measured
2026-10-28). A product cannot ask you to stop Windows Search. Every folder here gets ``FILE_ATTRIBUTE_NOT_CONTENT_INDEXED``,
which any account may set on its own folders, no administrator needed, and a file or folder made inside one inherits
it, so nothing Thomas writes there later is indexed. Only folders are marked; a file already indexed keeps its entry.
Indexing is all it changes: nothing is hidden, locked or excluded from Defender.

A root is walked once: ``.unindexed`` in it records that every folder it held was marked, and later starts mark the
root alone (folders made since inherited the mark). Never raises: a folder that cannot be marked is left as it was.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterable
from pathlib import Path

log = logging.getLogger(__name__)

NOT_CONTENT_INDEXED = 0x2000  # FILE_ATTRIBUTE_NOT_CONTENT_INDEXED
DONE = ".unindexed"
WINDOWS = os.name == "nt"


def _mark(folder: str) -> bool:
    """Add the attribute to *folder*; True when it has it afterwards."""
    try:
        attributes = os.stat(folder, follow_symlinks=False).st_file_attributes
    except (OSError, AttributeError):
        return False
    if attributes & NOT_CONTENT_INDEXED:
        return True
    import ctypes

    return bool(ctypes.windll.kernel32.SetFileAttributesW(folder, attributes | NOT_CONTENT_INDEXED))


def _linked(path: str) -> bool:
    return os.path.islink(path) or bool(getattr(os.path, "isjunction", lambda _path: False)(path))


def mark_folders(roots: Iterable[Path]) -> list[str]:
    """Mark every folder under each existing root (once per root), or the root alone once it was walked; the roots
    walked this time. A folder this account may not mark is counted in the log, not walked for again at every start:
    the runtime folder alone holds 575,360 files."""
    walked: list[str] = []
    if not WINDOWS:
        return walked
    for root in roots:
        top = str(root)
        if not os.path.isdir(top) or not _mark(top):
            continue
        done = os.path.join(top, DONE)
        if os.path.exists(done):
            continue
        refused = 0
        for folder, children, _files in os.walk(top, onerror=lambda _exc: None):
            # A link or junction is not followed: its target is not Thomas's to mark.
            children[:] = [name for name in children if not _linked(os.path.join(folder, name))]
            refused += sum(not _mark(os.path.join(folder, name)) for name in children)
        if refused:
            log.info("%d folders under %s could not be marked not to be indexed", refused, top)
        try:
            Path(done).write_text("every folder here this account may mark was marked not to be indexed\n", "utf-8")
        except OSError:
            log.debug("could not record that %s was marked not to be indexed", top)
        walked.append(top)
    return walked


def thomas_folders() -> list[Path]:
    """The folders Thomas keeps rewriting: the checkout's ``runtime`` and ``.thomas``, and his data folder."""
    from thomas.core.config import resolve_thomas_data_dir

    checkout = Path(__file__).resolve().parents[2]
    return [checkout / "runtime", checkout / ".thomas", Path(resolve_thomas_data_dir())]


__all__ = ["DONE", "NOT_CONTENT_INDEXED", "mark_folders", "thomas_folders"]
