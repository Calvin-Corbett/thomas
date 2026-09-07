"""Publish text over a board file with the replace-with-retry the message writer uses.

A bare ``tmp.replace(path)`` in the claim writer lost the rename race twelve
times on 2026-09-05 (WinError 5 while another process had the board open) and
left a 1.3 MB temp copy behind each time; message sends, which retry, never
lost it. Lives beside claim_utils.py because that file sits at its size baseline.
"""

from __future__ import annotations

import os
from contextlib import suppress
from pathlib import Path


def publish_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        from board_io import _replace_with_retry
    except ImportError:  # imported as a package module rather than from its folder
        from scripts.crew.workboard.board_io import _replace_with_retry
    try:
        _replace_with_retry(tmp, path)
    except OSError as exc:
        # Another process holds the board open with delete sharing: a rename
        # over it is denied for as long as it does, while an in-place write
        # (what message.py has always done) goes through. Same board, same
        # bytes, atomicity traded for landing at all.
        if getattr(exc, "winerror", None) not in {5, 32}:
            raise
        path.write_text(text, encoding="utf-8")
    finally:
        with suppress(FileNotFoundError):
            tmp.unlink()


__all__ = ["publish_text"]
