"""What a plugin's code on disk currently is, as one comparable string.

Phase 3.5 (plans/thomas/tasks/PRAXIS-PHASE3-KERNEL/PLAN.md).

``thomas/plugins/runtime.py`` caches loaded plugin instances against the mtime
of ``installed_plugins.json``. Editing a plugin's own source does not touch that
manifest, so before this module the cache answered every later call with the
instance built from the code as it was at first load. Saving a fix to a plugin
and seeing no change was not a stale-process problem; it was that nothing was
looking at the file you edited.

**Content, not mtime.** A timestamp comparison is the obvious implementation and
it is wrong twice over: a filesystem with one-second mtime resolution reports no
change for an edit made within a second of the load — which is precisely the
shape of an agent editing its own plugin — and a copy or a checkout rewrites
mtimes for files whose content is identical, forcing reloads that change
nothing. Hashing the bytes answers the question actually being asked: *is this
the same code?*

Reads are bounded (``_MAX_FILES``, ``_MAX_BYTES_PER_FILE``) so fingerprinting an
unexpectedly large install root costs a known amount rather than an unknown one.
Both bounds are folded into the digest rather than applied silently: hitting the
file cap is recorded, and each file contributes its size as well as its first
megabyte, so an edit past the byte cap still changes the answer whenever it
changes the length. A bound that quietly stops looking would make
``unchanged`` — the word that means "what is on disk is already running" — the
answer for code that is not.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

#: Bounds on one fingerprint pass. A plugin package that exceeds either of these
#: is not a plugin package; the fingerprint stays honest by recording that it
#: stopped (``<truncated-after:N>``) and by hashing each file's size, rather than
#: by silently covering part of the tree.
_MAX_FILES = 512
_MAX_BYTES_PER_FILE = 1 << 20

#: Only these are code a reload would pick up. A plugin's data files change
#: without changing behaviour, and reloading on every one of those would make
#: "it reloaded" stop meaning anything.
_SOURCE_SUFFIXES = (".py",)


def _hash_file(digest: Any, path: Path, label: str) -> None:
    digest.update(label.encode("utf-8", errors="replace"))
    try:
        # The size covers what the byte cap does not read. A file longer than
        # _MAX_BYTES_PER_FILE whose edit lands past the cap still changes the
        # digest as long as it changes the length, which an edit to source
        # almost always does.
        digest.update(f":{path.stat().st_size}:".encode())
        with path.open("rb") as handle:
            digest.update(handle.read(_MAX_BYTES_PER_FILE))
    except OSError as exc:
        # An unreadable source file is a real difference from a readable one,
        # and folding the error text in keeps it that way: the fingerprint
        # changes again when the file becomes readable.
        digest.update(f"<unreadable:{exc.__class__.__name__}>".encode())


def _collect_source_files(path: Path) -> tuple[list[Path], bool]:
    """The bounded file list, and whether the bound actually cut something off."""
    if path.is_file():
        return ([path] if path.suffix in _SOURCE_SUFFIXES else []), False
    if not path.is_dir():
        return [], False
    found: list[Path] = []
    for suffix in _SOURCE_SUFFIXES:
        found.extend(path.rglob(f"*{suffix}"))
    ordered = sorted(found)
    return ordered[:_MAX_FILES], len(ordered) > _MAX_FILES


def source_fingerprint(path: str | Path) -> str:
    """A digest of the code at ``path``. Equal digests mean equal code.

    An absent path fingerprints as ``"absent"`` rather than as an empty digest,
    so "the plugin was uninstalled" and "the plugin has no source" stay
    distinguishable from each other and from a load that never happened.

    A tree with more than ``_MAX_FILES`` source files folds a truncation marker
    into the digest. That is weaker than hashing everything and stronger than
    saying nothing: the answer is then "the first 512 files, and there were more",
    which is at least not mistakable for "all of it".
    """
    try:
        root = Path(path).expanduser()
    except (OSError, ValueError, RuntimeError) as exc:
        log.debug("fingerprint: unusable path %r: %s", path, exc)
        return "unusable"
    if not root.exists():
        return "absent"

    files, truncated = _collect_source_files(root)
    if not files:
        return "no-source"

    digest = hashlib.sha256()
    base = root if root.is_dir() else root.parent
    for file_path in files:
        try:
            label = file_path.relative_to(base).as_posix()
        except ValueError:
            label = file_path.name
        _hash_file(digest, file_path, label)
    if truncated:
        digest.update(f"<truncated-after:{_MAX_FILES}>".encode())
    return digest.hexdigest()


def purge_imported_modules(prefix: str) -> list[str]:
    """Drop ``sys.modules`` entries under ``prefix``. Returns what was removed.

    A plugin package is imported under a synthetic module name, and its own
    submodules land under that name. Re-executing the package ``__init__``
    without clearing them re-binds the *cached* submodules, so a plugin whose
    edit lives in a submodule reloads into the old behaviour — the failure mode
    is worse than not reloading at all, because the log says it reloaded.
    """
    if not prefix:
        return []
    doomed = [name for name in sys.modules if name == prefix or name.startswith(f"{prefix}.")]
    for name in doomed:
        sys.modules.pop(name, None)
    return doomed


__all__ = ["purge_imported_modules", "source_fingerprint"]
