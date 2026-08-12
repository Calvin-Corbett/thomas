"""Coherent, transactional symbol rename across a repository (stdlib only).

Autonomous multi-file editing primitive: rename an identifier everywhere it
appears — Python imports/definitions/usages, test files, and docs — as a single
all-or-nothing transaction.

Guarantees:

* **Word-boundary matching** — occurrences are located with ``\\b<name>\\b`` so
  ``old_name`` never clobbers ``old_name_extra`` (the underscore is a word
  character, so no boundary sits between ``old_name`` and ``_extra``).
* **Coherent plan** — ``plan_rename`` returns a single ordered ``RenamePlan``: a
  per-file list of edits (with occurrence counts) covering every matching file.
* **Deterministic** — files are walked and sorted by POSIX-relative path, so the
  same inputs always produce the same ordered plan and the same result.
* **All-or-nothing apply** — every planned file is snapshotted (raw bytes)
  before the first write; any write failure restores every touched file to its
  original bytes (``rolled_back=True``), leaving the repo byte-identical.

This module depends only on the standard library; it never imports from other
Thomas packages, so it is safe to use from the ``tools`` tier.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "FileRename",
    "RenamePlan",
    "RenameResult",
    "InvalidIdentifierError",
    "plan_rename",
    "apply_rename",
]

# File suffixes that participate in a coherent rename: python source + tests
# (``.py``) and documentation (``.md``).
DEFAULT_SUFFIXES: tuple[str, ...] = (".py", ".md")

# Directories never worth scanning — vendored code, caches, VCS metadata.
_SKIP_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".venv",
        "venv",
        "node_modules",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "build",
        "dist",
        ".tox",
        ".eggs",
    }
)

# A valid rename target is a single identifier token (letters, digits, and
# underscores, not starting with a digit). This keeps word-boundary matching
# well-defined and refuses dotted / whitespace inputs.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class InvalidIdentifierError(ValueError):
    """Raised when ``old`` or ``new`` is not a single identifier token."""


@dataclass(frozen=True, order=True)
class FileRename:
    """One file's contribution to a rename plan.

    ``rel_path`` is the POSIX-relative path from the repo root (deterministic
    ordering key); ``occurrences`` is the number of word-boundary matches that
    will be rewritten in that file.
    """

    rel_path: str
    occurrences: int


@dataclass(frozen=True)
class RenamePlan:
    """A deterministic, coherent rename transaction.

    Two plans compare equal iff they describe the same rename over the same
    ordered set of files with the same occurrence counts — the basis of the
    determinism guarantee.
    """

    root: str
    old: str
    new: str
    files: tuple[FileRename, ...]

    @property
    def file_count(self) -> int:
        return len(self.files)

    @property
    def total_occurrences(self) -> int:
        return sum(f.occurrences for f in self.files)

    @property
    def is_empty(self) -> bool:
        return not self.files


@dataclass
class RenameResult:
    """Outcome of applying a :class:`RenamePlan`."""

    ok: bool
    applied_files: list[str] = field(default_factory=list)
    total_occurrences: int = 0
    rolled_back: bool = False
    error: str | None = None


# ---------------------------------------------------------------------------
# Matching helpers
# ---------------------------------------------------------------------------


def _validate_identifier(label: str, value: str) -> None:
    if not _IDENTIFIER_RE.match(value):
        raise InvalidIdentifierError(f"{label} must be a single identifier token, got {value!r}")


def _compile_boundary(name: str) -> re.Pattern[str]:
    """Word-boundary matcher for ``name`` — matches whole-token occurrences only."""
    return re.compile(r"\b" + re.escape(name) + r"\b")


def _iter_candidate_files(root: Path, suffixes: tuple[str, ...]) -> Iterable[Path]:
    """Yield candidate files under *root*, skipping vendored/cache directories.

    Directories are traversed in sorted order and only files with a matching
    suffix are yielded, giving a stable, reproducible walk.
    """
    stack: list[Path] = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir(), key=lambda p: p.name)
        except OSError:
            continue
        subdirs: list[Path] = []
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name in _SKIP_DIRS:
                    continue
                subdirs.append(entry)
            elif entry.is_file() and entry.suffix in suffixes:
                yield entry
        # Push in reverse so the shallowest sorted dir is processed first.
        stack.extend(reversed(subdirs))


# ---------------------------------------------------------------------------
# Planning
# ---------------------------------------------------------------------------


def plan_rename(
    root: str | Path,
    old: str,
    new: str,
    *,
    suffixes: tuple[str, ...] = DEFAULT_SUFFIXES,
) -> RenamePlan:
    """Discover every word-boundary occurrence of *old* and plan the rename.

    Scans ``.py`` (imports, definitions, usages, tests) and ``.md`` (docs)
    files under *root*, counting whole-token matches of *old*. Returns a
    deterministic :class:`RenamePlan` whose ``files`` are ordered by
    POSIX-relative path. Files with zero matches are excluded.
    """
    _validate_identifier("old", old)
    _validate_identifier("new", new)

    root_path = Path(root).resolve()
    if not root_path.is_dir():
        raise NotADirectoryError(f"root is not a directory: {root_path}")

    pattern = _compile_boundary(old)
    found: list[FileRename] = []
    for file_path in _iter_candidate_files(root_path, suffixes):
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        count = len(pattern.findall(content))
        if count:
            rel = file_path.relative_to(root_path).as_posix()
            found.append(FileRename(rel_path=rel, occurrences=count))

    found.sort()  # deterministic order by (rel_path, occurrences)
    return RenamePlan(root=str(root_path), old=old, new=new, files=tuple(found))


# ---------------------------------------------------------------------------
# Transactional apply
# ---------------------------------------------------------------------------


def _default_writer(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _restore(snapshots: dict[Path, bytes], touched: list[Path]) -> list[str]:
    """Restore every touched file from its byte snapshot; return any failures."""
    failures: list[str] = []
    for path in touched:
        try:
            path.write_bytes(snapshots[path])
        except OSError as exc:
            failures.append(f"{path}: {exc}")
    return failures


def apply_rename(
    plan: RenamePlan,
    *,
    writer: Callable[[Path, str], None] | None = None,
) -> RenameResult:
    """Apply *plan* as an all-or-nothing transaction.

    Every planned file is snapshotted (raw bytes) before the first write. If any
    write fails, every already-touched file is restored to its original bytes and
    the result reports ``rolled_back=True`` — the repository is left
    byte-identical to its pre-apply state.

    ``writer`` is an injection point (defaults to a UTF-8 ``write_text``); tests
    use it to force a mid-apply failure and exercise rollback.
    """
    write = writer or _default_writer
    root_path = Path(plan.root)
    pattern = _compile_boundary(plan.old)

    if plan.is_empty:
        return RenameResult(ok=True, applied_files=[], total_occurrences=0)

    # ── Preflight + snapshot: read and rewrite in memory, capturing originals ──
    snapshots: dict[Path, bytes] = {}
    planned_writes: list[tuple[Path, str, str, int]] = []  # (path, rel, new_content, count)
    for entry in plan.files:
        path = (root_path / entry.rel_path).resolve()
        try:
            original = path.read_bytes()
        except OSError as exc:
            return RenameResult(
                ok=False,
                error=f"snapshot failed for {entry.rel_path}: {exc}; nothing applied",
            )
        snapshots[path] = original
        text = original.decode("utf-8", errors="strict")
        new_text, count = pattern.subn(plan.new, text)
        planned_writes.append((path, entry.rel_path, new_text, count))

    # ── Write phase: any failure rolls back every touched file ──
    touched: list[Path] = []
    applied: list[str] = []
    total = 0
    for path, rel, new_content, count in planned_writes:
        touched.append(path)  # a failed write may truncate — restore it too
        try:
            write(path, new_content)
        except OSError as exc:
            restore_failures = _restore(snapshots, touched)
            error = f"write failed for {rel}: {exc}; all files rolled back"
            if restore_failures:
                error += "; ROLLBACK INCOMPLETE: " + "; ".join(restore_failures)
            return RenameResult(ok=False, rolled_back=True, error=error)
        applied.append(rel)
        total += count

    return RenameResult(ok=True, applied_files=applied, total_occurrences=total)
