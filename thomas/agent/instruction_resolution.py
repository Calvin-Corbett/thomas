"""Scoped, hierarchical, cross-tool instruction file resolution.

Given a working file or directory, this module walks from that directory up to
the project root, collects every instruction file it finds along the way, and
merges them into a single prompt block with deterministic precedence.

Supported formats (live-read from disk on every resolution — never cached):

- Thomas-native:  ``THOMAS.md``, ``.thomas.md``
- Claude Code:    ``CLAUDE.md``
- Agents spec:    ``AGENTS.md``
- Cursor:         ``.cursorrules``

Precedence rules (exact, deterministic order)
---------------------------------------------
1. **Directory proximity wins.** A file in the start directory outranks any
   file in a parent directory; each directory outranks all of its ancestors.
2. **Within one directory, format order wins.** The fixed order is:
   ``THOMAS.md`` > ``.thomas.md`` > ``CLAUDE.md`` > ``AGENTS.md`` >
   ``.cursorrules``. Thomas-native files always outrank imported formats in
   the same directory.
3. ``resolve_instruction_sources`` returns sources sorted highest-precedence
   first (nearest directory first; within a directory, format order).
4. ``merge_instruction_sources`` emits blocks lowest-precedence first, so the
   highest-precedence source appears **last** (closest to the end of the
   prompt). Every block is labelled with its origin path and format.

Losslessness and explicit override
----------------------------------
The merge is lossless: content from every applicable file appears in the
merged output, *unless explicitly overridden*. A file that contains the
marker line ``<!-- thomas:override -->`` suppresses every source with strictly
lower precedence (all ancestor directories, plus lower-ranked formats in its
own directory). The marker line itself is stripped from the emitted content.

The walk stops at ``root`` when given, otherwise at the nearest ancestor
containing a ``.git`` entry, otherwise at the filesystem root (bounded by
``max_depth`` directories).

This module is intentionally dependency-light (stdlib only) because it is
imported on early CLI/agent startup paths.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

OVERRIDE_MARKER = "<!-- thomas:override -->"

# (filename, format id) in fixed within-directory precedence order.
# Earlier entries outrank later ones inside the same directory.
INSTRUCTION_FILENAMES: tuple[tuple[str, str], ...] = (
    ("THOMAS.md", "thomas"),
    (".thomas.md", "thomas"),
    ("CLAUDE.md", "claude"),
    ("AGENTS.md", "agents"),
    (".cursorrules", "cursor"),
)

_DEFAULT_MAX_DEPTH = 32
DEFAULT_MERGE_MAX_CHARS = 24_000


@dataclass(frozen=True)
class InstructionSource:
    """One resolved instruction file.

    ``depth`` is 0 for the start directory and increases toward the root.
    ``rank`` is the within-directory format rank (0 = highest precedence).
    """

    path: Path
    fmt: str
    depth: int
    rank: int
    content: str
    declares_override: bool


def _as_start_dir(start: str | Path | None) -> Path:
    base = Path(start) if start else Path.cwd()
    try:
        resolved = base.expanduser().resolve()
    except OSError:
        resolved = base.expanduser()
    try:
        if resolved.is_file():
            return resolved.parent
    except OSError:
        pass
    return resolved


def find_project_root(start_dir: Path, *, max_depth: int = _DEFAULT_MAX_DEPTH) -> Path:
    """Nearest ancestor (inclusive) containing ``.git``, else the last walkable ancestor."""

    chain = (start_dir, *start_dir.parents)[: max(1, int(max_depth))]
    for directory in chain:
        try:
            if (directory / ".git").exists():
                return directory
        except OSError:
            continue
    return chain[-1]


def _directory_chain(start_dir: Path, root_dir: Path, max_depth: int) -> list[Path]:
    """Directories from ``start_dir`` up to ``root_dir`` inclusive, nearest first."""

    chain: list[Path] = []
    for directory in (start_dir, *start_dir.parents)[: max(1, int(max_depth))]:
        chain.append(directory)
        if directory == root_dir:
            break
    return chain


def _read_source(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return None
    return text or None


def _strip_override_marker(content: str) -> str:
    kept = [line for line in content.splitlines() if line.strip() != OVERRIDE_MARKER]
    return "\n".join(kept).strip()


def resolve_instruction_sources(
    start: str | Path | None = None,
    *,
    root: str | Path | None = None,
    max_depth: int = _DEFAULT_MAX_DEPTH,
) -> list[InstructionSource]:
    """Collect applicable instruction files, highest precedence first.

    Sources are live-read from disk on every call. The returned list is
    already override-filtered: if any source declares the explicit override
    marker, every strictly-lower-precedence source is dropped.
    """

    start_dir = _as_start_dir(start)
    if root is not None:
        try:
            root_dir = Path(root).expanduser().resolve()
        except OSError:
            root_dir = Path(root).expanduser()
    else:
        root_dir = find_project_root(start_dir, max_depth=max_depth)

    sources: list[InstructionSource] = []
    for depth, directory in enumerate(_directory_chain(start_dir, root_dir, max_depth)):
        for rank, (filename, fmt) in enumerate(INSTRUCTION_FILENAMES):
            content = _read_source(directory / filename)
            if content is None:
                continue
            declares_override = any(line.strip() == OVERRIDE_MARKER for line in content.splitlines())
            sources.append(
                InstructionSource(
                    path=directory / filename,
                    fmt=fmt,
                    depth=depth,
                    rank=rank,
                    content=_strip_override_marker(content),
                    declares_override=declares_override,
                )
            )

    # Explicit override: the highest-precedence source declaring the marker
    # suppresses everything below it. Sources are already in precedence order.
    for index, source in enumerate(sources):
        if source.declares_override:
            dropped = sources[index + 1 :]
            if dropped:
                log.debug(
                    "Instruction override in %s suppressed %d lower-precedence source(s).",
                    source.path,
                    len(dropped),
                )
            return sources[: index + 1]
    return sources


def merge_instruction_sources(
    sources: list[InstructionSource],
    *,
    max_chars: int = DEFAULT_MERGE_MAX_CHARS,
) -> str:
    """Merge resolved sources into one labelled block, lowest precedence first.

    The highest-precedence source (nearest directory, highest format rank)
    appears last in the output. If the merge exceeds ``max_chars``, whole
    lowest-precedence blocks are dropped first and a truncation note is
    prepended — higher-precedence content is never sacrificed for lower.
    If the single highest-precedence block alone exceeds ``max_chars``, its
    tail is cut and an explicit truncation note is appended so the caller's
    prompt budget is always respected.
    """

    if not sources:
        return ""
    total = len(sources)
    blocks: list[str] = []
    # Reverse: emit farthest/lowest-precedence first so nearest lands last.
    for position, source in enumerate(reversed(sources)):
        header = f"[instructions {position + 1}/{total}: {source.path.as_posix()} ({source.fmt}) — later blocks take precedence]"
        blocks.append(header + "\n" + source.content)

    budget = max(200, int(max_chars))
    dropped = 0
    while len(blocks) > 1 and sum(len(b) + 2 for b in blocks) > budget:
        blocks.pop(0)
        dropped += 1
    if len(blocks) == 1 and len(blocks[0]) > budget:
        tail_note = "\n[instructions truncated: content cut to fit prompt budget]"
        blocks[0] = blocks[0][: budget - len(tail_note)].rstrip() + tail_note
    if dropped:
        blocks.insert(0, f"[instructions truncated: {dropped} lowest-precedence file(s) omitted for length]")
    return "\n\n".join(blocks).strip()


def resolve_merged_instructions(
    start: str | Path | None = None,
    *,
    root: str | Path | None = None,
    max_depth: int = _DEFAULT_MAX_DEPTH,
    max_chars: int = DEFAULT_MERGE_MAX_CHARS,
) -> str | None:
    """Resolve and merge nearest-directory instruction files for ``start``."""

    sources = resolve_instruction_sources(start, root=root, max_depth=max_depth)
    merged = merge_instruction_sources(sources, max_chars=max_chars)
    return merged or None
