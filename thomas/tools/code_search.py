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
import fnmatch
import os
import re
import shutil
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult
from thomas.tools.semantic_search import register_semantic_search_tool

_SKIP_DIRS = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
}

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
            search_path = (self._root / rel).resolve()
            if not str(search_path).startswith(str(self._root)):
                return ToolResult(ok=False, error="Path escapes sandbox")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

        cmd: list[str] = ["rg", "--line-number", "--with-filename"]
        if not args.get("case_sensitive", False):
            cmd.append("--ignore-case")
        ctx = args.get("context", 0)
        if ctx > 0:
            cmd += ["-C", str(ctx)]
        if args.get("glob"):
            cmd += ["--glob", args["glob"]]
        max_results = args.get("max_results", 50)
        cmd += ["--max-count", str(max_results)]
        cmd += [pattern, str(search_path)]

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
        pattern_str = args["pattern"]
        rel = args.get("path", ".")
        file_glob = args.get("glob", "*")
        context_n = args.get("context", 0)
        max_results = args.get("max_results", 50)
        flags = 0 if args.get("case_sensitive") else re.IGNORECASE

        try:
            base = (self._root / rel).resolve()
            if not str(base).startswith(str(self._root)):
                return ToolResult(ok=False, error="Path escapes sandbox")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

        try:
            regex = re.compile(pattern_str, flags)
        except re.error as e:
            return ToolResult(ok=False, error=f"Invalid regex: {e}")

        matches: list[str] = []
        files_searched = 0

        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                if file_glob != "*" and not fnmatch.fnmatch(fname, file_glob):
                    continue
                fpath = Path(dirpath) / fname
                files_searched += 1
                try:
                    lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue

                rel_path = fpath.relative_to(self._root)
                for lineno, line in enumerate(lines, 1):
                    if regex.search(line):
                        if context_n > 0:
                            start = max(0, lineno - 1 - context_n)
                            end = min(len(lines), lineno + context_n)
                            for i in range(start, end):
                                prefix = ">" if i == lineno - 1 else " "
                                matches.append(f"{rel_path}:{i + 1}{prefix} {lines[i]}")
                            matches.append("--")
                        else:
                            matches.append(f"{rel_path}:{lineno}: {line.rstrip()}")
                        if len(matches) >= max_results:
                            break
                if len(matches) >= max_results:
                    break
            if len(matches) >= max_results:
                break

        if not matches:
            return ToolResult(ok=True, data=f"No matches found (searched {files_searched} files)")
        header = f"Found matches (searched {files_searched} files):\n"
        return ToolResult(ok=True, data=header + "\n".join(matches))


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
            base = (self._root / rel).resolve()
            if not str(base).startswith(str(self._root)):
                return ToolResult(ok=False, error="Path escapes sandbox")
        except Exception as e:
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

        results: list[str] = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                if Path(fname).suffix not in exts:
                    continue
                fpath = Path(dirpath) / fname
                try:
                    lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                rel_path = fpath.relative_to(self._root)
                for lineno, line in enumerate(lines, 1):
                    if any(p.search(line) for p in patterns):
                        start = max(0, lineno - 1)
                        end = min(len(lines), lineno + 3)
                        ctx = "\n".join(f"  {i + 1}: {lines[i]}" for i in range(start, end))
                        results.append(f"{rel_path}:{lineno}\n{ctx}")
                        if len(results) >= 20:
                            break
            if len(results) >= 20:
                break

        if not results:
            return ToolResult(ok=True, data=f"No definition found for '{args['symbol']}'")
        return ToolResult(ok=True, data="\n\n".join(results))


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
            base = (self._root / rel).resolve()
            if not str(base).startswith(str(self._root)):
                return ToolResult(ok=False, error="Path escapes sandbox")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

        pattern = rf"\b{re.escape(symbol)}\b"

        if self._has_rg:
            cmd = [
                "rg",
                "--line-number",
                "--with-filename",
                "-m",
                str(max_results),
                pattern,
                str(base),
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
            except (FileNotFoundError, asyncio.TimeoutError):
                pass  # fall through to Python

        # Python fallback
        compiled = re.compile(pattern)
        results: list[str] = []
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
            for fname in filenames:
                if Path(fname).suffix not in _CODE_EXTS:
                    continue
                fpath = Path(dirpath) / fname
                try:
                    lines = fpath.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    continue
                rel_path = fpath.relative_to(self._root)
                for lineno, line in enumerate(lines, 1):
                    if compiled.search(line):
                        results.append(f"{rel_path}:{lineno}: {line.rstrip()}")
                        if len(results) >= max_results:
                            break
            if len(results) >= max_results:
                break

        if not results:
            return ToolResult(ok=True, data=f"No references found for '{symbol}'")
        return ToolResult(ok=True, data="\n".join(results))


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
            base = (self._root / rel).resolve()
            if not str(base).startswith(str(self._root)):
                return ToolResult(ok=False, error="Path escapes sandbox")
        except Exception as e:
            return ToolResult(ok=False, error=str(e))

        if not base.is_dir():
            return ToolResult(ok=False, error=f"Not a directory: {rel}")

        lines: list[str] = [base.name or "."]
        self._walk_tree(base, "", 0, max_depth, show_files, lines)
        return ToolResult(ok=True, data="\n".join(lines))

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
        try:
            entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        except PermissionError:
            return

        # Filter skip dirs, keep important dotfiles
        visible = [e for e in entries if e.name not in _SKIP_DIRS and not e.name.startswith(".")]
        dotfiles = [e for e in entries if e.name in {".gitignore", ".env.example", ".github"}]
        all_entries = sorted(set(visible + dotfiles), key=lambda p: (p.is_file(), p.name.lower()))

        if not show_files:
            all_entries = [e for e in all_entries if e.is_dir()]

        for i, entry in enumerate(all_entries):
            is_last = i == len(all_entries) - 1
            connector = "└── " if is_last else "├── "
            extension = "    " if is_last else "│   "

            if entry.is_dir():
                lines.append(f"{prefix}{connector}{entry.name}/")
                self._walk_tree(entry, prefix + extension, depth + 1, max_depth, show_files, lines)
            else:
                lines.append(f"{prefix}{connector}{entry.name}")


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
    register_semantic_search_tool(registry)
