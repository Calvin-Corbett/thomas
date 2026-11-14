"""Filesystem tools: read, write, list, search files."""

from __future__ import annotations

import asyncio
import fnmatch
import logging
import os
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from thomas.core.file_access import WORKSPACE, authorize_write, clamp_file_access_level
from thomas.tools.base import Tool, ToolResult
from thomas.tools.fs_scope import (  # noqa: F401 - moved; shell.py imports them from here
    _is_read_protected_path,
    _safe_path,
)
from thomas.tools.runtime_protection_flag import (  # noqa: F401 - re-exported; tests and gates import these from here
    _GREEN_EVOLVE_RUNTIME_WRITES_ENV,
    _MAX_DISABLE_HOURS,
    _RUNTIME_FLAG_REL,
    _RUNTIME_FLAG_VERSION,
    _RUNTIME_KEY_REL,
    _green_evolve_runtime_writes_enabled,
    _is_runtime_protection_disabled,
    _load_runtime_protection_key,
    _runtime_signing_payload,
    _within_disable_window,
)
from thomas.tools.runtime_protection_paths import (  # noqa: F401 - re-exported; tests and gates import these from here
    _FILESYSTEM_ONLY_PROTECTED_PREFIXES,
    _HARDCODED_PROTECTED_DIRS,
    _HARDCODED_PROTECTED_FILES,
    _is_protected_runtime_path,
    _maybe_apply_native_auth_override,
    _runtime_protection_roots,
    anchor_runtime_protection,
)

log = logging.getLogger(__name__)

# Thomas project root (where the protected runtime dirs live). Used so the
# runtime-code protection still applies when a higher file-access level lets the
# worker write into the project tree.
_PROJECT_ROOT = Path(__file__).resolve().parents[2]


# ── Tree walks: never on the server's event loop, never unbounded ──
# Measured 2026-09-23: fs.search was async but never awaited. It walked the chat's
# sandbox -- the repo, runtime/ and .thomas/ included -- on the server's event loop,
# and one search that found nothing held that loop for 543 s over 259,348 files.
# Every background worker reports through that loop, so while it was held they all
# looked silent and their watchdog failed them. Walks now run in a worker thread,
# skip the directories below, and stop at a file and a time budget, saying so.
_WALK_MAX_FILES = 20_000
_WALK_MAX_SECONDS = 20.0
# Never walked into, at any depth: version control, dependencies, caches, Thomas's state.
_WALK_SKIP_DIRS = frozenset({".git", ".thomas", "node_modules", ".venv", "venv", ".tox", "__pycache__"})
# Skipped only directly under the sandbox root, where Thomas keeps its data. Deeper
# down the name is ordinary source (this repo has thomas/server/web/js/runtime/).
_WALK_ROOT_SKIP_DIRS = frozenset({"runtime"})


class _WalkBudget:
    """How much of a tree one tool call may look at before it stops and says why."""

    def __init__(self, max_files: int | None = None, max_seconds: float | None = None) -> None:
        self.max_files = max(1, int(_WALK_MAX_FILES if max_files is None else max_files))
        self.max_seconds = max(0.0, float(_WALK_MAX_SECONDS if max_seconds is None else max_seconds))
        self._deadline = time.monotonic() + self.max_seconds
        self.files = 0
        self.stopped = ""  # why the walk stopped early; empty while it has not
        self.cancelled = threading.Event()  # set when the awaiting call is cancelled

    def spend(self, files: int = 0) -> bool:
        """Count *files* more; False once any budget has run out."""
        if not self.stopped:
            self.files += files
            if self.cancelled.is_set():
                self.stopped = "the call was cancelled"
            elif self.files > self.max_files:
                self.stopped = f"it reached its {self.max_files:,}-file budget"
            elif time.monotonic() >= self._deadline:
                self.stopped = f"it reached its {self.max_seconds:g}-second time budget"
        return not self.stopped

    def note(self) -> str:
        """The line that tells the model its results are partial, so it can narrow the call."""
        if not self.stopped:
            return ""
        return f"\nStopped early: {self.stopped}. These results are partial; narrow the path or the glob."


def _walk_skipped(sandbox_root: Path, path: Path) -> bool:
    return path.name in _WALK_SKIP_DIRS or (path.name in _WALK_ROOT_SKIP_DIRS and path.parent == sandbox_root)


def _walk(
    sandbox_root: Path, base: Path, budget: _WalkBudget, *, count_entries: bool = False
) -> Iterator[tuple[Path, list[str], list[str]]]:
    """``os.walk`` from *base*, pruned of skipped dirs, ending when *budget* runs out.

    *base* itself is walked even when its name is one that is skipped: it was asked for.
    """
    for dirpath, dirnames, filenames in os.walk(base):
        here = Path(dirpath)
        dirnames[:] = [d for d in dirnames if not _walk_skipped(sandbox_root, here / d)]
        if not budget.spend(len(dirnames) + len(filenames) if count_entries else 0):
            return
        yield here, dirnames, filenames


async def _off_loop(budget: _WalkBudget, walk: Callable[..., Any], *args: Any) -> Any:
    """Run *walk* in a worker thread; if the caller is cancelled, tell the walk to stop."""
    try:
        return await asyncio.to_thread(walk, *args)
    except asyncio.CancelledError:
        budget.cancelled.set()
        raise


# One read_text() of a large file is a single call: the time budget cannot interrupt it,
# and decoding holds the GIL, so the server loop stalls anyway (a 116 MB build cache in
# this repo measured 0.4 s). Files are read this many characters at a time instead.
_SEARCH_CHUNK_CHARS = 1 << 20
_LINE_BREAKS = frozenset("\n\r\x0b\x0c\x1c\x1d\x1e\x85  ")  # what str.splitlines() splits on


def _file_line_batches(path: Path, budget: _WalkBudget) -> Iterator[list[str]]:
    """Read splitlines in chunks, checking the budget between chunks.

    Text mode normalizes CRLF/CR; partial lines wait for the next chunk."""
    if path.stat().st_size <= _SEARCH_CHUNK_CHARS:
        yield path.read_text(encoding="utf-8", errors="replace").splitlines()
        return
    with open(path, encoding="utf-8", errors="replace") as handle:
        carry = ""
        while chunk := handle.read(_SEARCH_CHUNK_CHARS):
            text = carry + chunk
            lines = text.splitlines()
            carry = "" if text[-1] in _LINE_BREAKS else lines.pop()
            yield lines
            if not budget.spend():
                return
        if carry:
            yield [carry]


def _search_tree(
    sandbox_root: Path, base: Path, regex: Any, file_glob: str, max_results: int, budget: _WalkBudget
) -> tuple[list[str], int]:
    """Search a file or tree in a worker thread, within budget."""
    matches: list[str] = []
    files_searched = 0
    paths = (
        (base,)
        if base.is_file()
        else (here / name for here, _dirs, names in _walk(sandbox_root, base, budget) for name in names)
    )
    for fpath in paths:
        if not budget.spend(1):
            return matches, files_searched
        if not fnmatch.fnmatch(fpath.name, file_glob) or _is_read_protected_path(sandbox_root, fpath):
            continue
        first_lineno = 1
        try:
            for batch_index, lines in enumerate(_file_line_batches(fpath, budget)):
                if batch_index == 0:
                    files_searched += 1
                for lineno, line in enumerate(lines, first_lineno):
                    if regex.search(line):
                        matches.append(f"{fpath.relative_to(sandbox_root)}:{lineno}: {line.rstrip()}")
                        if len(matches) >= max_results:
                            return matches, files_searched
                first_lineno += len(lines)
        except (OSError, UnicodeDecodeError):
            continue
    return matches, files_searched


def _glob_within_budget(sandbox_root: Path, base: Path, pattern: str, budget: _WalkBudget) -> Iterator[Path]:
    """``base.glob(pattern)``, except that a ``**`` walk skips what ``_walk`` skips and
    stops with the budget. A pattern without ``**`` reads one directory level per
    component, so it is left to pathlib unchanged."""
    parts = pattern.replace("\\", "/").split("/")
    if "**" not in parts:
        yield from base.glob(pattern)
        return
    cut = parts.index("**")
    head, tail = "/".join(parts[:cut]), "/".join(parts[cut + 1 :])
    starts = [base] if not head else [p for p in base.glob(head) if p.is_dir() and not _walk_skipped(sandbox_root, p)]
    seen: set[Path] = set()
    for start in starts:
        for here, _dirnames, _filenames in _walk(sandbox_root, start, budget, count_entries=True):
            found = [here] if not tail.strip("/") else _glob_within_budget(sandbox_root, here, tail, budget)
            for p in found:
                if p not in seen and (p == start or not _walk_skipped(sandbox_root, p)):
                    seen.add(p)
                    yield p


def _list_entries(sandbox_root: Path, base: Path, pattern: str, max_results: int, budget: _WalkBudget) -> list[str]:
    """fs.list_dir's listing, in a worker thread."""
    entries: list[str] = []
    for p in sorted(_glob_within_budget(sandbox_root, base, pattern, budget)):
        if len(entries) >= max_results:
            entries.append(f"... (truncated at {max_results} results)")
            break
        rel_path = p.relative_to(sandbox_root)
        suffix = "/" if p.is_dir() else ""
        entries.append(f"{rel_path}{suffix}")
    return entries


class ReadFileTool(Tool):
    name = "fs.read_file"
    category = "filesystem"
    description = (
        "Read the contents of a text file. Supports optional line range "
        "(start_line, end_line) for reading portions of large files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative or absolute path to the file",
            },
            "start_line": {
                "type": "integer",
                "description": "First line to read (1-based). Omit to read from start.",
            },
            "end_line": {
                "type": "integer",
                "description": "Last line to read (inclusive). Omit to read to end.",
            },
        },
        "required": ["path"],
    }

    def __init__(self, sandbox_root: Path, max_file_size: int = 5_000_000):
        self._root = sandbox_root.resolve()
        self._max_size = max_file_size

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        rel = args["path"]
        try:
            path = _safe_path(self._root, rel)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        # ── Read protection: refuse the runtime-protection signing key ──
        read_blocked = _is_read_protected_path(self._root, path)
        if read_blocked:
            log.warning("Read refused: %s", read_blocked)
            return ToolResult(ok=False, error=read_blocked)

        if not path.exists():
            return ToolResult(ok=False, error=f"File not found: {rel}")
        if not path.is_file():
            return ToolResult(ok=False, error=f"Not a file: {rel}")

        size = path.stat().st_size
        if size > self._max_size:
            return ToolResult(
                ok=False,
                error=f"File too large ({size:,} bytes, max {self._max_size:,}). "
                f"Use start_line/end_line to read a portion.",
            )

        text = path.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines(keepends=True)

        start = args.get("start_line")
        end = args.get("end_line")
        if start is not None or end is not None:
            s = (start or 1) - 1
            e = end or len(lines)
            lines = lines[s:e]
            first_line = s + 1
        else:
            first_line = 1
        text = "".join(f"{i:>6}\t{ln}" for i, ln in enumerate(lines, start=first_line))

        return ToolResult(ok=True, data=text)


# A write that removes more than this fraction of an existing file (>= the
# size floor) is refused as a likely rewrite-from-memory truncation, by
# whichever of the line or character fraction is larger (WriteFileTool.
# _truncation_refusal; self-fix evidence, 2026-09-24; Ruling X, M1/M2).
_TRUNCATION_GUARD_FRACTION = 0.4
_TRUNCATION_GUARD_MIN_LINES = 20
_TRUNCATION_GUARD_MIN_CHARS = 2000


def _char_count_with_trailing_newline(text: str) -> int:
    """len(text), normalised to count as if *text* ends in exactly one line
    break (N4: a file missing its final newline has one fewer separator than
    the same content would with one, which shifted an exactly-40% edit's
    character share to 40.03% and refused it; a file that already ends in
    one is counted unchanged)."""
    return len(text) if text.endswith(("\n", "\r")) else len(text) + 1


class WriteFileTool(Tool):
    name = "fs.write_file"
    category = "filesystem"
    description = (
        "Write content to a file. Creates parent directories if needed. On an "
        "EXISTING file of at least 20 lines or 2,000 characters, a write that "
        "removes more than 40% of its lines OR characters is refused -- that "
        "pattern is a rewrite-from-memory truncation, not an edit. Use "
        "diff.create to change part of a file; pass replace_whole_file: true "
        "to mean a full replacement."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative or absolute path for the file",
            },
            "content": {
                "type": "string",
                "description": "The text content to write",
            },
            "replace_whole_file": {
                "type": "boolean",
                "description": (
                    "Set true to intentionally replace an existing file's entire "
                    "content, bypassing the truncation guard. Not needed when "
                    "creating a new file."
                ),
            },
        },
        "required": ["path", "content"],
    }

    def __init__(
        self,
        sandbox_root: Path,
        *,
        file_access: int = WORKSPACE,
        project_root: Path | None = None,
        home_dir: Path | None = None,
    ):
        self._root = sandbox_root.resolve()
        # The file-access ladder level (read_only/workspace/project/pc/full). Default
        # WORKSPACE == the original sandbox-confined behavior, so existing callers are
        # unchanged; raising it lets the worker write to the project / your PC.
        self._file_access = clamp_file_access_level(file_access)
        self._project_root = (project_root or _PROJECT_ROOT).resolve()
        self._home_dir = (home_dir or Path.home()).resolve()

    def _resolve_target(self, rel: str) -> Path:
        """Resolve a path. Relative paths are relative to the workspace; absolute
        paths are taken as-is (the ladder, not _safe_path, decides if they're allowed)."""
        p = Path(rel)
        return p.resolve() if p.is_absolute() else (self._root / rel).resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        rel = args["path"]
        path = self._resolve_target(rel)

        # ── File-access ladder: is this path within the granted scope? ──
        # At WORKSPACE (default) this reproduces the old sandbox confinement; higher
        # levels widen to the project / your home folder. System dirs are denied at
        # every level.
        allowed, reason = authorize_write(
            self._file_access,
            path,
            workspace_root=self._root,
            project_root=self._project_root,
            home_dir=self._home_dir,
        )
        if not allowed:
            log.info("Write refused by file-access level: %s", reason)
            return ToolResult(ok=False, error=reason)

        # ── Runtime protection: block writes to Thomas's own code, always ──
        # Anchored to the PROJECT root (where Thomas's runtime actually lives), so a
        # write is blocked only when it resolves INSIDE the real repo — at any
        # file-access level. A worker building a deliverable in a separate workspace
        # stays free to create its own scripts/ or thomas/ subfolder (those names are
        # protected only in the repo); checking the workspace sandbox root there
        # falsely blocked the deliverable and hung the task.
        blocked = None
        for protection_root in _runtime_protection_roots(self._root, self._project_root):
            blocked = _is_protected_runtime_path(protection_root, path)
            if blocked:
                break
        if blocked:
            log.warning("Runtime protection triggered: %s", blocked)
            return ToolResult(ok=False, error=blocked)

        if not bool(args.get("replace_whole_file")):
            refusal = self._truncation_refusal(path, args["content"])
            if refusal is not None:
                log.warning("Write refused as a likely truncation: %s", refusal)
                return ToolResult(ok=False, error=refusal)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        # Report the resolved absolute path so the model can answer
        # "where did you save it?" instead of guessing with pwd/ls.
        return ToolResult(ok=True, data=f"Wrote {len(args['content'])} chars to {path}")

    @staticmethod
    def _truncation_refusal(path: Path, new_content: str) -> str | None:
        """A refusal string if this write would gut an existing file, else None.

        Below the size floor (M1), measured on the file's own text, nothing is
        checked; above it, removal is judged by whichever of the line or
        character fraction is larger (M2), both character counts taken as if
        each text ended in exactly one line break (N4). The refusal reports
        the texts' own counts.
        """
        if not path.exists() or not path.is_file():
            return None
        try:
            existing_text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        new_text = str(new_content)
        existing_lines, new_lines = len(existing_text.splitlines()), len(new_text.splitlines())
        if existing_lines < _TRUNCATION_GUARD_MIN_LINES and len(existing_text) < _TRUNCATION_GUARD_MIN_CHARS:
            return None
        existing_chars = _char_count_with_trailing_newline(existing_text)
        new_chars = _char_count_with_trailing_newline(new_text)
        line_frac = max(0.0, existing_lines - new_lines) / existing_lines if existing_lines else 0.0
        char_frac = max(0.0, existing_chars - new_chars) / existing_chars if existing_chars else 0.0
        removed_frac = max(line_frac, char_frac)
        if removed_frac <= _TRUNCATION_GUARD_FRACTION:
            return None
        pct = int(removed_frac * 100)
        return (
            f"Refused: this write would remove about {pct}% of an existing file's content "
            f"({existing_lines} -> {new_lines} lines, {len(existing_text)} -> {len(new_text)} chars). That "
            "is what a rewrite-from-memory truncation looks like, not an intended edit. Use "
            "diff.create to change part of a file instead of rewriting the whole thing. If a "
            "full replacement is really what you mean, pass replace_whole_file: true."
        )


def _record_self_change(rel: str, before: str | None, after: str, why: str, repo_root: Path) -> None:
    """File a change to Thomas's own code so the owner can undo or accept it.

    Owner direction 2026-09-22: a self-fix is "obviously retractable", with a
    card at the end of the reply carrying Undo and Accept. Never fatal: failing
    to note a change must not fail the write the owner already approved.
    """
    try:
        from thomas.core.self_change_ledger import record
        from thomas.core.session_scope import active_chat_id

        record(path=str(rel), before=before, after=after, why=why, chat=active_chat_id(), repo_root=repo_root)
    except (OSError, ValueError, TypeError, ImportError):
        log.warning("self-change ledger did not record '%s'", rel, exc_info=True)


def _card_path(path: Path, project_root: Path) -> str:
    """The path as the card shows it: relative to the project, forward slashes."""
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


class WriteProtectedFileTool(Tool):
    """Write a file at a runtime-protected path with native OS authorization.

    Standard ``fs.write_file`` refuses writes inside protected paths
    (``thomas/tools/``, ``thomas/agent/``, ``thomas/core/``, ``thomas/server/``,
    ``scripts/``, ``evolve_supervisor/``, ``evolve_corpus/``, top-level policy
    files, the runtime-protection flag).

    This tool wraps the *same* write logic but flips the
    ``allow_native_auth_override`` kwarg on the protection check.  When the
    target path is protected, the call attempts a one-shot native OS auth
    prompt (Windows Hello / Touch ID / polkit).  If a human at the physical
    device approves, this single write is allowed and audit-logged.  If
    denied/cancelled/unavailable, the standard refusal is returned.

    Headless sessions (no interactive desktop) cannot satisfy the prompt,
    so this tool is effectively unusable for protected paths in that
    context — which is the point.
    """

    name = "fs.write_protected_file"
    category = "filesystem"
    description = (
        "Write a file at a runtime-protected path. Requires a native OS "
        "authorization prompt (Windows Hello/PIN, Touch ID, or polkit) for "
        "any path inside thomas/tools/, thomas/agent/, thomas/core/, "
        "thomas/server/, scripts/, evolve_supervisor/, evolve_corpus/, "
        "or any top-level policy file. Use only "
        "when an interactive human is present at the device. For unprotected "
        "paths this tool behaves like fs.write_file."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative or absolute path for the file",
            },
            "content": {
                "type": "string",
                "description": "The text content to write",
            },
            "reason": {
                "type": "string",
                "description": (
                    "Short human-readable reason shown in the OS auth prompt "
                    "(e.g. 'Apply emergency fix to thomas/tools/filesystem.py')."
                ),
            },
        },
        "required": ["path", "content", "reason"],
    }

    def __init__(self, sandbox_root: Path, project_root: Path | None = None):
        self._root = sandbox_root.resolve()
        self._project_root = (project_root or _PROJECT_ROOT).resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        rel = args["path"]
        reason = str(args.get("reason") or "").strip()
        if not reason:
            return ToolResult(
                ok=False,
                error="fs.write_protected_file requires a non-empty 'reason' for the OS auth prompt.",
            )

        try:
            path = _safe_path(self._root, rel)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        # Read what is there now, before asking: the card shows the real diff, and
        # the same bytes let this change be taken back. If they cannot be read as
        # text, nothing is recorded -- an entry claiming "there was nothing here"
        # would make Undo delete the file.
        existed = path.exists()
        try:
            before: str | None = path.read_text(encoding="utf-8") if existed else None
            recordable = True
        except (OSError, UnicodeDecodeError):
            before, recordable = None, False
        content = str(args["content"])

        # The approval card is built from these exact bytes, worded by the pinned
        # catalogue, never by the model: its `reason` is shown on the chat card as
        # Thomas's words and never reaches the Windows dialog.
        from thomas.tools import trusted_card

        card = trusted_card.protected_write_card(
            _card_path(path, self._project_root),
            before,
            content,
            why=reason,
            existed=existed and before is None,
        )
        action_description = f"Write protected runtime path: {rel} — {reason}"
        # Anchor protection to the real project root, not the (possibly workspace)
        # sandbox: a deliverable worker writing <workspace>/scripts/... must not be
        # treated as touching Thomas's protected scripts/ (which only lives in the repo).
        blocked = None
        for protection_root in _runtime_protection_roots(self._root, self._project_root):
            blocked = _is_protected_runtime_path(
                protection_root,
                path,
                allow_native_auth_override=True,
                action_description=action_description,
                card=card,
            )
            if blocked:
                break
        if blocked:
            log.warning("Runtime protection refused (even with OS auth override): %s", blocked)
            return ToolResult(ok=False, error=blocked)

        # What you approved was a hash of these bytes. Anything else is not written.
        if trusted_card.load_catalogue().content_hash(content) != card.content_hash:
            log.error("fs.write_protected_file: content does not match the approved card for '%s'", rel)
            return ToolResult(ok=False, error="Refused: the content to write is not the content that was approved.")

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        if recordable:
            _record_self_change(rel, before, content, reason, self._project_root or self._root)
        log.warning(
            "fs.write_protected_file: wrote %d chars to '%s' (reason=%r)",
            len(args["content"]),
            rel,
            reason,
        )
        return ToolResult(
            ok=True,
            data=f"Wrote {len(args['content'])} chars to {rel} (via OS-auth override)",
        )


class ListDirTool(Tool):
    name = "fs.list_dir"
    category = "filesystem"
    description = (
        "List files and directories. Supports glob patterns. Returns file names with type indicators (/ for dirs)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory to list (default: current directory)",
            },
            "pattern": {
                "type": "string",
                "description": "Glob pattern to filter results (e.g. '*.py', '**/*.ts')",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum entries to return (default: 200)",
            },
        },
    }

    def __init__(self, sandbox_root: Path, *, max_files: int | None = None, max_seconds: float | None = None):
        self._root = sandbox_root.resolve()
        self._max_files = max_files
        self._max_seconds = max_seconds

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        rel = args.get("path", ".")
        pattern = args.get("pattern", "*")
        max_results = args.get("max_results", 200)

        try:
            base = _safe_path(self._root, rel)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        if not base.exists():
            return ToolResult(ok=False, error=f"Directory not found: {rel}")
        if not base.is_dir():
            return ToolResult(ok=False, error=f"Not a directory: {rel}")

        budget = _WalkBudget(self._max_files, self._max_seconds)
        try:
            entries = await _off_loop(budget, _list_entries, self._root, base, pattern, max_results, budget)
        except (OSError, ValueError) as e:
            return ToolResult(ok=False, error=f"Glob error: {e}")

        if not entries:
            return ToolResult(
                ok=True, data=("(nothing found)" if budget.stopped else "(empty directory)") + budget.note()
            )
        return ToolResult(ok=True, data="\n".join(entries) + budget.note())


class SearchFilesTool(Tool):
    name = "fs.search"
    category = "filesystem"
    description = (
        "Search for text in files using regex or literal match. "
        "Returns matching lines with file paths and line numbers."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Text or regex pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "File or directory to search in (default: project root)",
            },
            "glob": {
                "type": "string",
                "description": "File pattern to search within (e.g. '*.py')",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum matches to return (default: 50)",
            },
        },
        "required": ["pattern"],
    }

    def __init__(self, sandbox_root: Path, *, max_files: int | None = None, max_seconds: float | None = None):
        self._root = sandbox_root.resolve()
        self._max_files = max_files
        self._max_seconds = max_seconds

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        import re

        pattern_str = args["pattern"]
        rel = args.get("path", ".")
        file_glob = args.get("glob", "*")
        max_results = args.get("max_results", 50)

        try:
            base = _safe_path(self._root, rel)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        if not base.exists():
            return ToolResult(ok=False, error=f"Path not found: {rel}")
        try:
            regex = re.compile(pattern_str, re.IGNORECASE)
        except re.error as e:
            return ToolResult(ok=False, error=f"Invalid regex: {e}")

        budget = _WalkBudget(self._max_files, self._max_seconds)
        matches, files_searched = await _off_loop(
            budget, _search_tree, self._root, base, regex, file_glob, max_results, budget
        )

        if not files_searched:
            message = f"No files searched: path {rel!r}, glob {file_glob!r}; no matching files read"
            return ToolResult(ok=True, data=message + budget.note())
        if not matches:
            return ToolResult(ok=True, data=f"No matches found (searched {files_searched} files){budget.note()}")
        header = f"Found {len(matches)} matches (searched {files_searched} files):\n"
        return ToolResult(ok=True, data=header + "\n".join(matches) + budget.note())


def register_filesystem_tools(
    registry: Any,
    sandbox_root: Path,
    max_file_size: int = 5_000_000,
    *,
    file_access: int = WORKSPACE,
    project_root: Path | None = None,
    home_dir: Path | None = None,
) -> None:
    """Register all filesystem tools with the registry.

    ``file_access`` is the permission-ladder level (default WORKSPACE = the original
    sandbox-confined behavior). Raise it (PROJECT/PC/FULL) to let fs.write_file write
    beyond the workspace; OS system dirs and Thomas's own code stay protected at every
    level. See thomas/core/file_access.py.
    """
    registry.register(ReadFileTool(sandbox_root, max_file_size))
    registry.register(
        WriteFileTool(sandbox_root, file_access=file_access, project_root=project_root, home_dir=home_dir)
    )
    registry.register(WriteProtectedFileTool(sandbox_root, project_root=project_root))
    registry.register(ListDirTool(sandbox_root))
    registry.register(SearchFilesTool(sandbox_root))
