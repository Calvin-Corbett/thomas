"""Bounded source-tree scans for the ``code.*`` tools.

The Python fallbacks behind ``code.search``, ``code.find_definition`` and
``code.find_references`` used to walk whatever they were pointed at, to whatever
depth, with no budget. They were declared ``async`` but never awaited anything,
so the walk ran on the caller's thread -- and a Build child agent's tool calls
run as tasks on the server's event loop.

Measured 2026-09-24 on this checkout: ``code.find_definition`` with
``path='thomas'`` took 3.83 s, and with ``path='.'`` took **227.5 s**, because it
descended ``runtime/`` and ``.thomas/`` -- Thomas's own state directories, which
the skip list did not name. For nearly four minutes the server could not answer
anything, including the heartbeats its own workers report through.

This module is the walk, once: the skip list, the budget, and a note that tells
the model its results were cut short so it can narrow the call instead of
believing an empty answer. The tools hand it to a worker thread.

The same lesson is recorded in ``thomas/tools/filesystem.py`` for ``fs.search``
(lines 95-106). The budgets match it exactly, and so does the root-only rule:
``runtime`` and nothing else, because a name skipped at a project's root is a
directory of that project's source made invisible. :data:`SKIP_DIRS` is wider
than ``fs.search``'s list -- beyond the seven names that list already carries it
adds ``.hg``, ``.svn``, ``build``, ``dist``, ``.mypy_cache``, ``.pytest_cache``
and ``thomas_rag_index``, which are version control, build output and caches at
any depth.
"""

from __future__ import annotations

import fnmatch
import os
import re
import stat
import time
from collections.abc import Iterator
from pathlib import Path, PurePosixPath

from thomas.tools.runtime_protection_flag import _RUNTIME_KEY_REL

# Never descended into, at any depth: version control, dependencies, build
# output, caches, and Thomas's own state. ``.thomas`` is the one whose absence
# was measured above.
SKIP_DIRS = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        ".thomas",
        ".mypy_cache",
        ".pytest_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "thomas_rag_index",
        "venv",
    }
)
# Skipped only when it sits directly under the directory being scanned, where it
# is Thomas's runtime state. Deeper down the name is ordinary source -- this repo
# has thomas/server/web/js/runtime/ -- so it must not be skipped by name alone.
# Only ``runtime`` belongs here, the same as ``fs.search``: at a project's root
# every other candidate (``output/``, ``artifacts/``) is just as likely to be
# that project's own code, and a scan that silently omits it answers wrongly.
ROOT_SKIP_DIRS = frozenset({"runtime"})

# Never read by any walk. ``filesystem._is_read_protected_path`` is the rule for a path somebody names, and resolves it
# to decide; a walk meets 20,000 names, and this one is reserved, so comparing the name holds the same line for less.
KEY_NAME = PurePosixPath(_RUNTIME_KEY_REL).name

MAX_FILES = 20_000
MAX_SECONDS = 20.0


class ScanBudget:
    """How much of a tree one tool call may read before it stops and says why."""

    def __init__(self, max_files: int | None = None, max_seconds: float | None = None) -> None:
        self.max_files = max(1, int(MAX_FILES if max_files is None else max_files))
        self.max_seconds = max(0.1, float(MAX_SECONDS if max_seconds is None else max_seconds))
        self._deadline = time.monotonic() + self.max_seconds
        self.files = 0
        self.stopped = ""

    def spend(self, files: int = 1) -> bool:
        """Count ``files`` more; False once a budget has run out."""
        if not self.stopped:
            self.files += files
            if self.files > self.max_files:
                self.stopped = f"it reached its {self.max_files:,}-file budget"
            elif time.monotonic() > self._deadline:
                self.stopped = f"it reached its {self.max_seconds:g}-second budget"
        return not self.stopped

    def note(self) -> str:
        """The line that tells the caller its results are partial."""
        if not self.stopped:
            return ""
        return f"\nStopped early: {self.stopped}. These results are partial; narrow the path or the glob."


def _is_link(entry: os.DirEntry[str]) -> bool:
    """A symbolic link or a junction. Read from the listing, so a link to a network share is never stat'ed."""
    if entry.is_symlink():
        return True
    return os.name == "nt" and entry.stat(follow_symlinks=False).st_reparse_tag == stat.IO_REPARSE_TAG_MOUNT_POINT


def list_folder(folder: Path | str) -> tuple[list[str], list[str], list[str]]:
    """``folder``'s subfolders, files and links, by name. What cannot be listed is left out, as ``os.walk`` leaves it.

    A link is its own kind, neither a folder nor a file: it is a name here for something that can be anywhere, so a walk
    that steps through one has left the place it was given. ``os.walk`` only stops at symbolic links, and on Python 3.12
    goes straight through a junction. A link that stays inside loses nothing, because the walk reaches the same files
    at their real path; rg behaves the same way.
    """
    folders: list[str] = []
    files: list[str] = []
    links: list[str] = []
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if _is_link(entry):
                    links.append(entry.name)
                elif entry.is_dir(follow_symlinks=False):
                    folders.append(entry.name)
                else:
                    files.append(entry.name)
    except OSError:
        pass
    return folders, files, links


def iter_source_files(
    base: Path,
    *,
    exts: set[str] | None = None,
    file_glob: str = "*",
    budget: ScanBudget,
) -> Iterator[Path]:
    """Yield readable files under ``base``, pruning skipped directories and never entering a link.

    ``base`` itself is the root for :data:`ROOT_SKIP_DIRS`, so pointing a scan at
    a project folder skips that project's ``runtime/`` while a scan aimed inside
    ``thomas/server/web/js`` still reads the ``runtime/`` module directory there.
    """
    base_str = str(base)
    pending = [base_str]
    while pending:
        dirpath = pending.pop()
        at_root = dirpath == base_str
        folders, files, _links = list_folder(dirpath)
        kept = [name for name in folders if name not in SKIP_DIRS and not (at_root and name in ROOT_SKIP_DIRS)]
        # Last pushed is first walked, so this keeps the order os.walk gave: each folder, then its subfolders by name.
        pending.extend(os.path.join(dirpath, name) for name in sorted(kept, reverse=True))
        for name in sorted(files):
            if name == KEY_NAME:
                continue
            if exts is not None and Path(name).suffix.lower() not in exts:
                continue
            if file_glob != "*" and not fnmatch.fnmatch(name, file_glob):
                continue
            if not budget.spend():
                return
            yield Path(dirpath) / name


def _read_lines(path: Path) -> list[str] | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None


def search_lines(
    base: Path,
    root: Path,
    regex: re.Pattern[str],
    *,
    exts: set[str] | None = None,
    file_glob: str = "*",
    context: int = 0,
    max_results: int = 50,
    budget: ScanBudget | None = None,
) -> tuple[list[str], int, str]:
    """Matching lines under ``base``, as ``(rows, files_searched, note)``."""
    spend = budget or ScanBudget()
    rows: list[str] = []
    searched = 0
    # A literal cannot match a line unless it occurs in the file. Avoid splitting
    # every nonmatching file into lines; keep the regex path for all other patterns.
    literal = regex.pattern if regex.pattern.isascii() and re.escape(regex.pattern) == regex.pattern else None
    if regex.flags not in (re.UNICODE, re.UNICODE | re.IGNORECASE):
        literal = None
    if literal is not None and regex.flags & re.IGNORECASE:
        literal = literal.lower()
    for path in iter_source_files(base, exts=exts, file_glob=file_glob, budget=spend):
        if literal is not None:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            searched += 1
            haystack = text.lower() if regex.flags & re.IGNORECASE else text
            if literal not in haystack and (text.isascii() or not regex.flags & re.IGNORECASE):
                continue
            lines = text.splitlines()
        else:
            lines = _read_lines(path)
            if lines is None:
                continue
            searched += 1
        rel = _relative(path, root)
        for lineno, line in enumerate(lines, 1):
            if not regex.search(line):
                continue
            if context > 0:
                start = max(0, lineno - 1 - context)
                end = min(len(lines), lineno + context)
                rows.extend(f"{rel}:{i + 1}{'>' if i == lineno - 1 else ' '} {lines[i]}" for i in range(start, end))
                rows.append("--")
            else:
                rows.append(f"{rel}:{lineno}: {line.rstrip()}")
            if len(rows) >= max_results:
                return rows, searched, spend.note()
    return rows, searched, spend.note()


def find_symbol(
    base: Path,
    root: Path,
    patterns: list[re.Pattern[str]],
    exts: set[str],
    *,
    after: int = 3,
    max_results: int = 20,
    budget: ScanBudget | None = None,
) -> tuple[list[str], str]:
    """Definition sites with trailing context, as ``(blocks, note)``."""
    spend = budget or ScanBudget()
    blocks: list[str] = []
    for path in iter_source_files(base, exts=exts, budget=spend):
        lines = _read_lines(path)
        if lines is None:
            continue
        rel = _relative(path, root)
        for lineno, line in enumerate(lines, 1):
            if not any(pattern.search(line) for pattern in patterns):
                continue
            end = min(len(lines), lineno + after)
            body = "\n".join(f"  {i + 1}: {lines[i]}" for i in range(max(0, lineno - 1), end))
            blocks.append(f"{rel}:{lineno}\n{body}")
            if len(blocks) >= max_results:
                return blocks, spend.note()
    return blocks, spend.note()


def _relative(path: Path, root: Path) -> str:
    """``path`` as the caller's sandbox sees it, or its own name if it is outside."""
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


__all__ = [
    "KEY_NAME",
    "MAX_FILES",
    "MAX_SECONDS",
    "ROOT_SKIP_DIRS",
    "SKIP_DIRS",
    "ScanBudget",
    "find_symbol",
    "iter_source_files",
    "list_folder",
    "search_lines",
]
