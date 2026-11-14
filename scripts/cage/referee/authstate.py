"""Small, strict file helpers for the switch's authority state (policy, halt, caps, abuse counts, pipe messages).

Every file the authority layer reads or writes lives under a state folder or a pin folder that the caller passes in.
``checked_root`` refuses a folder that sits under ``ThomasCage`` or ``runtime``: the cage is writable by programs
running as you, so nothing that decides whether Express may land is kept there. Reads are size-limited and accept only
a plain file; JSON is parsed strictly (an object, no repeated key, no NaN). Standard library only.
"""

from __future__ import annotations

import itertools
import json
import os
import secrets
import stat
import threading
from collections.abc import Iterable
from pathlib import Path

NOT_AUTHORITY = frozenset({"thomascage", "runtime"})  # folder names where authority state must never live
_IO = threading.RLock()  # one file operation at a time in this process; the temp name is also unique per write
_COUNTER = itertools.count()


class StateError(RuntimeError):
    """A state or pin file cannot be trusted. ``code`` is a short plain reason for the ledger."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def checked_root(path: Path | str, what: str, forbidden: Iterable[Path | str] = ()) -> Path:
    """The folder as a resolved path, or ``StateError`` when programs running as you could write it.

    Refused: any folder named ThomasCage or runtime on the way down, any name with ``:`` after the drive (an alternate
    data stream such as ``ThomasCage::$DATA``), and anything at or under a ``forbidden`` folder (the service passes the
    repository checkout here).
    """
    resolved = Path(path).resolve()
    if any(part.casefold() in NOT_AUTHORITY for part in resolved.parts):
        raise StateError("root_in_cage", f"{what} must not be under ThomasCage or runtime")
    raw = str(path)
    after_drive = raw[2:] if raw[1:2] == ":" else raw  # "C:" at the start is a drive; any other ':' is a stream name
    if ":" in after_drive or any(":" in part for part in resolved.parts[1:]):
        raise StateError("root_has_stream", f"{what} has a ':' in a folder name")
    for bad in forbidden:
        banned = Path(bad).resolve()
        if resolved == banned or banned in resolved.parents:
            raise StateError("root_in_forbidden", f"{what} must not be inside {banned.name}")
    return resolved


def read_small(path: Path, limit: int) -> bytes | None:
    """The bytes of a plain file of at most ``limit`` bytes; None when there is no such name; ``StateError`` otherwise."""
    with _IO:
        try:
            info = os.lstat(path)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise StateError("unreadable", str(exc)) from exc
        if not stat.S_ISREG(info.st_mode):
            raise StateError("not_a_plain_file", path.name)
        if info.st_size > limit:
            raise StateError("too_large", path.name)
        try:
            with open(path, "rb") as handle:
                data = handle.read(limit + 1)
        except OSError as exc:
            raise StateError("unreadable", str(exc)) from exc
    if len(data) > limit:
        raise StateError("too_large", path.name)
    return data


def write_atomic(path: Path, data: bytes) -> None:
    """Write then rename, with an fsync of the file, so a reader sees the old bytes or the new ones.

    The temporary name is unique per write (process, counter, random) and writes in this process never overlap.
    """
    tmp = path.with_name(f"{path.name}.{os.getpid()}.{next(_COUNTER)}.{secrets.token_hex(4)}.tmp")
    with _IO:
        try:
            with open(tmp, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


def _no_repeats(pairs: list[tuple[str, object]]) -> dict:
    out: dict = {}
    for key, value in pairs:
        if key in out:
            raise ValueError(f"repeated key {key!r}")
        out[key] = value
    return out


def _no_constant(name: str) -> object:
    raise ValueError(f"{name} is not allowed")


def strict_object(raw: bytes) -> dict:
    """A JSON object from UTF-8 bytes, or ``StateError('garbled')``."""
    try:
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_repeats, parse_constant=_no_constant)
    except (ValueError, RecursionError) as exc:  # UnicodeDecodeError is a ValueError
        raise StateError("garbled", str(exc)[:80]) from exc
    if not isinstance(data, dict):
        raise StateError("garbled", "not a JSON object")
    return data
