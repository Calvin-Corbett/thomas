"""The overlay's disk transaction: one lock, hard limits, one atomic write, birth inside it.

A refused write leaves NO trace. The lock lives beside the overlay directory
(`<parent>/<name>.lock`), not inside it, so taking it never creates the
directory; validation and the limits run before anything exists; and the
directory, its birth files and the manifest are created only inside the
locked write of an accepted first record. A link or junction anywhere the
write would touch refuses it (OverlayUnsafe) so a redirected directory can
never carry the user's files somewhere the boundary does not cover.
"""

from __future__ import annotations

import ctypes
import json
import logging
import os
import re
import secrets
import time
from contextlib import contextmanager, suppress
from pathlib import Path

log = logging.getLogger(__name__)

# Lock knobs, read at call time so a test can shrink the retry window.
_LOCK_MAX_RETRIES = 20
_LOCK_RETRY_INTERVAL = 0.25  # seconds
_LOCK_STALE_SECONDS = 30.0
_LOCK_TOKEN = re.compile(r"^[0-9a-f]{32}$")

# Hard limits, read at call time so a test can shrink them. A write that would
# cross any of them refuses as a whole and writes nothing (OverlayLimit); the
# active-override cap is checked on the RESOLVED result, so a clear paired with
# a set in the same write cannot slip past it.
_MAX_RECORDS_PER_APPEND = 200
_MAX_TOTAL_RECORDS = 20000
_MAX_ACTIVE_OVERRIDES = 500
_MAX_MANIFEST_BYTES = 2 * 1024 * 1024

_README = """# Your Thomas overlay

This directory is yours. Stock Thomas reads it on every page load and writes
it only when you act (a Redesign, a theme edit, a rename); nothing else in
Thomas creates, edits or deletes files here, and a stock update never touches
them. `manifest.json` lists every override as an append-only record;
`python -m thomas.server.overlay list` shows what is in effect and
`python -m thomas.server.overlay check` reports anything the current stock no
longer resolves.
"""
BIRTH_FILES = (
    ("README.md", _README),
    (".gitattributes", "manifest.json diff=json\n"),
    (".gitignore", "*.tmp\n"),
)


class OverlayUnsafe(RuntimeError):
    """A path the write would touch is a link or junction; nothing was written."""


class OverlayLimit(RuntimeError):
    """The write would cross a hard limit; nothing was written."""


class OverlayLocked(RuntimeError):
    """The lock could not be taken in time; nothing was written."""


class OverlayWriteFailed(RuntimeError):
    """The disk refused the write; everything this write created was rolled back."""


def lock_path_for(manifest_path: Path) -> Path:
    return manifest_path.parent.parent / f"{manifest_path.parent.name}.lock"


def _is_reparse(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)  # Python 3.12+ on Windows
        return bool(is_junction()) if is_junction else False
    except OSError:
        return True


def guard_boundary(directory: Path, *inside: Path) -> None:
    """Refuse when anything the write touches, or ANY ancestor of it, is a link or junction.

    A junction one level ABOVE the overlay directory sends every byte of the
    write to a tree the contract never describes, so the whole existing
    ancestor chain is checked before anything is created or followed, and
    nothing on it is ever unlinked or repaired. There is no way to turn this
    off: the boundary is the promise the overlay makes, so a redirected path
    is refused rather than followed under any setting.
    """
    seen: set[Path] = set()
    for candidate in (directory, *inside):
        for link in (candidate, *candidate.parents):
            if link in seen:
                continue
            seen.add(link)
            if os.path.lexists(link) and _is_reparse(link):
                raise OverlayUnsafe(f"refusing to write through a link or junction inside the overlay boundary: {link}")


def _create_owned(path: Path, token: str) -> bool:
    """Atomically create a marker whose pid/token identify its sole owner."""
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    try:
        body = json.dumps({"pid": os.getpid(), "token": token}, separators=(",", ":")).encode("ascii")
        os.write(fd, body)
    except OSError:
        path.unlink(missing_ok=True)
        raise
    finally:
        os.close(fd)
    return True


def _read_owner(path: Path) -> dict[str, object] | None:
    try:
        value = json.loads(path.read_text(encoding="ascii"))
    except (OSError, UnicodeError, ValueError):
        return None
    if (not isinstance(value, dict) or set(value) != {"pid", "token"}
            or type(value["pid"]) is not int or value["pid"] <= 0
            or not isinstance(value["token"], str) or not _LOCK_TOKEN.match(value["token"])):
        return None
    return value


def _process_alive(pid: int) -> bool:
    """Fail closed unless the local OS positively says this pid has exited."""
    if pid == os.getpid():
        return True
    if os.name != "nt":
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except (OSError, PermissionError):
            return True
        return True
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return ctypes.get_last_error() != 87  # ERROR_INVALID_PARAMETER means no such process
    try:
        code = ctypes.c_ulong()
        return not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value == 259
    finally:
        kernel32.CloseHandle(handle)


def _release_owned(path: Path, token: str) -> None:
    """Remove only this owner's marker; never unlink a successor by pathname."""
    owner = _read_owner(path)
    if owner is not None and owner["token"] == token:
        path.unlink(missing_ok=True)


def _reap_dead(lock_path: Path) -> bool:
    """Reap an old marker only after serialized, repeated proof its pid is dead."""
    try:
        if time.time() - lock_path.stat().st_mtime <= _LOCK_STALE_SECONDS:
            return False
    except OSError:
        return False
    owner = _read_owner(lock_path)
    if owner is None or _process_alive(int(owner["pid"])):
        return False
    reap_path = lock_path.with_name(lock_path.name + ".reap")
    reap_token = secrets.token_hex(16)
    if not _create_owned(reap_path, reap_token):
        return False
    try:
        current = _read_owner(lock_path)
        if current != owner or current is None or _process_alive(int(current["pid"])):
            return False
        lock_path.unlink(missing_ok=True)
        return True
    finally:
        _release_owned(reap_path, reap_token)


@contextmanager
def locked(lock_path: Path):
    """Owned O_EXCL lock with bounded retries and positive-dead-owner recovery.

    A lock path that is a link or junction is refused outright: it is never
    followed, and the stale break never unlinks it.
    """
    guard_boundary(lock_path.parent, lock_path, lock_path.with_name(lock_path.name + ".reap"))
    made_parent = not lock_path.parent.exists()
    if made_parent:
        lock_path.parent.mkdir(parents=True, exist_ok=True)  # the overlay's parent, outside the boundary
    token = secrets.token_hex(16)
    for attempt in range(_LOCK_MAX_RETRIES):
        try:
            if _create_owned(lock_path, token):
                break
        except OSError as exc:
            raise OverlayLocked(f"overlay lock cannot be created: {lock_path} ({exc})") from exc
        if _reap_dead(lock_path):
            continue
        if attempt == _LOCK_MAX_RETRIES - 1:
            raise OverlayLocked(f"overlay lock is held: {lock_path}") from None
        time.sleep(_LOCK_RETRY_INTERVAL)
    try:
        yield
    finally:
        _release_owned(lock_path, token)
        if made_parent:
            with suppress(OSError):
                lock_path.parent.rmdir()  # succeeds only when this write created nothing


def check_limits(current: int, new: int, active: int, text: str) -> None:
    """Every hard limit, checked before a byte is written."""
    if new > _MAX_RECORDS_PER_APPEND:
        raise OverlayLimit(f"at most {_MAX_RECORDS_PER_APPEND} records per write; nothing was written")
    if current + new > _MAX_TOTAL_RECORDS:
        raise OverlayLimit(f"the manifest would exceed {_MAX_TOTAL_RECORDS} records; nothing was written")
    if active > _MAX_ACTIVE_OVERRIDES:
        raise OverlayLimit(f"{active} active overrides would exceed the cap of {_MAX_ACTIVE_OVERRIDES}; nothing was written")
    if len(text.encode("utf-8")) > _MAX_MANIFEST_BYTES:
        raise OverlayLimit(f"the manifest would exceed {_MAX_MANIFEST_BYTES} bytes; nothing was written")


def write_transaction(manifest_path: Path, text: str, *, birth: bool) -> None:
    """Inside the caller's lock: give birth only now (when asked), then replace the manifest atomically.

    When the disk refuses any step, only what THIS write created is removed
    (the temp file, birth files it wrote, the directory it made); a file that
    was already there is never touched. The refusal is OverlayWriteFailed.
    """
    directory = manifest_path.parent
    tmp = manifest_path.with_name(f"{manifest_path.name}.{os.getpid()}.{secrets.token_hex(2)}.tmp")
    guard_boundary(directory, manifest_path, tmp, *(directory / name for name, _ in BIRTH_FILES))
    created: list[Path] = []
    made_directory = False
    try:
        if birth:
            if not directory.exists():
                directory.mkdir(parents=True)
                made_directory = True
            for name, body in BIRTH_FILES:
                target = directory / name
                try:
                    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                except FileExistsError:
                    continue
                created.append(target)
                os.close(descriptor)
                target.write_text(body, encoding="utf-8", newline="\n")
        descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        created.append(tmp)
        os.close(descriptor)
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, manifest_path)
    except OSError as exc:
        for path in reversed(created):
            try:
                path.unlink()
            except OSError:
                pass
        if made_directory:
            try:
                directory.rmdir()
            except OSError:
                pass
        raise OverlayWriteFailed(f"the overlay write failed and was rolled back: {exc}") from exc
    if birth:
        log.info("overlay created at %s", directory)
