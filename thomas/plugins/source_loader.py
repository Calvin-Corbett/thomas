"""Importing a plugin from its source, never from its cached bytecode.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md).

``SourceFileLoader`` consults ``__pycache__`` before it compiles: it compares the
source file's mtime **in whole seconds** and its size against the header of the
``.pyc``, and if both match it runs the cached bytecode. An agent editing its own
plugin sits inside that window constantly — a rewrite within the same second
whose length happens to match the previous one. The reload then reports success
and the old code keeps answering, which is a worse outcome than not reloading at
all, because the log says the edit landed.

Measured before this module existed, with bytecode writing on: a plugin edited
from ``loop36`` to ``loop49`` answered ``outcome: reloaded`` thirteen times in a
row and stamped ``loop36`` every time.

**How this closes it.** ``SourceLoader.get_code`` asks ``path_stats`` for the
source's timestamp, and treats ``OSError`` as "there is nothing to compare
against": it skips reading the cache, and — because the write is guarded by the
same timestamp it never obtained — skips writing one. So a plugin loaded through
:class:`SourceOnlyLoader` always runs the bytes that are on disk, and leaves no
``__pycache__`` behind to go stale later.

**Why a finder as well as a loader.** A package's own ``from . import rule`` does
not come back through the loader that imported the package; it goes to the path
finder, which uses an ordinary ``SourceFileLoader`` with its ordinary cache. So a
plugin whose edit lives in a submodule would reload into the old behaviour by the
same mechanism, one level down. :class:`SourceOnlyFinder` sits on ``sys.meta_path``
and answers **only** for the synthetic module prefixes registered here, so plugin
submodules compile from source and nothing else in the process changes.

Bytecode caching is a real optimisation and this deliberately gives it up — for
installed plugins only, which are a handful of small files, and in exchange for
the one property the reload lane is for.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import logging
import sys
import threading
from importlib.abc import MetaPathFinder
from importlib.machinery import ModuleSpec
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Top-level synthetic package names whose submodules must also bypass the cache.
_PREFIXES: set[str] = set()
_LOCK = threading.Lock()
_FINDER: SourceOnlyFinder | None = None


class SourceOnlyLoader(importlib.machinery.SourceFileLoader):
    """A source loader that neither reads nor writes ``__pycache__``."""

    def path_stats(self, path: str) -> Any:
        """Refuse to date the source, which is how the cache is declined.

        ``get_code`` catches ``OSError`` here and falls through to compiling the
        file. Raising is the documented way to say "this loader has no timestamp
        to validate a ``.pyc`` against"; it is not an error path.
        """
        raise OSError(f"bytecode cache bypassed for {path}")


class SourceOnlyFinder(MetaPathFinder):
    """Resolves submodules of a registered plugin package, source-only.

    Answers for nothing else: a name whose top-level package was not registered
    by :func:`register_source_only_prefix` gets ``None``, which sends the import
    on to the finders that would have handled it anyway.
    """

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> ModuleSpec | None:
        if "." not in fullname:
            # The package itself is loaded by path, not found by name.
            return None
        with _LOCK:
            known = fullname.partition(".")[0] in _PREFIXES
        if not known:
            return None
        for entry in list(path or ()):
            try:
                spec = _spec_in_directory(fullname, Path(str(entry)))
            except OSError as exc:  # REVIEWED: an unreadable dir is not our error
                log.debug("source-only finder: %s unreadable: %s", entry, exc)
                continue
            if spec is not None:
                return spec
        return None


def _spec_in_directory(fullname: str, directory: Path) -> ModuleSpec | None:
    tail = fullname.rpartition(".")[2]
    package_init = directory / tail / "__init__.py"
    if package_init.is_file():
        return source_only_spec(fullname, package_init, package_dir=directory / tail)
    module_file = directory / f"{tail}.py"
    if module_file.is_file():
        return source_only_spec(fullname, module_file)
    return None


def source_only_spec(module_name: str, file_path: Path, *, package_dir: Path | None = None) -> ModuleSpec | None:
    """A spec for ``file_path`` whose loader compiles it every time."""
    loader = SourceOnlyLoader(module_name, str(file_path))
    if package_dir is None:
        return importlib.util.spec_from_file_location(module_name, str(file_path), loader=loader)
    return importlib.util.spec_from_file_location(
        module_name,
        str(file_path),
        loader=loader,
        submodule_search_locations=[str(package_dir)],
    )


def register_source_only_prefix(module_name: str) -> None:
    """Route submodule imports under ``module_name`` through the source loader.

    Idempotent, and the finder is installed once on first use rather than at
    import time: a module that changes ``sys.meta_path`` merely by being imported
    is the kind of side effect that is very hard to account for later.
    """
    if not module_name:
        return
    global _FINDER
    with _LOCK:
        _PREFIXES.add(module_name.partition(".")[0])
        if _FINDER is None:
            _FINDER = SourceOnlyFinder()
            sys.meta_path.insert(0, _FINDER)
            log.debug("source-only import finder installed for plugin packages")


__all__ = [
    "SourceOnlyFinder",
    "SourceOnlyLoader",
    "register_source_only_prefix",
    "source_only_spec",
]
