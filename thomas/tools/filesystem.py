"""Filesystem tools: read, write, list, search files."""

from __future__ import annotations

import fnmatch
import logging
import os
from pathlib import Path, PurePosixPath
from typing import Any

from thomas.tools.base import Tool, ToolResult

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded protected directories — the last line of defence.
# Even if agent_safety.toml is corrupted or unreadable, these stay active.
# Every directory listed here (relative to sandbox root) is read-only for
# agent-spawned tools.  The list is deliberately minimal: only Thomas's own
# runtime, enforcement scripts, and top-level policy files.
# ---------------------------------------------------------------------------
_HARDCODED_PROTECTED_DIRS: tuple[str, ...] = (
    "thomas/tools",
    "thomas/agent",
    "thomas/core",
    "thomas/server",
    "scripts",
)

_HARDCODED_PROTECTED_FILES: tuple[str, ...] = (
    "agent_safety.toml",
    "AGENTS.md",
    "GUARDRAILS.md",
    ".pre-commit-config.yaml",
    "pyproject.toml",
    "thomas.toml",
    "thomas.prod.toml",
)


def _is_runtime_protection_disabled(sandbox_root: Path) -> bool:
    """Return True if a human has temporarily disabled runtime protection.

    The flag file is created by ``scripts/runtime_protection_toggle.py``
    which requires Windows credential authentication before writing it.
    """
    try:
        from scripts.runtime_protection_toggle import runtime_protection_is_disabled
    except ImportError:
        return False
    return bool(runtime_protection_is_disabled(sandbox_root.resolve()))


def _is_protected_runtime_path(sandbox_root: Path, target: Path) -> str | None:
    """Check if *target* falls inside a protected runtime directory or matches
    a protected file.

    Returns a human-readable reason string if the path is protected, or
    ``None`` if the write is allowed.

    The check is intentionally independent of any config file so that an agent
    cannot neutralise it by editing ``agent_safety.toml`` — that file is
    itself inside the protected set.

    A human can temporarily disable this by running::

        python scripts/runtime_protection_toggle.py off

    which requires Windows credential authentication and creates a flag file.
    """
    # Allow bypass when a human has explicitly disabled protection.
    if _is_runtime_protection_disabled(sandbox_root):
        return None

    try:
        rel = target.resolve().relative_to(sandbox_root.resolve())
    except ValueError:
        # Outside sandbox entirely — _safe_path already handles this.
        return None

    # Normalise to forward-slash for consistent matching on all platforms.
    rel_posix = PurePosixPath(rel)

    # Check protected directories (any file *inside* these).
    for pdir in _HARDCODED_PROTECTED_DIRS:
        protected = PurePosixPath(pdir)
        try:
            rel_posix.relative_to(protected)
            return (
                f"BLOCKED: '{rel_posix}' is inside protected runtime "
                f"directory '{pdir}/'. Agent-spawned tools cannot modify "
                f"Thomas's own runtime code."
            )
        except ValueError:
            continue

    # Check individual protected files at the repo root.
    for pfile in _HARDCODED_PROTECTED_FILES:
        if rel_posix == PurePosixPath(pfile):
            return f"BLOCKED: '{rel_posix}' is a protected policy file. " f"Agent-spawned tools cannot modify it."

    return None


def _safe_path(root: Path, rel: str) -> Path:
    """Resolve path and ensure it doesn't escape the sandbox root.

    Uses os.path.commonpath for case-insensitive comparison on Windows,
    which handles case differences (C:\\Users vs c:\\users) and prevents
    symlink/junction escapes.
    """
    resolved_root = root.resolve()
    p = (resolved_root / rel).resolve()
    try:
        common = Path(os.path.commonpath([str(resolved_root), str(p)]))
        # On Windows, paths are case-insensitive
        if os.name == "nt":
            if common.resolve() != resolved_root:
                raise ValueError(f"Path escapes sandbox: {rel}")
        else:
            if common != resolved_root:
                raise ValueError(f"Path escapes sandbox: {rel}")
    except ValueError:
        raise ValueError(f"Path escapes sandbox: {rel}") from None
    return p


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
            # Add line numbers
            numbered = []
            for i, ln in enumerate(lines, start=s + 1):
                numbered.append(f"{i:>6}\t{ln}")
            text = "".join(numbered)
        else:
            # Add line numbers for full file
            numbered = []
            for i, ln in enumerate(lines, start=1):
                numbered.append(f"{i:>6}\t{ln}")
            text = "".join(numbered)

        return ToolResult(ok=True, data=text)


class WriteFileTool(Tool):
    name = "fs.write_file"
    category = "filesystem"
    description = "Write content to a file. Creates parent directories if needed."
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
        },
        "required": ["path", "content"],
    }

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        rel = args["path"]
        try:
            path = _safe_path(self._root, rel)
        except ValueError as e:
            return ToolResult(ok=False, error=str(e))

        # ── Runtime protection: block writes to Thomas's own code ──
        blocked = _is_protected_runtime_path(self._root, path)
        if blocked:
            log.warning("Runtime protection triggered: %s", blocked)
            return ToolResult(ok=False, error=blocked)

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(args["content"], encoding="utf-8")
        return ToolResult(ok=True, data=f"Wrote {len(args['content'])} chars to {rel}")


class ListDirTool(Tool):
    name = "fs.list_dir"
    category = "filesystem"
    description = (
        "List files and directories. Supports glob patterns. " "Returns file names with type indicators (/ for dirs)."
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

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()

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

        entries: list[str] = []
        try:
            for p in sorted(base.glob(pattern)):
                if len(entries) >= max_results:
                    entries.append(f"... (truncated at {max_results} results)")
                    break
                rel_path = p.relative_to(self._root)
                suffix = "/" if p.is_dir() else ""
                entries.append(f"{rel_path}{suffix}")
        except (OSError, ValueError) as e:
            return ToolResult(ok=False, error=f"Glob error: {e}")

        if not entries:
            return ToolResult(ok=True, data="(empty directory)")
        return ToolResult(ok=True, data="\n".join(entries))


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
                "description": "Directory to search in (default: project root)",
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

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()

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

        try:
            regex = re.compile(pattern_str, re.IGNORECASE)
        except re.error as e:
            return ToolResult(ok=False, error=f"Invalid regex: {e}")

        matches: list[str] = []
        files_searched = 0
        _skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".tox"}

        for dirpath, dirnames, filenames in os.walk(base):
            # Skip common non-content directories
            dirnames[:] = [d for d in dirnames if d not in _skip_dirs]

            for fname in filenames:
                if not fnmatch.fnmatch(fname, file_glob):
                    continue
                fpath = Path(dirpath) / fname
                files_searched += 1

                try:
                    text = fpath.read_text(encoding="utf-8", errors="replace")
                except (OSError, UnicodeDecodeError):
                    continue

                for lineno, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        rel_path = fpath.relative_to(self._root)
                        matches.append(f"{rel_path}:{lineno}: {line.rstrip()}")
                        if len(matches) >= max_results:
                            break
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break

        if not matches:
            return ToolResult(
                ok=True,
                data=f"No matches found (searched {files_searched} files)",
            )
        header = f"Found {len(matches)} matches (searched {files_searched} files):\n"
        return ToolResult(ok=True, data=header + "\n".join(matches))


def register_filesystem_tools(registry: Any, sandbox_root: Path, max_file_size: int = 5_000_000) -> None:
    """Register all filesystem tools with the registry."""
    registry.register(ReadFileTool(sandbox_root, max_file_size))
    registry.register(WriteFileTool(sandbox_root))
    registry.register(ListDirTool(sandbox_root))
    registry.register(SearchFilesTool(sandbox_root))
