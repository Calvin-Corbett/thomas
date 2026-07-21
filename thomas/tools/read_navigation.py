"""CAP-001 L2: repo-wide read & navigation with a bounded read rationale.

``RepoReadProbe`` locates a *symbol* (function / class / module-level binding)
anywhere in a repository given **no location hint** -- even when the definition
lives several directories deep (e.g. ``a/b/c/target.py``). Crucially it does not
blindly slurp the whole tree: every file it opens is charged against a
:class:`ReadBudget` (max files / max bytes) and recorded as a
:class:`ReadRationaleEntry` with a one-line reason. The returned
:class:`ReadProbeResult` therefore carries an *accountable* trail of exactly
what was read and why, and provably never exceeds the budget.

Determinism: files are visited in a stable, path-sorted order and reasons are
generated from fixed templates, so the same repo + symbol + budget always yields
the same locations, rationale, and budget accounting.

This module depends only on the standard library (tools-layer rule: no imports
from agent/server/cli or other feature packages).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

# Default source extensions the probe will read. Kept narrow so navigation stays
# accountable rather than scanning binary / vendored assets.
DEFAULT_EXTENSIONS: tuple[str, ...] = (".py",)

# Directories never worth reading for symbol navigation. Skipping them keeps the
# read budget spent on real source, not caches or version-control internals.
DEFAULT_IGNORE_DIRS: frozenset[str] = frozenset(
    {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache", ".pytest_cache", ".ruff_cache"}
)

# Symbol-definition kinds, in the order they are reported for a single line.
KIND_FUNCTION = "function"
KIND_CLASS = "class"
KIND_ASSIGNMENT = "assignment"


@dataclass(frozen=True)
class ReadBudget:
    """Upper bound on how much the probe may read.

    Attributes:
        max_files: Maximum number of files the probe may open.
        max_bytes: Maximum total number of bytes the probe may read across all
            files. A file larger than the remaining byte allowance is read only
            up to that allowance (partial read), so the bound is never exceeded.
    """

    max_files: int
    max_bytes: int

    def __post_init__(self) -> None:
        if self.max_files < 0 or self.max_bytes < 0:
            raise ValueError("ReadBudget bounds must be non-negative")


@dataclass(frozen=True)
class BudgetUsage:
    """How much of a :class:`ReadBudget` was actually consumed."""

    files_read: int = 0
    bytes_read: int = 0

    def fits_within(self, budget: ReadBudget) -> bool:
        """True iff this usage is within ``budget`` on both dimensions."""
        return self.files_read <= budget.max_files and self.bytes_read <= budget.max_bytes


@dataclass(frozen=True)
class Location:
    """A single place where the target symbol is defined.

    Attributes:
        path: Repo-relative path (POSIX separators) of the defining file.
        line: 1-indexed line number of the definition.
        kind: One of ``function`` / ``class`` / ``assignment``.
        text: The stripped source line of the definition (for at-a-glance
            confirmation without a second read).
    """

    path: str
    line: int
    kind: str
    text: str


@dataclass(frozen=True)
class ReadRationaleEntry:
    """One accountable read: which file, how many bytes, and why.

    Attributes:
        path: Repo-relative path (POSIX separators) of the file read.
        bytes_read: Number of bytes actually read from this file (may be less
            than the file size when the remaining byte budget was smaller).
        truncated: True when the file was only partially read to stay in budget.
        reason: One-line justification for reading this file.
    """

    path: str
    bytes_read: int
    truncated: bool
    reason: str


@dataclass(frozen=True)
class ReadProbeResult:
    """Outcome of :meth:`RepoReadProbe.probe`.

    Attributes:
        symbol: The symbol that was searched for.
        locations: Every definition found, in path-sorted order (empty when the
            symbol does not exist within the budgeted reads).
        rationale: One entry per file read, in read order; bounded by the budget.
        within_budget: True iff ``budget_used`` fits within the requested budget
            (always True by construction; surfaced so callers can assert it).
        budget_used: The :class:`BudgetUsage` actually consumed.
        exhausted_budget: True when the walk stopped because the budget ran out
            before every candidate file could be read (navigation was capped).
    """

    symbol: str
    locations: list[Location] = field(default_factory=list)
    rationale: list[ReadRationaleEntry] = field(default_factory=list)
    within_budget: bool = True
    budget_used: BudgetUsage = field(default_factory=BudgetUsage)
    exhausted_budget: bool = False


class RepoReadProbe:
    """Locate a symbol across a repo under a bounded, accountable read budget."""

    def __init__(
        self,
        *,
        extensions: tuple[str, ...] = DEFAULT_EXTENSIONS,
        ignore_dirs: frozenset[str] = DEFAULT_IGNORE_DIRS,
    ) -> None:
        self._extensions = tuple(extensions)
        self._ignore_dirs = ignore_dirs

    def probe(self, root: str | Path, symbol: str, budget: ReadBudget) -> ReadProbeResult:
        """Find ``symbol`` under ``root`` without a hint, within ``budget``.

        Args:
            root: Repository root to search.
            symbol: Bare symbol name (no path, no module hint).
            budget: Read budget the probe must respect.

        Returns:
            A :class:`ReadProbeResult`. ``budget_used`` is guaranteed to fit
            within ``budget`` (``within_budget`` True), the ``rationale`` has at
            most ``budget.max_files`` entries, and ``locations`` holds every
            definition discovered among the files that were read.
        """
        symbol = symbol.strip()
        if not symbol:
            raise ValueError("symbol must be a non-empty name")

        root_path = Path(root)
        matchers = _build_matchers(symbol)

        locations: list[Location] = []
        rationale: list[ReadRationaleEntry] = []
        files_read = 0
        bytes_read = 0
        exhausted = False

        for rel_path, abs_path in self._iter_candidate_files(root_path):
            if files_read >= budget.max_files:
                exhausted = True
                break
            remaining_bytes = budget.max_bytes - bytes_read
            if remaining_bytes <= 0:
                exhausted = True
                break

            raw = abs_path.read_bytes()
            truncated = len(raw) > remaining_bytes
            chunk = raw[:remaining_bytes] if truncated else raw

            files_read += 1
            bytes_read += len(chunk)

            hits = _scan(chunk, matchers, rel_path)
            locations.extend(hits)
            rationale.append(
                ReadRationaleEntry(
                    path=rel_path,
                    bytes_read=len(chunk),
                    truncated=truncated,
                    reason=_reason(symbol, hits, truncated),
                )
            )

        usage = BudgetUsage(files_read=files_read, bytes_read=bytes_read)
        locations.sort(key=lambda loc: (loc.path, loc.line))
        return ReadProbeResult(
            symbol=symbol,
            locations=locations,
            rationale=rationale,
            within_budget=usage.fits_within(budget),
            budget_used=usage,
            exhausted_budget=exhausted,
        )

    def _iter_candidate_files(self, root: Path):
        """Yield ``(rel_posix_path, abs_path)`` in deterministic sorted order."""
        candidates: list[tuple[str, Path]] = []
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            if path.suffix not in self._extensions:
                continue
            rel = path.relative_to(root)
            if any(part in self._ignore_dirs for part in rel.parts):
                continue
            candidates.append((rel.as_posix(), path))
        candidates.sort(key=lambda item: item[0])
        yield from candidates


def _build_matchers(symbol: str) -> tuple[tuple[str, re.Pattern[str]], ...]:
    """Compile line-level definition matchers for ``symbol`` (kind, pattern)."""
    name = re.escape(symbol)
    return (
        (KIND_FUNCTION, re.compile(rf"^\s*(?:async\s+)?def\s+{name}\b")),
        (KIND_CLASS, re.compile(rf"^\s*class\s+{name}\b")),
        # Module- or class-level binding: `NAME = ...` or annotated `NAME: T`.
        (KIND_ASSIGNMENT, re.compile(rf"^\s*{name}\s*(?::[^=]+)?=(?!=)")),
    )


def _scan(chunk: bytes, matchers: tuple[tuple[str, re.Pattern[str]], ...], rel_path: str) -> list[Location]:
    """Return every definition of the symbol within ``chunk``."""
    text = chunk.decode("utf-8", errors="replace")
    found: list[Location] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in matchers:
            if pattern.match(line):
                found.append(Location(path=rel_path, line=lineno, kind=kind, text=line.strip()))
                break
    return found


def _reason(symbol: str, hits: list[Location], truncated: bool) -> str:
    """Build the one-line rationale for having read a file."""
    scope = "partial read (byte budget)" if truncated else "full read"
    if hits:
        kinds = ", ".join(sorted({h.kind for h in hits}))
        return f"{scope}: found {len(hits)} definition(s) of '{symbol}' ({kinds})"
    return f"{scope}: searched for '{symbol}', no definition here"
