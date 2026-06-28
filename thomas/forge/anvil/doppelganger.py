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

import filecmp
import hashlib
import logging
import os
import shutil
import subprocess  # nosec
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import tomllib

log = logging.getLogger(__name__)


_INCLUDE_DIRS = ("thomas", "scripts", "tests", "definitions")
_INCLUDE_FILES = (
    "pyproject.toml",
    "README.md",
    "CHANGELOG.md",
    "thomas.toml",
    "pytest.ini",
    "run-ui.cmd",
    "run-repl.cmd",
    ".gitignore",
    "SOUL.md",
)
_GREEN_SUPPORT_DIRS = ("extensions", "evolve_supervisor", "evolve_corpus")
_GREEN_SUPPORT_FILES = (
    "AGENTS.md",
    "GUARDRAILS.md",
    "WORKTREE_RULES.md",
    "agent_safety.toml",
    "docs/AGENT_FILE_EDITING_RULES.md",
    "docs/ai/AGENT_ROUTER.md",
    "docs/ai/CHECKLISTS/agent-lane-chat.md",
    "apps/site/src/lib/site-config.ts",
    "apps/site/src/app/marketplace/page.tsx",
    "apps/site/src/app/api/marketplace/catalog/route.ts",
    "apps/site/src/app/api/v1/plugins/catalog/route.ts",
    "apps/site/src/app/api/v1/plugins/download-token/route.ts",
    "apps/site/src/app/api/v1/plugins/[pluginId]/route.ts",
)

_IGNORE_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".DS_Store",
}

SUPERVISOR_OWNED_PATHS = {
    "thomas/forge/anvil/doppelganger.py",
    "thomas/forge/anvil/evolve.py",
    "thomas/forge/anvil/evolve_autonomy.py",
    "thomas/forge/anvil/evolve_loop.py",
}
RUNTIME_PROTECTED_PREFIXES = (
    "thomas/tools/",
    "thomas/agent/",
    "thomas/core/",
    "thomas/server/",
    "scripts/",
)
RUNTIME_PROTECTED_FILES = {
    "agent_safety.toml",
    "AGENTS.md",
    "GUARDRAILS.md",
    ".pre-commit-config.yaml",
    "pyproject.toml",
    "thomas.toml",
    "thomas.prod.toml",
    "runtime/.runtime_protection_disabled",
    "runtime/.runtime_protection_key",
    "runtime/.breakglass_window",
    "runtime/.breakglass_window_key",
}
TEST_INFRA_ROOTS = ("tests",)
TEST_INFRA_FILES = {"pytest.ini"}
LOOP_PACKAGE_ROOT = "thomas/forge/anvil"


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


def find_project_root(start: Path | None = None) -> Path:
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


def get_paths(project_root: Path | None = None) -> DoppelgangerPaths:
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
            if (
                st_dst
                and st_dst.st_size == st_src.st_size
                and int(st_dst.st_mtime) == int(st_src.st_mtime)
                and filecmp.cmp(p, target, shallow=False)
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


def _normalize_relpath(value: str | Path) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_promotion_protected_paths(paths: DoppelgangerPaths) -> set[str]:
    relpaths = set(SUPERVISOR_OWNED_PATHS) | set(RUNTIME_PROTECTED_FILES) | set(RUNTIME_PROTECTED_PREFIXES)
    config_path = paths.blue_root / "agent_safety.toml"
    if not config_path.exists():
        return relpaths
    try:
        payload = tomllib.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return relpaths
    protected = payload.get("protected")
    if not isinstance(protected, dict):
        return relpaths
    for key in ("policy_files", "guardrails_files", "enforcement_files", "enforcement_scripts"):
        rows = protected.get(key) or []
        if not isinstance(rows, list):
            continue
        for item in rows:
            rel = _normalize_relpath(str(item or "")).strip()
            if rel:
                relpaths.add(rel)
    return relpaths


def _is_protected_relpath(rel: str, protected_paths: set[str]) -> bool:
    normalized = _normalize_relpath(rel).strip()
    if normalized in protected_paths:
        return True
    return any(item.endswith("/") and normalized.startswith(item.rstrip("/") + "/") for item in protected_paths if item)


def _iter_existing_files_under(root: Path, rel_prefix: str) -> set[str]:
    prefix = _normalize_relpath(rel_prefix).rstrip("/")
    base = root / prefix
    if not base.exists():
        return set()
    if base.is_file():
        return {prefix}
    return {
        f"{prefix}/{candidate.relative_to(base).as_posix()}"
        for candidate in _iter_src_files(base)
        if candidate.is_file()
    }


def _promotion_test_infra_paths(paths: DoppelgangerPaths) -> set[str]:
    relpaths = set(TEST_INFRA_FILES)
    for dirname in TEST_INFRA_ROOTS:
        for root in (paths.blue_root, paths.green_root):
            base = root / dirname
            if not base.exists():
                continue
            for candidate in _iter_src_files(base):
                if candidate.is_file():
                    relpaths.add(f"{dirname}/{candidate.relative_to(base).as_posix()}")
    return relpaths


def _promotion_loop_package_python_paths(paths: DoppelgangerPaths) -> set[str]:
    relpaths: set[str] = set()
    for root in (paths.blue_root, paths.green_root):
        base = root / LOOP_PACKAGE_ROOT
        if not base.exists():
            continue
        for candidate in _iter_src_files(base):
            if not candidate.is_file() or candidate.suffix != ".py":
                continue
            relpaths.add(f"{LOOP_PACKAGE_ROOT}/{candidate.relative_to(base).as_posix()}")
    return relpaths


def _promotion_new_loop_package_python_paths(paths: DoppelgangerPaths) -> set[str]:
    relpaths: set[str] = set()
    green_base = paths.green_root / LOOP_PACKAGE_ROOT
    if not green_base.exists():
        return relpaths
    for candidate in _iter_src_files(green_base):
        if not candidate.is_file() or candidate.suffix != ".py":
            continue
        rel = f"{LOOP_PACKAGE_ROOT}/{candidate.relative_to(green_base).as_posix()}"
        if not (paths.blue_root / rel).exists():
            relpaths.add(rel)
    return relpaths


def _promotion_protected_diffs(paths: DoppelgangerPaths) -> list[str]:
    changed: list[str] = []
    protected_paths = (
        _load_promotion_protected_paths(paths)
        | _promotion_test_infra_paths(paths)
        | _promotion_loop_package_python_paths(paths)
    )
    exact_paths = {rel for rel in protected_paths if not rel.endswith("/")}
    protected_prefixes = {rel for rel in protected_paths if rel.endswith("/")}
    for rel in sorted(exact_paths):
        blue_path = paths.blue_root / rel
        green_path = paths.green_root / rel
        if not blue_path.exists() and not green_path.exists():
            continue
        if blue_path.exists() != green_path.exists():
            changed.append(rel)
            continue
        try:
            if _sha256(blue_path) != _sha256(green_path):
                changed.append(rel)
        except OSError:
            changed.append(rel)
    for prefix in sorted(protected_prefixes):
        blue_files = _iter_existing_files_under(paths.blue_root, prefix)
        green_files = _iter_existing_files_under(paths.green_root, prefix)
        for rel in sorted(blue_files | green_files):
            blue_path = paths.blue_root / rel
            green_path = paths.green_root / rel
            if blue_path.exists() != green_path.exists():
                changed.append(rel)
                continue
            try:
                if _sha256(blue_path) != _sha256(green_path):
                    changed.append(rel)
            except OSError:
                changed.append(rel)
    return changed


def _promotion_protected_paths(paths: DoppelgangerPaths) -> set[str]:
    return (
        _load_promotion_protected_paths(paths)
        | _promotion_test_infra_paths(paths)
        | _promotion_loop_package_python_paths(paths)
    )


def _promotion_delta_protected_paths(paths: DoppelgangerPaths) -> set[str]:
    return (
        _load_promotion_protected_paths(paths)
        | _promotion_test_infra_paths(paths)
        | _promotion_new_loop_package_python_paths(paths)
    )


def _validate_green_to_blue_promotion(paths: DoppelgangerPaths) -> None:
    protected_diffs = _promotion_protected_diffs(paths)
    if protected_diffs:
        preview = ", ".join(protected_diffs[:8])
        raise RuntimeError(f"green promotion blocked by protected/supervisor-owned diff: {preview}")


def _normalize_delta_relpath(value: Any) -> str:
    rel = _normalize_relpath(str(value or "")).strip()
    if not rel:
        raise RuntimeError("green promotion blocked by empty delta path")
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError(f"green promotion blocked by unsafe delta path: {rel}")
    return rel


def _is_promotable_scope(rel: str) -> bool:
    normalized = _normalize_relpath(rel)
    if normalized in _INCLUDE_FILES:
        return True
    return any(normalized == root or normalized.startswith(f"{root}/") for root in _INCLUDE_DIRS)


def _validate_green_delta_promotion(paths: DoppelgangerPaths, changed_files: Iterable[Any]) -> list[str]:
    changed = sorted({_normalize_delta_relpath(item) for item in changed_files})
    if not changed:
        raise RuntimeError("green promotion blocked: no verified delta paths supplied")
    protected = _promotion_delta_protected_paths(paths)
    blocked = [rel for rel in changed if _is_protected_relpath(rel, protected)]
    if blocked:
        preview = ", ".join(blocked[:8])
        raise RuntimeError(f"green promotion blocked by protected/supervisor-owned delta: {preview}")
    out_of_scope = [rel for rel in changed if not _is_promotable_scope(rel)]
    if out_of_scope:
        preview = ", ".join(out_of_scope[:8])
        raise RuntimeError(f"green promotion blocked by non-promotable delta path: {preview}")
    return changed


def sync_green_delta_to_blue(paths: DoppelgangerPaths, changed_files: Iterable[Any]) -> list[str]:
    """Copy only the verified green delta into blue.

    Full green->blue sync mirrors entire trees and can overwrite unrelated dirty
    blue work. Evolve promotions should apply only the verified candidate files.
    """
    changed = _validate_green_delta_promotion(paths, changed_files)
    for rel in changed:
        src = paths.green_root / rel
        dst = paths.blue_root / rel
        if src.exists():
            if src.is_dir():
                raise RuntimeError(f"green promotion blocked by directory delta path: {rel}")
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
        else:
            if dst.exists():
                if dst.is_dir():
                    shutil.rmtree(dst)
                else:
                    dst.unlink()
    return changed


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
    for d in _GREEN_SUPPORT_DIRS:
        src = paths.blue_root / d
        if src.exists():
            _sync_tree(src, paths.green_root / d)
    for f in _GREEN_SUPPORT_FILES:
        src = paths.blue_root / f
        if src.exists():
            (paths.green_root / f).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, paths.green_root / f)


def sync_green_to_blue(paths: DoppelgangerPaths) -> None:
    _validate_green_to_blue_promotion(paths)
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


def latest_backup(paths: DoppelgangerPaths) -> Path | None:
    if not paths.backups_root.exists():
        return None
    items = [p for p in paths.backups_root.iterdir() if p.is_dir()]
    if not items:
        return None
    return sorted(items, key=lambda p: p.name)[-1]


def rollback(paths: DoppelgangerPaths, backup_dir: Path | None = None) -> Path:
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


def _hermetic_venv() -> bool:
    """True when the green venv must be built without network access (tests/offline).

    Set THOMAS_EVOLVE_HERMETIC_VENV=1 (the test harness does this in
    tests/conftest.py) to build the green venv with --system-site-packages so it
    inherits aiohttp/click/httpx from the parent interpreter. The dep probe then
    passes and the networked `pip install` is skipped entirely -- otherwise that
    install blocks forever in an offline/sandboxed environment and hangs the
    evolve test suite.
    """
    return os.environ.get("THOMAS_EVOLVE_HERMETIC_VENV", "").strip().lower() in {"1", "true", "yes", "on"}


def ensure_green_venv(paths: DoppelgangerPaths) -> Path:
    """Ensure the green venv exists and has thomas installed editable."""
    hermetic = _hermetic_venv()
    py = _venv_python(paths.green_venv)
    if not py.exists():
        paths.green_venv.parent.mkdir(parents=True, exist_ok=True)
        venv_cmd = [sys.executable, "-m", "venv"]
        # Inherit the parent interpreter's site-packages under test so the dep
        # probe below passes without a networked install.
        if hermetic:
            venv_cmd.append("--system-site-packages")
        venv_cmd.append(str(paths.green_venv))
        subprocess.check_call(venv_cmd)  # nosec
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
        # Never run the networked install under test; a hermetic venv inherits
        # deps via --system-site-packages, so reaching here means the harness is
        # misconfigured -- fail loudly rather than block forever on the network.
        if hermetic:
            raise RuntimeError(
                "Hermetic green venv is missing core deps (aiohttp/click/httpx); "
                "expected them via --system-site-packages from the parent interpreter."
            )
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
            f"$p={int(port)};"
            "$l=Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1;"
            "if(-not $l){ exit 3 };"
            # Avoid PowerShell's built-in $PID (read-only) which is case-insensitive.
            "$procId=[int]$l.OwningProcess;"
            "$cmd='';"
            'try{ $cmd=(Get-CimInstance Win32_Process -Filter (\\"ProcessId=$procId\\") -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CommandLine) } catch {};'
            "if($cmd -and ($cmd -match '(?i)(\\\\b-m\\\\s+thomas\\\\s+serve\\\\b|\\\\bthomas(\\\\.exe)?\\\\s+serve\\\\b)')){"
            "  Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue; exit 0"
            "} else { exit 4 }"
        ),
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


def promote_green_delta_to_blue(
    paths: DoppelgangerPaths,
    changed_files: Iterable[Any],
    *,
    stop_port: int = 8899,
) -> Path:
    """Promote only verified delta paths from green into blue with a backup."""
    paths.backups_root.mkdir(parents=True, exist_ok=True)
    _stop_thomas_on_port_windows(int(stop_port))
    backup = create_backup(paths)
    sync_green_delta_to_blue(paths, changed_files)
    return backup
