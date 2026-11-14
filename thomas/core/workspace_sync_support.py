"""Reading settings, paths and Python files for the workspace sync engine.

Split out of ``workspace_sync_engine.py`` when that file crossed the 800-line
rule. Everything here is a pure function of its arguments and the environment:
no engine state, no git. The engine keeps the cycle; this keeps the small
answers the cycle needs.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Files an automatic commit must never pick up: live databases, logs, scratch,
# secrets, and directories that are build output rather than work.
DEFAULT_EXCLUDE_GLOBS = (
    "*.db",
    "*.db-shm",
    "*.db-wal",
    "*.sqlite",
    "*.sqlite3",
    "*.log",
    "*.tmp",
    "*.temp",
    "*.bak",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "id_rsa",
    "id_ed25519",
    ".thomas/*",
    "runtime/*",
    "output/*",
    "__pycache__/*",
    ".pytest_cache/*",
    ".mypy_cache/*",
    ".ruff_cache/*",
    "node_modules/*",
    ".open-next/*",
)


def env_float(name: str, default: float, *, min_value: float = 0.0, max_value: float = 86_400.0) -> float:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return float(default)
    try:
        value = float(raw)
    except Exception:
        return float(default)
    return float(max(min_value, min(max_value, value)))


def env_int(name: str, default: int, *, min_value: int = 1, max_value: int = 10_000) -> int:
    raw = str(os.environ.get(name, "") or "").strip()
    if not raw:
        return int(default)
    try:
        value = int(raw)
    except Exception:
        return int(default)
    return int(max(min_value, min(max_value, value)))


def env_bool(name: str, default: bool) -> bool:
    raw = str(os.environ.get(name, "") or "").strip().lower()
    if not raw:
        return bool(default)
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def truncate(text: str, limit: int = 800) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return value[: limit - 20] + "\n... (truncated)"


def normalize_rel_path(value: str) -> str:
    text = str(value or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    while text.startswith("/"):
        text = text[1:]
    return text


def parse_extra_globs(raw: str) -> list[str]:
    items: list[str] = []
    for piece in str(raw or "").split(","):
        val = normalize_rel_path(piece).lower()
        if not val:
            continue
        items.append(val)
    return sorted(set(items))


def safe_file_age_s(path: Path) -> float:
    try:
        return max(0.0, time.time() - path.stat().st_mtime)
    except Exception:
        return 0.0


def validate_python_syntax(repo_root: Path, files: list[str]) -> dict[str, Any]:
    """Parse every changed ``.py`` file, in this process.

    This used to spawn ``python -m py_compile`` once per file, from the sync
    engine's thread. A fifty-file commit was fifty interpreter starts, each
    paying import and startup cost to answer a question the built-in
    :func:`compile` answers in microseconds -- without writing a ``.pyc`` as a
    side effect. The question asked is unchanged: does this file parse.
    """
    py_files = [rel for rel in files if str(rel).lower().endswith(".py")]
    if not py_files:
        return {"ok": True, "checked": 0, "errors": []}
    errors: list[dict[str, Any]] = []
    for rel in py_files:
        path = (Path(repo_root) / rel).resolve()
        if not path.exists():
            continue
        try:
            source = path.read_bytes()
        except OSError as exc:
            errors.append({"path": rel, "error": f"{type(exc).__name__}: {exc}"})
            continue
        try:
            compile(source, str(path), "exec", dont_inherit=True)
        except SyntaxError as exc:
            # The reading a person wants: which line, and what about it.
            errors.append(
                {
                    "path": rel,
                    "stdout": "",
                    "stderr": truncate(f"line {exc.lineno or 0}: {exc.msg or exc}"),
                }
            )
        except ValueError as exc:
            # Source with a null byte, or a declared encoding that is not one.
            # Still a file that will not import.
            errors.append({"path": rel, "error": f"{type(exc).__name__}: {exc}"})
    return {"ok": not bool(errors), "checked": len(py_files), "errors": errors}


__all__ = [
    "DEFAULT_EXCLUDE_GLOBS",
    "env_bool",
    "env_float",
    "env_int",
    "normalize_rel_path",
    "now_iso",
    "parse_extra_globs",
    "safe_file_age_s",
    "truncate",
    "validate_python_syntax",
]
