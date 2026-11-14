"""A place's git files, read without trusting the place: the refusal, the plain-folder check and small-file reads.

Every read goes through the no-follow seam with each folder above the file held (``places.read_in_place``). Part of
``gitplace`` (see its notes), which re-exports these names.
"""

from __future__ import annotations

import os
from pathlib import Path

from scripts.cage.referee.nofollow import UnsafeEntry

from .places import read_in_place


class Unreadable(Exception):
    """The place cannot be read safely; the message says why in words you can act on."""


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(str(path))).rstrip("\\/")


def _plain_folder(fs, path: Path) -> None:
    try:
        with fs.hold_dir(path):
            pass
    except UnsafeEntry as exc:
        raise Unreadable(f"{path} is not a plain folder ({exc.code})") from exc
    except OSError as exc:
        raise Unreadable(f"{path} could not be opened ({exc})") from exc


def small(fs, path: Path, limit: int = 1 << 16) -> bytes | None:
    """A small git file read through the no-follow seam with every folder above it held; None when absent."""
    try:
        return read_in_place(fs, path.parent, path.name, limit)[0]
    except UnsafeEntry as exc:
        if exc.code == "missing":
            return None
        raise Unreadable(f"{path} was refused ({exc.code})") from exc
    except FileNotFoundError:
        return None
