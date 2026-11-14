"""File and lock handling for the board archiver. stdlib only.

The lock follows board_io.py's convention exactly (same file, same O_EXCL create,
same JSON owner record, released only by its own token) so a held lock excludes
message.py, claim writes and this tool from each other. This module never breaks
someone else's lock: a held lock is a refusal, not something to clear.
"""

from __future__ import annotations

import errno
import json
import os
import subprocess
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from scripts.praxis import board_restore

REPLACE_ATTEMPTS = 8
NEWLINE = b"\n"
# Not .md: plan_structure_gate demands that every markdown file under plans/thomas is listed in the
# WORKBOARD and README, which a generated archive can never be.
ARCHIVE_SUFFIX = ".txt"


def iso(now: datetime) -> str:
    return now.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def archive_path(archive_dir: Path, month: str) -> Path:
    return archive_dir / f"messages-{month}{ARCHIVE_SUFFIX}"


def read_state(path: Path) -> board_restore.ArchiveState:
    return board_restore.parse_archive(path.read_bytes() if path.exists() else b"")


class Busy(RuntimeError):
    """Something else owns the board right now; an apply skips instead of failing."""


class LockHeld(Busy):
    """Another writer holds the board lock."""


def git_dirs(root: Path) -> list[Path]:
    """The git directories whose index.lock a commit in this checkout would hold."""
    found: list[Path] = []
    dot_git = root / ".git"
    if dot_git.is_file():  # a linked worktree: ".git" is a file that says "gitdir: <path>"
        text = dot_git.read_text(encoding="utf-8", errors="replace").strip()
        if text.startswith("gitdir:"):
            found.append(Path(text[len("gitdir:") :].strip()))
    elif dot_git.is_dir():
        found.append(dot_git)
    common = canonical_root(root) / ".git"
    return [*found, common] if common.is_dir() and common not in found else found


def busy_reason(root: Path) -> str:
    """Why an apply must wait (a git index.lock is present), or '' when it may proceed."""
    for directory in git_dirs(root):
        if (directory / "index.lock").exists():
            return f"git is busy: {directory / 'index.lock'} exists (a commit or stash is running)"
    return ""


def canonical_root(root: Path) -> Path:
    """The primary checkout, so linked worktrees share one lock (as board_io.py does)."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode == 0:
            common = Path(out.stdout.strip())
            if common.name == ".git" and common.parent.exists():
                return common.parent
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return root


def _owner(lock_file: Path) -> dict[str, object]:
    try:
        payload = json.loads(lock_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


@contextmanager
def board_lock(lock_file: Path, timeout: float) -> Iterator[None]:
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.monotonic() + max(0.0, timeout)
    token = uuid.uuid4().hex
    while True:
        try:
            fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except (FileExistsError, PermissionError):
            if time.monotonic() >= deadline:
                held = _owner(lock_file)
                raise LockHeld(f"board lock {lock_file} is held by pid {held.get('pid', '?')}") from None
            time.sleep(0.05)
    try:
        os.write(fd, json.dumps({"pid": os.getpid(), "token": token, "created_at": time.time()}).encode("utf-8"))
    finally:
        os.close(fd)
    try:
        yield
    finally:
        if _owner(lock_file).get("token") == token:
            try:
                lock_file.unlink()
            except FileNotFoundError:
                pass


def append_bytes(path: Path, data: bytes) -> None:
    """Append and fsync. Archives are append-only; nothing here rewrites a byte.

    A file a killed run left without a final newline gets one first, so the new
    block always starts on its own line and the torn bytes stay a separate, ignored line.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    torn = path.exists() and path.stat().st_size > 0 and path.read_bytes()[-1:] != NEWLINE
    with path.open("ab") as handle:
        if torn:
            handle.write(NEWLINE)
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def atomic_replace(path: Path, data: bytes) -> None:
    """Write beside the target, fsync, then swap in; retries the Windows sharing errors."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.archive.tmp")
    with tmp.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    delay = 0.025
    try:
        for attempt in range(REPLACE_ATTEMPTS):
            try:
                tmp.replace(path)
                return
            except OSError as exc:
                busy = getattr(exc, "winerror", None) in {5, 32} or exc.errno == errno.EACCES
                if not busy or attempt + 1 >= REPLACE_ATTEMPTS:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 0.2)
    finally:
        tmp.unlink(missing_ok=True)


def sweep_stale_temps(board: Path) -> int:
    """Remove temp files a killed run left beside the board (caller holds the lock)."""
    removed = 0
    for tmp in board.parent.glob(f".{board.name}.*.archive.tmp"):
        tmp.unlink(missing_ok=True)
        removed += 1
    return removed
