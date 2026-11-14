"""Answer a test run that was already made on unchanged work, instead of running it again.

``check.run`` asks here before it starts pytest. A run is the same question when the command is the same and the
project is in the same state: the same commit, and the same content in every file that is modified or new. Then the
earlier result is the answer, marked as a repeat, and nothing is started. Measured 2026-11-09 on one PC: 27 of about
210 pytest calls in four hours were such repeats, about 2.6 hours of tests that could only say what was known.

The state is read with two git calls and the content of the files git lists as changed, so it costs a fraction of a
second where a run costs minutes. A folder that is not a git project has no state here and always runs. Results are
kept in the data folder, one small file for each project, so another agent on the same project gets the answer too.
Nothing here raises: when anything cannot be read, the tests simply run.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from thomas.core import atomic_json

KEEP = 60
MAX_AGE_S = 6 * 3600.0
_GIT_S = 20.0
_WHOLE_FILE_BYTES = 2 * 1024 * 1024
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _git(root: Path, env: dict[str, str] | None, *args: str) -> bytes | None:
    try:
        done = subprocess.run(
            # A read of the state runs no program the project names and writes nothing: core.fsmonitor can name
            # one, and without --no-optional-locks a status refreshes the index another agent may be using.
            [
                "git",
                "--no-optional-locks",
                "-C",
                str(root),
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.quotepath=off",
                *args,
            ],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            timeout=_GIT_S,
            check=False,
            env=env,
            creationflags=_NO_WINDOW,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


_BYPRODUCTS = frozenset({"__pycache__", ".pytest_cache"})


def _byproduct(entry: bytes) -> bool:
    """A file a test run writes on its own, which says nothing about the project: bytecode and pytest's cache."""
    return len(entry) >= 4 and not _BYPRODUCTS.isdisjoint(os.fsdecode(entry[3:]).split("/"))


def fingerprint(root: Path, env: dict[str, str] | None = None) -> str | None:
    """One value for the state of the project: its commit and every changed or new file's content. None when git
    cannot say, which means "do not reuse"."""
    head = _git(root, env, "rev-parse", "HEAD")
    status = _git(root, env, "status", "--porcelain=v1", "-z", "--untracked-files=all") if head is not None else None
    if head is None or status is None:
        return None
    digest = hashlib.blake2b(digest_size=20)
    entries = status.split(b"\0")
    kept = [entry for entry in entries if not _byproduct(entry)]
    if len(kept) != len(entries):  # so a run's own bytecode never makes the project look edited
        status = b"\0".join(kept)
    digest.update(head)
    digest.update(status)
    for entry in kept:
        if len(entry) < 4:
            continue
        path = Path(root) / os.fsdecode(entry[3:])
        try:
            size = path.stat().st_size
            if size > _WHOLE_FILE_BYTES:  # a large file is told apart by its size and time, not read whole
                digest.update(f"{size}:{path.stat().st_mtime_ns}".encode())
            elif path.is_file():
                digest.update(hashlib.blake2b(path.read_bytes(), digest_size=16).digest())
        except OSError:
            digest.update(b"gone")
    return digest.hexdigest()


def key_of(argv: list[str]) -> str:
    return hashlib.blake2b(json.dumps(argv).encode("utf-8"), digest_size=16).hexdigest()


def _file(folder: Path, root: Path) -> Path:
    name = hashlib.blake2b(os.path.normcase(str(root)).encode("utf-8"), digest_size=12).hexdigest()
    return Path(folder) / f"{name}.json"


def _entries(path: Path) -> dict[str, Any]:
    try:
        found = json.loads(atomic_json.read_text_with_retry(path)).get("entries")
    except (OSError, ValueError, AttributeError):
        return {}
    return found if isinstance(found, dict) else {}


def _ago(seconds: float) -> str:
    seconds = max(0, int(seconds))
    return f"{seconds} s" if seconds < 90 else f"{seconds // 60} min"


def recall(folder: Path, root: Path, key: str, state: str, *, now: float | None = None) -> dict[str, Any] | None:
    """The earlier result for this command on this exact state, marked as a repeat; None when there is none."""
    now = time.time() if now is None else now
    entry = _entries(_file(folder, root)).get(key)
    if not isinstance(entry, dict) or entry.get("state") != state or not isinstance(entry.get("data"), dict):
        return None
    age = now - float(entry.get("at") or 0)
    if not 0 <= age <= MAX_AGE_S:
        return None
    return {
        **entry["data"],
        "reused": (
            f"This is the result from {_ago(age)} ago: nothing in the project has changed since, so the tests were "
            "not run again. Change a file and they run; pass fresh: true to run them now."
        ),
    }


def remember(folder: Path, root: Path, key: str, state: str, data: dict[str, Any], *, now: float | None = None) -> None:
    """Keep this result as the answer for this command on this state. The newest ``KEEP`` are kept."""
    now = time.time() if now is None else now
    path = _file(folder, root)
    entries = _entries(path)
    entries[key] = {"state": state, "at": now, "data": data}
    newest = sorted(entries.items(), key=lambda item: -float(item[1].get("at") or 0))[:KEEP]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_json.write_json_atomic(path, {"entries": dict(newest)})
    except (OSError, TypeError, ValueError):
        return


__all__ = ["KEEP", "MAX_AGE_S", "fingerprint", "key_of", "recall", "remember"]
