"""Git analysis and project statistics tools for the engineering toolkit.

Split out of thomas/tools/engineering.py with no behaviour change; that
module imports both classes back so every existing import keeps working.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult
from thomas.tools.fs_scope import Scope, scopes


class RootedTool(Tool):
    """A tool whose paths are the workspace's: resolved through the files slot, run from its root.

    With no root given the root is the working folder, as before. The slot is looked up on each call.
    """

    def __init__(self, root: Path | str | None = None) -> None:
        self._root = root

    def _scope(self) -> Scope:
        return scopes().scope(self._root if self._root is not None else Path.cwd())

    def _reach(self, rel: str, *, read: bool = False) -> tuple[Path | None, ToolResult | None]:
        """The real path ``rel`` names inside the root, or a refusal in the tool's own error shape."""
        scope = self._scope()
        try:
            if read and (blocked := scope.read_refusal(rel)):
                return None, ToolResult(ok=False, error=blocked)
            return scope.resolve(rel), None
        except (ValueError, OSError) as exc:
            return None, ToolResult(ok=False, error=str(exc))


# ---------------------------------------------------------------------------
# Git advanced analysis
# ---------------------------------------------------------------------------


class GitAnalysisTool(RootedTool):
    name = "eng.git_analysis"
    category = "engineering"
    description = (
        "Advanced git repository analysis: file change frequency (churn), "
        "contributor stats, and recent activity summary."
    )
    parameters = {
        "type": "object",
        "properties": {
            "repo_path": {
                "type": "string",
                "description": "Path to git repository. Default '.'.",
            },
            "analysis": {
                "type": "string",
                "description": "Type: 'churn' (most-changed files), 'contributors', 'recent'. Default 'recent'.",
            },
            "days": {
                "type": "integer",
                "description": "Look back N days. Default 30.",
            },
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            import git as gitmodule
        except ImportError:
            return ToolResult(ok=False, error="GitPython not installed (pip install gitpython)")
        repo_path, refused = self._reach(args.get("repo_path", "."))
        if refused:
            return refused
        repo_path = str(repo_path)
        analysis = args.get("analysis", "recent")
        days = args.get("days", 30)
        try:
            gitmodule.Repo(repo_path)
        except (gitmodule.InvalidGitRepositoryError, gitmodule.NoSuchPathError) as e:
            return ToolResult(ok=False, error=str(e))
        since = f"--since={days} days ago"
        if analysis == "churn":
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                repo_path,
                "log",
                since,
                "--name-only",
                "--pretty=format:",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._scope().root),
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            files: dict[str, int] = {}
            for line in stdout.decode("utf-8", errors="replace").splitlines():
                f = line.strip()
                if f:
                    files[f] = files.get(f, 0) + 1
            top = sorted(files.items(), key=lambda x: x[1], reverse=True)[:20]
            return ToolResult(ok=True, data=json.dumps([{"file": f, "changes": c} for f, c in top], indent=2))
        elif analysis == "contributors":
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                repo_path,
                "shortlog",
                "-sne",
                since,
                "HEAD",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._scope().root),
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            return ToolResult(ok=True, data=stdout.decode("utf-8", errors="replace").strip())
        else:  # recent
            proc = await asyncio.create_subprocess_exec(
                "git",
                "-C",
                repo_path,
                "log",
                since,
                "--oneline",
                "-30",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self._scope().root),
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
            return ToolResult(ok=True, data=stdout.decode("utf-8", errors="replace").strip())


# ---------------------------------------------------------------------------
# Project health / stats
# ---------------------------------------------------------------------------


class ProjectStatsTool(RootedTool):
    name = "eng.project_stats"
    category = "engineering"
    description = (
        "Get quick stats about a project: line counts by language, file counts, largest files, and directory sizes."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Path to project root. Default '.'.",
            },
        },
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        root, refused = self._reach(args.get("path", "."))
        if refused:
            return refused
        if not root.is_dir():
            return ToolResult(ok=False, error=f"Not a directory: {root}")
        ext_counts: dict[str, int] = {}
        ext_lines: dict[str, int] = {}
        largest: list = []
        total_files = 0
        skip = {".git", "__pycache__", "node_modules", ".mypy_cache", ".ruff_cache", "venv", ".venv"}
        for fpath in root.rglob("*"):
            if any(p in fpath.parts for p in skip):
                continue
            if not fpath.is_file():
                continue
            total_files += 1
            ext = fpath.suffix.lower() or "(none)"
            ext_counts[ext] = ext_counts.get(ext, 0) + 1
            size = fpath.stat().st_size
            largest.append((str(fpath), size))
            if ext in (".py", ".js", ".ts", ".jsx", ".tsx", ".css", ".html", ".md"):
                try:
                    lines = len(fpath.read_bytes().split(b"\n"))
                    ext_lines[ext] = ext_lines.get(ext, 0) + lines
                except OSError:
                    pass
        largest.sort(key=lambda x: x[1], reverse=True)
        return ToolResult(
            ok=True,
            data=json.dumps(
                {
                    "total_files": total_files,
                    "files_by_type": dict(sorted(ext_counts.items(), key=lambda x: x[1], reverse=True)[:15]),
                    "lines_by_type": dict(sorted(ext_lines.items(), key=lambda x: x[1], reverse=True)),
                    "largest_files": [{"path": p, "size_kb": round(s / 1024, 1)} for p, s in largest[:10]],
                },
                indent=2,
            ),
        )
