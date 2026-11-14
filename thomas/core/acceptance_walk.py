"""Where the acceptance contract's source walk never goes, and what it raises when it has to stop.

``acceptance_contract._source_files`` walks the workspace for the source files its checks read: the files that
consume a data field, and the files changed during the work (the parse check and the honest-page check). On
2026-09-06 a stack dump twenty seconds into a loop pass landed in that walk: in Thomas's own checkout ``runtime/``
holds 566,161 files and the skip list never named it. Measured on that checkout 2026-10-14: one walk took 29.4 s,
and about 0.7 s with these folders skipped.

Pure core module: no imports beyond the standard library.
"""

from __future__ import annotations

import os
from pathlib import Path

# Skipped wherever they appear, in any letter case: dependency, cache and build trees, virtual environments, and
# Thomas's own data folder. None of them holds a deliverable's source.
SKIP_ANYWHERE = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "venvs",
        "__pycache__",
        "dist",
        "build",
        ".mypy_cache",
        ".ruff_cache",
        ".thomas",
    }
)
# Skipped only at the top of the walk, and only when it is Thomas's runtime tree: the workspace is a Thomas checkout
# (``pyproject.toml`` and a ``thomas/`` package, the rule ``doppelganger.find_project_root`` uses), or the folder
# holds the doppelganger. In Thomas's own checkout ``runtime/benchmarks`` alone holds 415,220 files. Any other folder of
# that name is read: a project may keep its own source in a top-level ``runtime/``, and
# ``thomas/server/web/js/runtime`` holds 100 of Thomas's own scripts, which the honest-page check reads.
THOMAS_RUNTIME = "runtime"
THOMAS_RUNTIME_MARK = "doppelganger"


class SourceScanIncomplete(RuntimeError):
    """The walk stopped before it saw every folder. ``found`` holds the source files it had read by then: what they
    show still decides, but a check they cannot settle is not met, because the rest was never read."""

    def __init__(self, message: str, found: list[Path] | None = None) -> None:
        super().__init__(message)
        self.found: list[Path] = list(found or [])


def is_thomas_checkout(top: str | Path) -> bool:
    return os.path.isfile(os.path.join(top, "pyproject.toml")) and os.path.isdir(os.path.join(top, "thomas"))


def _is_thomas_runtime(top: str | Path, name: str) -> bool:
    return is_thomas_checkout(top) or os.path.isdir(os.path.join(top, name, THOMAS_RUNTIME_MARK))


def entered_dirs(dirs: list[str], *, top: Path | None = None) -> list[str]:
    """The subfolders the walk goes into, from one folder's list; ``top`` is the workspace, given for its own list."""
    kept = [d for d in dirs if d.lower() not in SKIP_ANYWHERE]
    if top is None:
        return kept
    return [d for d in kept if not (d.lower() == THOMAS_RUNTIME and _is_thomas_runtime(top, d))]


__all__ = [
    "SKIP_ANYWHERE",
    "THOMAS_RUNTIME",
    "THOMAS_RUNTIME_MARK",
    "SourceScanIncomplete",
    "entered_dirs",
    "is_thomas_checkout",
]
