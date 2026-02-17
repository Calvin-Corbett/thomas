"""Doppelganger Protocol (blue/green) utilities.

This module implements a pragmatic, local-first blue/green workflow:
- Blue: the primary working tree (the user's normal Thomas)
- Green: an isolated sandbox copy used to stage risky changes

Key goals:
- Avoid in-place edits of a running instance for risky changes.
- Keep runtime data (memory, secrets, indices) out of promotion sync.
- Support code pruning by allowing deletions during promotion.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess  # nosec
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

log = logging.getLogger(__name__)


_INCLUDE_DIRS = ("thomas", "scripts", "tests", "definitions")
_INCLUDE_FILES = (
    "pyproject.toml",
    "README.md",
    "CHANGELOG.md",
    "thomas.toml",
    "run-ui.cmd",
    "run-repl.cmd",
    ".gitignore",
    "SOUL.md",
)

_IGNORE_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".DS_Store",
}


@dataclass(frozen=True)
class DoppelgangerPaths:
    blue_root: Path
    dg_root: Path
    green_root: Path
    green_runtime: Path
    green_venv: Path
    backups_root: Path


def _is_windows() -> bool:
    return os.name == "nt"


def _venv_python(venv_dir: Path) -> Path:
    if _is_windows():
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def find_project_root(start: Optional[Path] = None) -> Path:
    """Find the Thomas project root.

    Heuristics:
    - Walk upwards from cwd (or provided start).
    - Look for pyproject.toml + thomas/ package dir.
    """
    p = (start or Path.cwd()).resolve()
    for _ in range(10):
        if (p / "pyproject.toml").is_file() and (p / "thomas").is_dir():
            return p
        if p.parent == p:
            break
        p = p.parent
    raise RuntimeError("Could not locate Thomas project root (pyproject.toml + thomas/).")


def get_paths(project_root: Optional[Path] = None) -> DoppelgangerPaths:
    blue = (project_root or find_project_root()).resolve()
    dg = blue / "runtime" / "doppelganger"
    green = dg / "green"
    green_runtime = dg / "green-runtime"
    green_venv = dg / "venvs" / "green"
    backups = dg / "backups"
    return DoppelgangerPaths(
        blue_root=blue,
        dg_root=dg,
        green_root=green,
        green_runtime=green_runtime,
        green_venv=green_venv,
        backups_root=backups,
    )


def _iter_src_files(src: Path) -> Iterable[Path]:
    for p in src.rglob("*"):
        name = p.name
        if name in _IGNORE_NAMES:
            continue
        if name.endswith(".pyc"):
            continue
        yield p


def _sync_tree(src: Path, dst: Path) -> None:
    """Mirror src -> dst, allowing deletions."""
    src = src.resolve()
    dst = dst.resolve()
    dst.mkdir(parents=True, exist_ok=True)

    # Copy/update
    for p in _iter_src_files(src):
        rel = p.relative_to(src)
        target = dst / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        # Copy only when needed (size/mtime heuristic).
        try:
            st_src = p.stat()
            st_dst = target.stat() if target.exists() else None
            if st_dst and st_dst.st_size == st_src.st_size and int(st_dst.st_mtime) == int(
                st_src.st_mtime
            ):
                continue
        except OSError:
            pass
        shutil.copy2(p, target)

    # Delete extraneous
    for p in sorted(dst.rglob("*"), key=lambda x: len(str(x)), reverse=True):
        name = p.name
        if name in _IGNORE_NAMES or name.endswith(".pyc"):
            # Always delete caches in dst to keep slots clean.
            try:
                if p.is_dir():
                    shutil.rmtree(p, ignore_errors=True)
                else:
                    p.unlink(missing_ok=True)  # py3.8+; ok for 3.10
            except Exception as e:
                log.debug("Failed to purge cache path %s: %s", p, e)
            continue

        rel = p.relative_to(dst)
        if not (src / rel).exists():
            try:
                if p.is_dir():
                    p.rmdir()
                else:
                    p.unlink()
            except OSError:
                # Directory not empty or file locked; ignore.
                pass


def sync_blue_to_green(paths: DoppelgangerPaths) -> None:
    paths.green_root.mkdir(parents=True, exist_ok=True)
    for d in _INCLUDE_DIRS:
        src = paths.blue_root / d
        if src.exists():
            _sync_tree(src, paths.green_root / d)
    for f in _INCLUDE_FILES:
        src = paths.blue_root / f
        if src.exists():
            (paths.green_root / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, paths.green_root / f)


def sync_green_to_blue(paths: DoppelgangerPaths) -> None:
    for d in _INCLUDE_DIRS:
        src = paths.green_root / d
        if src.exists():
            _sync_tree(src, paths.blue_root / d)
    for f in _INCLUDE_FILES:
        src = paths.green_root / f
        if src.exists():
            shutil.copy2(src, paths.blue_root / f)


def create_backup(paths: DoppelgangerPaths) -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = paths.backups_root / ts
    backup.mkdir(parents=True, exist_ok=True)
    for d in _INCLUDE_DIRS:
        src = paths.blue_root / d
        if src.exists():
            _sync_tree(src, backup / d)
    for f in _INCLUDE_FILES:
        src = paths.blue_root / f
        if src.exists():
            (backup / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, backup / f)
    return backup


def latest_backup(paths: DoppelgangerPaths) -> Optional[Path]:
    if not paths.backups_root.exists():
        return None
    items = [p for p in paths.backups_root.iterdir() if p.is_dir()]
    if not items:
        return None
    return sorted(items, key=lambda p: p.name)[-1]


def rollback(paths: DoppelgangerPaths, backup_dir: Optional[Path] = None) -> Path:
    backup = backup_dir or latest_backup(paths)
    if backup is None:
        raise RuntimeError("No backups found to roll back to.")
    for d in _INCLUDE_DIRS:
        src = backup / d
        if src.exists():
            _sync_tree(src, paths.blue_root / d)
    for f in _INCLUDE_FILES:
        src = backup / f
        if src.exists():
            shutil.copy2(src, paths.blue_root / f)
    return backup


def ensure_green_venv(paths: DoppelgangerPaths) -> Path:
    """Ensure the green venv exists and has thomas installed editable."""
    py = _venv_python(paths.green_venv)
    if not py.exists():
        paths.green_venv.parent.mkdir(parents=True, exist_ok=True)
        subprocess.check_call([sys.executable, "-m", "venv", str(paths.green_venv)])  # nosec
    py = _venv_python(paths.green_venv)
    if not py.exists():
        raise RuntimeError(f"Green venv created but python missing: {py}")

    # Fast path: if core deps are already present, avoid a networked pip run.
    probe = subprocess.call(  # nosec
        [str(py), "-c", "import aiohttp, click, httpx"],
        cwd=str(paths.green_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if probe != 0:
        subprocess.check_call([str(py), "-m", "pip", "install", "--upgrade", "pip"])  # nosec
        subprocess.check_call(  # nosec
            [str(py), "-m", "pip", "install", "-e", ".[repl,server]"],
            cwd=str(paths.green_root),
        )
    return py


def run_green_tests(paths: DoppelgangerPaths) -> None:
    py = ensure_green_venv(paths)
    # Ensure pytest is present in the green venv.
    has_pytest = subprocess.call(  # nosec
        [str(py), "-c", "import pytest"],
        cwd=str(paths.green_root),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if has_pytest != 0:
        subprocess.check_call([str(py), "-m", "pip", "install", "pytest>=7.0"], cwd=str(paths.green_root))  # nosec
    subprocess.check_call([str(py), "-m", "pytest", "-q"], cwd=str(paths.green_root))  # nosec


def run_green_server(paths: DoppelgangerPaths, *, host: str, port: int) -> None:
    py = ensure_green_venv(paths)
    env = dict(os.environ)
    env["THOMAS_MEMORY_ROOT"] = str(paths.green_runtime)
    subprocess.check_call(  # nosec
        [str(py), "-m", "thomas", "serve", "--host", host, "--port", str(int(port))],
        cwd=str(paths.green_root),
        env=env,
    )


def _stop_thomas_on_port_windows(port: int) -> bool:
    """Best-effort stop of an existing thomas serve process listening on port.

    Only stops the process if its command line looks like a thomas serve invocation.
    """
    if not _is_windows():
        return False

    ps = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-Command",
        (
            "$p=%d;"
            "$l=Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1;"
            "if(-not $l){ exit 3 };"
            # Avoid PowerShell's built-in $PID (read-only) which is case-insensitive.
            "$procId=[int]$l.OwningProcess;"
            "$cmd='';"
            "try{ $cmd=(Get-CimInstance Win32_Process -Filter (\\\"ProcessId=$procId\\\") -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CommandLine) } catch {};"
            "if($cmd -and ($cmd -match '(?i)(\\\\b-m\\\\s+thomas\\\\s+serve\\\\b|\\\\bthomas(\\\\.exe)?\\\\s+serve\\\\b)')){"
            "  Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue; exit 0"
            "} else { exit 4 }"
        )
        % int(port),
    ]

    r = subprocess.run(ps, capture_output=True, text=True)  # nosec
    # exit 0: stopped, 3: no listener, 4: listener isn't thomas serve
    return r.returncode == 0


def promote_green_to_blue(paths: DoppelgangerPaths, *, stop_port: int = 8899) -> Path:
    """Promote green into blue with a backup snapshot first."""
    paths.backups_root.mkdir(parents=True, exist_ok=True)

    # Stop blue if it's running on the known port (best-effort).
    _stop_thomas_on_port_windows(int(stop_port))

    backup = create_backup(paths)
    sync_green_to_blue(paths)
    return backup
