"""Sandboxed source-tree search tools for live code files.

Registers the ``code.*`` tools used by the server, CLI, and agent loop for
regex search, definition/reference lookup, and project-structure inspection.
This is intentionally separate from ``thomas.tools.search_code``, which exposes
the indexed ``rag.search`` adapter.

Uses ripgrep (rg) subprocess when available for speed and .gitignore awareness,
with a pure Python fallback for environments without rg.
"""

from __future__ import annotations

import asyncio
import re
import shutil
from pathlib import Path
from typing import Any

from thomas.core.file_access import path_is_inside
from thomas.tools import code_search_scan as scan
from thomas.tools import fs_scope
from thomas.tools.base import Tool, ToolResult
from thomas.tools.semantic_search import register_semantic_search_tool

# One skip list for every code.* scan, defined with the walk that uses it. It
# gained ".thomas" when code.find_definition was measured spending 227.5 s
# inside Thomas's own state directories -- see code_search_scan's docstring.
_SKIP_DIRS = scan.SKIP_DIRS
# The dotfiles worth seeing in code.project_structure, which hides the rest.
_TREE_DOTFILES = frozenset({".gitignore", ".env.example", ".github"})

_CODE_EXTS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".rb",
    ".php",
    ".swift",
    ".kt",
    ".scala",
    ".lua",
    ".sh",
    ".bash",
    ".ps1",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".xml",
    ".html",
    ".css",
    ".scss",
    ".sql",
    ".md",
    ".rst",
    ".txt",
}


def _inside_root(root: Path, rel: str) -> Path:
    """``rel`` as a real path, or ValueError if that is not inside ``root`` or is closed to agent tools.

    Compares folders, not characters: ``C:\\x\\work2`` starts with ``C:\\x\\work`` and is not inside it. ``root`` is the
    tool's own, resolved once when it was built. ``filesystem._safe_path`` resolves its root again on every call, so a
    root replaced by a link afterwards passes there, and it does not pass here. Naming a file outright gets past rg's
    every filter, so the signing key is refused here, for the same reason the fs tools refuse it.
    """
    scope = fs_scope.scopes().scope(root)
    try:
        target = scope.resolve(rel)
    except ValueError as exc:
        raise ValueError("Path escapes sandbox") from exc
    # The scope resolves its root again; the tool's own was pinned when it was built, and a path must be inside that.
    if not path_is_inside(target, root):
        raise ValueError("Path escapes sandbox")
    blocked = scope.read_refusal(rel)
    if blocked:
        raise ValueError(blocked)
    return target


def _rg_target(pattern: str, path: Path) -> list[str]:
    """The end of an rg command: what to look for and where, neither of which can be read as a flag.

    A bare ``pattern`` is parsed like any other argument, so ``-Lemarker`` followed links, ``--file=x`` tested the
    contents of ``x``, and ``--pre=x`` ran ``x`` on every file. Any other text a caller gives rg goes in ``--flag=value``.
    """
    return ["-e", pattern, "--", str(path)]


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class CodeSearchTool(Tool):
    name = "code.search"
    category = "code"
    description = (
        "Search for patterns in code using regex. Uses ripgrep when available for "
        "speed and .gitignore awareness. Supports context lines and glob filtering. "
        "Prefer this over fs.search for code-specific searches."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "description": "Regex or literal pattern to search for",
            },
            "path": {
                "type": "string",
                "description": "Directory or file to search (default: project root)",
            },
            "glob": {
                "type": "string",
                "description": "File glob filter (e.g. '*.py', '*.{ts,tsx}')",
            },
            "context": {
                "type": "integer",
                "description": "Lines of context around each match (default: 0)",
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Case-sensitive search (default: false)",
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
        self._has_rg = shutil.which("rg") is not None

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        if self._has_rg:
            return await self._search_rg(args)
        return await self._search_python(args)

    async def _search_rg(self, args: dict[str, Any]) -> ToolResult:
        pattern = args["pattern"]
        rel = args.get("path", ".")
        try:
            search_path = _inside_root(self._root, rel)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

        cmd: list[str] = ["rg", "--line-number", "--with-filename"]
        if not args.get("case_sensitive", False):
            cmd.append("--ignore-case")
        ctx = args.get("context", 0)
        if ctx > 0:
            cmd += ["-C", str(ctx)]
        if args.get("glob"):
            cmd.append(f"--glob={args['glob']}")
        # After the caller's glob, because rg lets the last match win, and one that asks for a dotfile reads past the
        # rule that skips them.
        cmd += ["--glob=!**/thomas_rag_index/**", f"--glob=!**/{scan.KEY_NAME}"]
        cmd.append(f"--max-count={args.get('max_results', 50)}")
        cmd += _rg_target(pattern, search_path)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._root),
            )
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=30)
        except asyncio.TimeoutError:
            return ToolResult(ok=False, error="Search timed out after 30s")
        except FileNotFoundError:
            # rg disappeared since init
            self._has_rg = False
            return await self._search_python(args)
        except NotADirectoryError:
            # Windows' answer when the working folder, the root, does not exist. rg itself is fine.
            return await self._search_python(args)

        stdout = stdout_b.decode("utf-8", errors="replace")
        stderr = stderr_b.decode("utf-8", errors="replace")
        stdout_clean = stdout.rstrip()
        stderr_clean = stderr.strip()

        if proc.returncode == 0:
            return ToolResult(ok=True, data=stdout_clean or "(no matches)")
        elif proc.returncode == 1:
            return ToolResult(ok=True, data="No matches found")
        else:
            # rg can return non-1 errors on Windows for special device paths
            # (for example `nul`) while still producing useful match output.
            if stdout_clean:
                if stderr_clean:
                    return ToolResult(ok=True, data=f"{stdout_clean}\n[rg warning] {stderr_clean}")
                return ToolResult(ok=True, data=stdout_clean)

            py_result = await self._search_python(args)
            if py_result.ok and stderr_clean:
                py_data = str(py_result.data or "").strip()
                py_result.data = (
                    f"{py_data}\n[rg warning] {stderr_clean}" if py_data else f"[rg warning] {stderr_clean}"
                )
            if py_result.ok:
                return py_result
            return ToolResult(ok=False, error=stderr_clean or py_result.error or "rg error")

    async def _search_python(self, args: dict[str, Any]) -> ToolResult:
        rel = args.get("path", ".")
        flags = 0 if args.get("case_sensitive") else re.IGNORECASE

        try:
            base = _inside_root(self._root, rel)
        except (OSError, ValueError, RuntimeError) as e:
            return ToolResult(ok=False, error=str(e))

        try:
            regex = re.compile(args["pattern"], flags)
        except re.error as e:
            return ToolResult(ok=False, error=f"Invalid regex: {e}")

        # In a worker thread: this walk runs on the event loop otherwise, and a
        # Build child agent's tool call is a task on the server's loop.
        matches, searched, note = await asyncio.to_thread(
            scan.search_lines,
            base,
            self._root,
            regex,
            file_glob=args.get("glob", "*"),
            context=args.get("context", 0),
            max_results=args.get("max_results", 50),
        )
        if not matches:
            return ToolResult(ok=True, data=f"No matches found (searched {searched} files){note}")
        return ToolResult(ok=True, data=f"Found matches (searched {searched} files):\n" + "\n".join(matches) + note)


class FindDefinitionTool(Tool):
    name = "code.find_definition"
    category = "code"
    description = (
        "Find where a function, class, or variable is defined. Returns file path, line number, and surrounding context."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Symbol name to find (function, class, variable)",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: project root)",
            },
            "language": {
                "type": "string",
                "description": "Language hint: python, javascript, typescript, go, rust",
            },
        },
        "required": ["symbol"],
    }

    _PATTERNS: dict[str, list[str]] = {
        "python": [
            r"^(class|def|async\s+def)\s+{symbol}\s*[:(]",
            r"^{symbol}\s*=\s*",
        ],
        "javascript": [
            r"(function\s+{symbol}|const\s+{symbol}\s*=|let\s+{symbol}\s*=|var\s+{symbol}\s*=|class\s+{symbol})",
        ],
        "typescript": [
            r"(function\s+{symbol}|const\s+{symbol}|let\s+{symbol}|var\s+{symbol}|class\s+{symbol}|interface\s+{symbol}|type\s+{symbol})",
        ],
        "go": [
            r"func\s+(\([^)]+\)\s+)?{symbol}\s*\(",
            r"type\s+{symbol}\s+(struct|interface)",
        ],
        "rust": [
            r"(fn|struct|enum|trait|type|const|static)\s+{symbol}\b",
        ],
    }

    _LANG_EXTS: dict[str, set[str]] = {
        "python": {".py"},
        "javascript": {".js", ".jsx", ".mjs"},
        "typescript": {".ts", ".tsx"},
        "go": {".go"},
        "rust": {".rs"},
    }

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        symbol = re.escape(args["symbol"])
        lang = args.get("language", "").lower()
        rel = args.get("path", ".")

        try:
            base = _inside_root(self._root, rel)
        except (OSError, ValueError, RuntimeError) as e:
            return ToolResult(ok=False, error=str(e))

        # Build regex patterns
        patterns: list[re.Pattern[str]] = []
        if lang in self._PATTERNS:
            for p in self._PATTERNS[lang]:
                patterns.append(re.compile(p.format(symbol=symbol), re.MULTILINE))
        else:
            patterns = [
                re.compile(rf"(def|class|function|const|let|var|type|interface|fn|struct|enum|trait)\s+{symbol}\b"),
                re.compile(rf"^{symbol}\s*[=:(]", re.MULTILINE),
            ]

        # Filter by language extensions if specified
        exts = self._LANG_EXTS.get(lang, _CODE_EXTS)

        # Python definitions use an incremental per-project index. Other languages
        # and ambiguous lookups retain the original bounded scan and its semantics.
        if lang == "python" and base.is_dir() and args["symbol"].isidentifier():
            from thomas.tools.code_definition_index import find_definitions

            indexed = await asyncio.to_thread(find_definitions, self._root, base, args["symbol"])
            if indexed is not None:
                if not indexed:
                    return ToolResult(ok=True, data=f"No definition found for '{args['symbol']}'")
                return ToolResult(ok=True, data="\n\n".join(indexed))

        # Scans still run off the event loop and keep their existing budget note.
        results, note = await asyncio.to_thread(scan.find_symbol, base, self._root, patterns, exts)
        if not results:
            return ToolResult(ok=True, data=f"No definition found for '{args['symbol']}'{note}")
        return ToolResult(ok=True, data="\n\n".join(results) + note)


class FindReferencesTool(Tool):
    name = "code.find_references"
    category = "code"
    description = (
        "Find all usages of a symbol (function calls, imports, references). "
        "Uses word-boundary matching to avoid false substring matches."
    )
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "Symbol name to find references for",
            },
            "path": {
                "type": "string",
                "description": "Directory to search in (default: project root)",
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum results to return (default: 30)",
            },
        },
        "required": ["symbol"],
    }

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()
        self._has_rg = shutil.which("rg") is not None

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        symbol = args["symbol"]
        rel = args.get("path", ".")
        max_results = args.get("max_results", 30)

        try:
            base = _inside_root(self._root, rel)
        except (OSError, ValueError, RuntimeError) as e:
            return ToolResult(ok=False, error=str(e))

        pattern = rf"\b{re.escape(symbol)}\b"

        if self._has_rg:
            cmd = [
                "rg",
                "--line-number",
                "--with-filename",
                f"--max-count={max_results}",
                *_rg_target(pattern, base),
            ]
            try:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    cwd=str(self._root),
                )
                out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
                if proc.returncode in (0, 1):
                    data = out.decode("utf-8", errors="replace").rstrip()
                    return ToolResult(ok=True, data=data or "No references found")
            except (FileNotFoundError, NotADirectoryError, asyncio.TimeoutError):
                pass  # fall through to Python

        # Python fallback, in a worker thread for the same reason as the rest.
        results, _searched, note = await asyncio.to_thread(
            scan.search_lines,
            base,
            self._root,
            re.compile(pattern),
            exts=_CODE_EXTS,
            max_results=max_results,
        )
        if not results:
            return ToolResult(ok=True, data=f"No references found for '{symbol}'{note}")
        return ToolResult(ok=True, data="\n".join(results) + note)


class ProjectStructureTool(Tool):
    name = "code.project_structure"
    category = "code"
    description = (
        "Show the project directory tree. Skips common non-content directories "
        "(.git, node_modules, etc.). Useful for understanding project layout."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Directory to show (default: project root)",
            },
            "max_depth": {
                "type": "integer",
                "description": "Maximum directory depth (default: 4)",
            },
            "show_files": {
                "type": "boolean",
                "description": "Include files, not just directories (default: true)",
            },
        },
    }

    def __init__(self, sandbox_root: Path):
        self._root = sandbox_root.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        rel = args.get("path", ".")
        max_depth = args.get("max_depth", 4)
        show_files = args.get("show_files", True)

        try:
            base = _inside_root(self._root, rel)
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

        if not base.is_dir():
            return ToolResult(ok=False, error=f"Not a directory: {rel}")

        def _tree() -> list[str]:
            lines: list[str] = [base.name or "."]
            self._walk_tree(base, "", 0, max_depth, show_files, lines)
            return lines

        # iterdir per directory, four levels deep by default: disk work, and
        # therefore not the event loop's.
        return ToolResult(ok=True, data="\n".join(await asyncio.to_thread(_tree)))

    def _walk_tree(
        self,
        path: Path,
        prefix: str,
        depth: int,
        max_depth: int,
        show_files: bool,
        lines: list[str],
    ) -> None:
        if depth >= max_depth:
            return
        folders, files, links = scan.list_folder(path)

        # (sorts last, name, what the tree shows, whether to go in). A link is named and never entered.
        rows = [(False, name, f"{name}/", True) for name in folders]
        rows += [(False, name, f"{name} (link, not followed)", False) for name in links]
        if show_files:
            rows += [(True, name, name, False) for name in files]

        # Filter skip dirs, keep important dotfiles
        shown = [
            row for row in rows if (row[1] not in _SKIP_DIRS and not row[1].startswith(".")) or row[1] in _TREE_DOTFILES
        ]
        shown.sort(key=lambda row: (row[0], row[1].lower()))

        for i, (_sorts_last, name, label, go_in) in enumerate(shown):
            is_last = i == len(shown) - 1
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "

            lines.append(f"{prefix}{connector}{label}")
            if go_in:
                self._walk_tree(path / name, prefix + extension, depth + 1, max_depth, show_files, lines)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_code_search_tools(registry: Any, sandbox_root: Path) -> None:
    """Register all code search tools with the registry."""
    registry.register(CodeSearchTool(sandbox_root))
    registry.register(FindDefinitionTool(sandbox_root))
    registry.register(FindReferencesTool(sandbox_root))
    registry.register(ProjectStructureTool(sandbox_root))
    # Semantic (concept) search over the RAG index — lives alongside the lexical
    # code.* tools so the agent can retrieve code by meaning, not just keywords.
    register_semantic_search_tool(registry, sandbox_root=sandbox_root, extensions=sorted(_CODE_EXTS))
