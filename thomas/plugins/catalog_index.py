"""Utilities for indexing plugin prompt-pack modules."""

from __future__ import annotations

import re
from pathlib import Path
from typing import List


_PLUGIN_FILE_RE = re.compile(r"^p\d{3}_[a-z0-9_]+\.py$")


def list_plugin_modules(package_dir: Path | None = None) -> List[str]:
    """Return sorted plugin module names without the `.py` suffix."""
    base = package_dir if package_dir is not None else Path(__file__).resolve().parent
    if not base.exists() or not base.is_dir():
        return []

    modules: List[str] = []
    for child in base.iterdir():
        if not child.is_file():
            continue
        name = child.name
        if not _PLUGIN_FILE_RE.match(name):
            continue
        modules.append(child.stem)
    modules.sort()
    return modules
