"""Offline checks BootDoctor runs before it touches anything.

The startup probe only asks whether the port answers. A database that will not
open, a ``thomas.toml`` that will not parse and a folder Thomas cannot write to
all stop a start while the port stays free, so each gets its own look here.

No check changes what is stored in a database or a config file. Two side
effects are left: ``check_writable`` creates and removes a probe file, and
SQLite can leave empty ``-wal`` and ``-shm`` files beside a WAL-mode database
it opened read-only. ``quarantine_corrupt`` is the one function that moves a
file, and it only runs when a caller asks for it by name.
"""

from __future__ import annotations

import http.client
import json
import os
import re
import sqlite3
import sys
import time
import urllib.request
from collections.abc import Iterable
from pathlib import Path

from thomas.core.config import resolve_thomas_data_dir

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - python 3.10 ships tomli as a dependency
    import tomli as tomllib

# (check, status, detail) -- the shape BootDoctorResult.add() takes.
Row = tuple[str, str, str]

_DB_SUFFIXES = (".sqlite3", ".sqlite", ".db")
_SKIP_DIRS = frozenset({".git", ".venv", "node_modules", "__pycache__", "artifacts", "downloads", "wheelhouse_cache"})
_SCAN_DEPTH = 3
_MAX_DATABASES = 60
# quick_check reads the whole file, so a very large one (or one past the total budget)
# only gets its header checked. BootDoctor runs while someone waits on a failed start.
_QUICK_CHECK_MAX_BYTES = 128 * 1024 * 1024
_QUICK_CHECK_TOTAL_BYTES = 512 * 1024 * 1024
_SQLITE_MAGIC = b"SQLite format 3\x00"

# Known ways a start dies, matched against the last _CLASSIFY_LINES lines of a probe log. A handled error early in
# a log (a PermissionError the server retried past) is not why the server stopped.
_CLASSIFY_LINES = 50
_LOG_SIGNATURES = (
    (
        re.compile(r"DatabaseError: (file is not a database|database disk image is malformed)", re.I),
        "a Thomas database file is damaged",
    ),
    (re.compile(r"TOMLDecodeError", re.I), "thomas.toml does not parse"),
    (
        re.compile(r"WinError 10013|Errno 10013|forbidden by its access permissions", re.I),
        "the port is blocked by Windows (a reserved port range or a permissions rule)",
    ),
    # A refused bind also raises PermissionError; that is the port's problem, not a folder's.
    (
        re.compile(r"PermissionError(?!.*(?:10013|bind on address|forbidden by its access permissions))", re.I),
        "a file or folder Thomas needs is not writable",
    ),
    (
        re.compile(
            r"WinError 10048|Errno 10048|address already in use|Errno 98\b|only one usage of each socket address", re.I
        ),
        "the port is already taken by another program",
    ),
    (re.compile(r"ModuleNotFoundError: No module named '([\w.]+)'"), "a Python package is missing ({0})"),
)


def config_file_path(root: Path, explicit: Path | str | None = None) -> Path:
    """The thomas.toml Thomas would read: --config, THOMAS_CONFIG, then <root>/thomas.toml."""
    if explicit and str(explicit).strip():
        return Path(explicit).expanduser().resolve()
    env_value = str(os.environ.get("THOMAS_CONFIG") or "").strip()
    if env_value:
        return Path(env_value).expanduser().resolve()
    return (Path(root) / "thomas.toml").resolve()


def check_config_file(path: Path) -> Row:
    """Parse the config file and name the file and line when it will not."""
    if not path.exists():
        return ("config_file", "ok", f"{path} not present; built-in defaults apply")
    try:
        with path.open("rb") as fh:
            tomllib.load(fh)
    except tomllib.TOMLDecodeError as exc:
        # tomllib's message ends "(at line N, column M)" but never names the file.
        return ("config_file", "fail", f"{path}: {exc}")
    except UnicodeDecodeError as exc:
        return ("config_file", "fail", f"{path}: not valid UTF-8 text ({exc})")
    except OSError as exc:
        return ("config_file", "fail", f"{path}: cannot be read ({type(exc).__name__}: {exc})")
    return ("config_file", "ok", f"{path} parses")


def _dedupe(paths: Iterable[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = os.path.normcase(str(path))
        if key not in seen:
            seen.add(key)
            out.append(path)
    return out


def state_bases(root: Path, memory_root: Path | None = None) -> list[Path]:
    """The folders Thomas keeps its state in."""
    bases: list[Path] = []
    if memory_root is not None:
        bases.append(Path(memory_root))
    env_memory = str(os.environ.get("THOMAS_MEMORY_ROOT") or "").strip()
    if env_memory:
        bases.append(Path(env_memory).expanduser())
    try:
        data_dir: Path | None = resolve_thomas_data_dir()
    except ValueError:
        data_dir = None  # a bad THOMAS_PROFILE is the server's to report; skip the data dir here
    if data_dir is not None:
        bases.append(data_dir)
    bases.append(Path(root) / "runtime")
    return _dedupe(path.resolve() for path in bases)


def _database_files(bases: Iterable[Path]) -> list[Path]:
    """Database files in the state folders only, never a walk of the whole checkout."""
    found: list[Path] = []
    for base in bases:
        try:
            found.extend(p for p in base.iterdir() if p.is_file() and p.name.lower().endswith(_DB_SUFFIXES))
        except OSError:
            continue  # missing or unreadable folder; the writable check reports it
        for sub in (base / ".thomas", base / "runtime"):
            if not sub.is_dir():
                continue
            for current, dirs, files in os.walk(sub):
                dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
                if len(Path(current).parts) - len(sub.parts) >= _SCAN_DEPTH:
                    dirs[:] = []
                found.extend(Path(current) / name for name in files if name.lower().endswith(_DB_SUFFIXES))
    for key, value in os.environ.items():
        if key.startswith("THOMAS_") and key.endswith(("_DB_PATH", "_SQLITE_PATH")) and str(value).strip():
            candidate = Path(value).expanduser()
            if candidate.is_file():
                found.append(candidate.resolve())
    return _dedupe(found)[:_MAX_DATABASES]


def database_state(path: Path, *, full_check: bool = True) -> tuple[str, str]:
    """Return (``ok`` | ``corrupt`` | ``suspect`` | ``unreadable``, detail) without writing to the file."""
    try:
        size = path.stat().st_size
        with path.open("rb") as fh:
            head = fh.read(len(_SQLITE_MAGIC))
    except OSError as exc:
        return "unreadable", f"{type(exc).__name__}: {exc}"
    if size == 0:
        return "ok", "empty file"
    if head != _SQLITE_MAGIC:
        if path.name.lower().endswith(".db"):
            # ".db" is also what other programs use, so this is a warning, never a file to move aside.
            return "suspect", "not a SQLite file"
        return "corrupt", "file is not a database"
    if not full_check:
        return "ok", "header is valid; too large for a full integrity check"
    try:
        con = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=2.0)
        try:
            rows = con.execute("PRAGMA quick_check(1)").fetchall()
        finally:
            con.close()
    except sqlite3.OperationalError as exc:
        # Locked or not openable read-only: not proof the file is damaged.
        return "unreadable", str(exc)
    except sqlite3.DatabaseError as exc:
        return "corrupt", str(exc)
    verdict = str(rows[0][0]) if rows else ""
    if verdict.lower() == "ok":
        return "ok", "integrity ok"
    return "corrupt", verdict or "integrity check returned nothing"


def check_writable(path: Path) -> Row:
    """Test-write into the folder (or the nearest existing parent) and remove the probe file."""
    target = Path(path)
    while not target.exists() and target.parent != target:
        target = target.parent
    if not target.is_dir():
        return ("state_dir_writable", "fail", f"{path}: {target} is a file, not a folder")
    probe = target / f".bootdoctor_write_{os.getpid()}"
    try:
        probe.write_bytes(b"")
        probe.unlink()
    except OSError as exc:
        return ("state_dir_writable", "fail", f"{path}: cannot write ({type(exc).__name__}: {exc})")
    return ("state_dir_writable", "ok", f"{path} is writable")


def run_offline_checks(
    root: Path,
    *,
    memory_root: Path | None = None,
    config_path: Path | str | None = None,
) -> tuple[list[Row], list[Path]]:
    """Run every offline check; return the findings and the corrupt database files."""
    rows: list[Row] = [check_config_file(config_file_path(root, config_path))]
    bases = state_bases(root, memory_root)
    rows.extend(check_writable(base) for base in bases)

    corrupt: list[Path] = []
    files = _database_files(bases)
    budget = _QUICK_CHECK_TOTAL_BYTES
    for path in files:
        try:
            size = path.stat().st_size
        except OSError:
            size = 0  # database_state reports the unreadable file
        full_check = size <= min(_QUICK_CHECK_MAX_BYTES, budget)
        if full_check:
            budget -= size
        state, detail = database_state(path, full_check=full_check)
        if state == "corrupt":
            corrupt.append(path)
            rows.append(("database_integrity", "fail", f"{path}: {detail}"))
        elif state in ("unreadable", "suspect"):
            rows.append(("database_integrity", "warn", f"{path}: {detail}"))
    if not corrupt:
        rows.append(("database_integrity", "ok", f"{len(files)} database file(s) checked; none damaged"))
    return rows, corrupt


def quarantine_corrupt(paths: Iterable[Path]) -> list[str]:
    """Move damaged database files aside (never delete) so Thomas can create fresh ones."""
    stamp = time.strftime("%Y%m%d_%H%M%S")
    notes: list[str] = []
    for path in paths:
        target = path.with_name(f"{path.name}.corrupt-{stamp}")
        try:
            path.rename(target)
        except OSError as exc:
            notes.append(f"could not move {path} ({type(exc).__name__}: {exc}); close Thomas and try again")
            continue
        notes.append(f"moved {path} to {target}")
        for suffix in ("-wal", "-shm", "-journal"):
            side = path.with_name(path.name + suffix)
            if side.exists():
                try:
                    side.rename(target.with_name(target.name + suffix))
                except OSError as exc:
                    notes.append(f"left {side} in place ({type(exc).__name__}: {exc})")
    return notes


def classify_startup_log(text: str) -> list[str]:
    """Name the likely cause of a failed start from known signatures in the end of its log."""
    tail = "\n".join(log_tail(text, _CLASSIFY_LINES))
    causes: list[str] = []
    for pattern, cause in _LOG_SIGNATURES:
        match = pattern.search(tail)
        if match:
            causes.append(cause.format(*match.groups()) if match.groups() else cause)
    return causes


def log_tail(text: str, lines: int = 15) -> list[str]:
    """The last non-empty lines of a log."""
    rows = [row.rstrip() for row in str(text or "").splitlines() if row.strip()]
    return rows[-lines:]


def answers_as_thomas(host: str, port: int, timeout: float = 1.5) -> bool:
    """True only when /api/health returns Thomas's own payload, not merely any listener."""
    url = f"http://{host}:{int(port)}/api/health"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as resp:
            body = json.loads(resp.read(65536).decode("utf-8", errors="replace"))
    except (http.client.HTTPException, OSError, ValueError):
        return False
    return isinstance(body, dict) and "status" in body and "version" in body
