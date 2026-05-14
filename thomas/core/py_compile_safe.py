"""Helpers for syntax compilation without polluting the source tree."""

from __future__ import annotations

import hashlib
import os
import py_compile
import tempfile
from pathlib import Path


def _safe_pyc_path(source: str | os.PathLike[str]) -> str:
    src_path = Path(source).resolve()
    cache_root = Path(os.environ.get("PYTHONPYCACHEPREFIX") or (Path(tempfile.gettempdir()) / "thomas_pycache"))
    digest = hashlib.sha1(str(src_path).encode("utf-8")).hexdigest()[:12]
    drive = src_path.drive.rstrip(":\\/").lower() if src_path.drive else "nodrive"
    rel_parts = [part for part in src_path.parts[1:] if part not in ("/", "\\")]
    target = cache_root / "manual_py_compile" / drive / Path(*rel_parts)
    target = target.with_suffix(f".{digest}.pyc")
    target.parent.mkdir(parents=True, exist_ok=True)
    return str(target)


def compile_no_repo_pyc(source: str | os.PathLike[str], *, doraise: bool = False) -> str | None:
    return py_compile.compile(str(source), cfile=_safe_pyc_path(source), doraise=doraise)
