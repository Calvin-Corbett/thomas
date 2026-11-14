"""Machine facts for scripts/fast_tests.py: how many workers fit, and which bytecode folder belongs to this tree.

Standard library only. Nothing here imports Thomas.
"""

from __future__ import annotations

import ctypes
import hashlib
import os
import shutil
import subprocess
from pathlib import Path

GB = 1024**3
PER_WORKER_BYTES = 600 * 1024 * 1024  # a worker held 250-300 MB on the 2026-10-03 samples; headroom on top
RESERVE_FLOOR_BYTES = 4 * GB
RESERVE_FRACTION = 0.12
MAX_WORKERS = 8
KEEP_PREFIXES = 4


def memory_bytes() -> tuple[int | None, int | None]:
    """(total, available) physical memory, or None for what this platform will not say."""
    if os.name == "nt":
        return _windows_memory()
    try:
        fields: dict[str, int] = {}
        with open("/proc/meminfo", encoding="ascii") as handle:
            for line in handle:
                key, _, rest = line.partition(":")
                if key in ("MemTotal", "MemAvailable"):
                    fields[key] = int(rest.split()[0]) * 1024
        return fields.get("MemTotal"), fields.get("MemAvailable")
    except (OSError, ValueError, IndexError):
        return None, None


def _windows_memory() -> tuple[int | None, int | None]:
    class _Status(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = _Status()
    status.dwLength = ctypes.sizeof(_Status)
    try:
        ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))  # type: ignore[attr-defined]
    except (AttributeError, OSError):
        return None, None
    return (int(status.ullTotalPhys), int(status.ullAvailPhys)) if ok else (None, None)


def pick_workers(
    requested: int | None, *, cpus: int, total: int | None, available: int | None, files: int | None = None
) -> tuple[int, str]:
    """Worker count and the reason it is that many. Never more than asked, never more than the machine holds."""
    ceiling = min(MAX_WORKERS, max(1, cpus // 2))
    reason = f"cpus={cpus} -> at most {ceiling}"
    if available is not None and total is not None:
        usable = available - max(RESERVE_FLOOR_BYTES, int(total * RESERVE_FRACTION))
        by_ram = max(1, usable // PER_WORKER_BYTES)
        if by_ram < ceiling:
            ceiling, reason = int(by_ram), f"free RAM {available / GB:.1f} GB -> at most {by_ram}"
    if files is not None and files < ceiling:
        ceiling, reason = max(1, files), f"only {files} file(s) to run"
    if requested is not None and requested < ceiling:
        ceiling, reason = max(1, requested), "as asked (-n)"
    return int(max(1, ceiling)), reason


def short_root_warning(root: Path, limit: int = 60) -> str | None:
    """Deep checkouts make Windows tests fail with 'Filename too long' (9 of 11 serial failures in one slice)."""
    if len(str(root)) <= limit:
        return None
    # Name no folder: C:\r is owner-only now, and a caged Build team cannot choose where its copy lives.
    return (
        f"the checkout path is {len(str(root))} characters; a test that fails with 'Filename too long' "
        "fails on the path, not the code (a short folder avoids it)"
    )


class GitUnavailable(RuntimeError):
    """git failed or is missing: the tree cannot be named, so no cache may be shared."""


def _git(root: Path, *args: str) -> str:
    try:
        done = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)  # noqa: S603, S607
    except OSError as exc:
        raise GitUnavailable(str(exc)) from exc
    if done.returncode != 0:
        raise GitUnavailable(done.stderr.strip() or f"git {' '.join(args)} exited {done.returncode}")
    return done.stdout


def tree_key(root: Path) -> str | None:
    """Names this exact tree: the HEAD tree plus the bytes of every changed or new file. 16 hex characters.

    Returns None when git cannot say (not a repository, dubious ownership, git missing): a constant key would make
    every such tree share one bytecode folder, so the caller runs without a cache instead.

    Bytecode is validated by file time and size, and a same-size rewrite inside one second runs stale code (19 of 40
    rewrites in the 2026-10-03 test), so a cache is never shared between two different trees.
    """
    try:
        digest = hashlib.sha256(_git(root, "rev-parse", "HEAD^{tree}").strip().encode())
        changed = set(_git(root, "diff", "HEAD", "--name-only").splitlines())
        changed |= set(_git(root, "ls-files", "--others", "--exclude-standard").splitlines())
    except GitUnavailable:
        return None
    for name in sorted(changed):
        digest.update(name.encode())
        try:
            digest.update(hashlib.sha256((root / name).read_bytes()).digest())
        except OSError:
            digest.update(b"<gone>")
    return digest.hexdigest()[:16]


def prune_prefixes(cache_dir: Path, keep_name: str) -> list[str]:
    """Delete all but the newest few bytecode folders, so the cache cannot grow without bound."""
    folders = sorted((p for p in (cache_dir / "pyc").glob("*") if p.is_dir()), key=lambda p: p.stat().st_mtime)
    gone = [p.name for p in folders[:-KEEP_PREFIXES] if p.name != keep_name]
    for name in gone:
        shutil.rmtree(cache_dir / "pyc" / name, ignore_errors=True)
    return gone
