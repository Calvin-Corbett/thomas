"""Git tools: status, diff, log, commit, blame.

All operations use subprocess calls to the git binary — no Python git
library required. Follows the same Tool pattern as shell.py.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult
from thomas.tools.filesystem import _safe_path


async def _git_run(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run a git subcommand. Returns (returncode, stdout, stderr)."""
    cmd = ["git"] + args
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
        )
        stdout_b, stderr_b = await proc.communicate()
    except FileNotFoundError:
        return -1, "", "git executable not found in PATH"
    return (
        proc.returncode or 0,
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
    )


def _git_result(rc: int, stdout: str, stderr: str) -> ToolResult:
    """Convert git subprocess output to a ToolResult."""
    if rc == 0:
        return ToolResult(ok=True, data=stdout.rstrip() or "(no output)")
    combined = stderr.strip() or stdout.strip() or "unknown git error"
    return ToolResult(ok=False, error=combined)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


class GitStatusTool(Tool):
    name = "git.status"
    category = "git"
    description = (
        "Show the working tree status: staged, unstaged, and untracked files. "
        "Use before commits to understand what has changed."
    )
    parameters = {
        "type": "object",
        "properties": {
            "short": {
                "type": "boolean",
                "description": "Use short format output (default: false)",
            },
        },
    }

    def __init__(self, working_dir: Path):
        self._cwd = working_dir.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        git_args = ["status"]
        if args.get("short"):
            git_args.append("--short")
        rc, stdout, stderr = await _git_run(git_args, self._cwd)
        return _git_result(rc, stdout, stderr)


class GitDiffTool(Tool):
    name = "git.diff"
    category = "git"
    description = (
        "Show changes between commits, working tree and index, or two refs. "
        "Without ref shows unstaged changes. With staged=true shows staged changes."
    )
    parameters = {
        "type": "object",
        "properties": {
            "ref": {
                "type": "string",
                "description": "Commit ref or range (e.g. 'HEAD', 'HEAD~1', 'main..feature')",
            },
            "staged": {
                "type": "boolean",
                "description": "Show staged changes (git diff --staged)",
            },
            "path": {
                "type": "string",
                "description": "Limit diff to this file or directory",
            },
        },
    }

    def __init__(self, working_dir: Path):
        self._cwd = working_dir.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        git_args = ["diff"]
        if args.get("staged"):
            git_args.append("--staged")
        if args.get("ref"):
            git_args.append(args["ref"])
        if args.get("path"):
            git_args += ["--", args["path"]]
        rc, stdout, stderr = await _git_run(git_args, self._cwd)
        return _git_result(rc, stdout, stderr)


class GitLogTool(Tool):
    name = "git.log"
    category = "git"
    description = "Show recent commit history with author, date, and message."
    parameters = {
        "type": "object",
        "properties": {
            "n": {
                "type": "integer",
                "description": "Number of commits to show (default: 10)",
            },
            "oneline": {
                "type": "boolean",
                "description": "Compact one-line format (default: true)",
            },
            "path": {
                "type": "string",
                "description": "Filter commits that touched this file or path",
            },
        },
    }

    def __init__(self, working_dir: Path):
        self._cwd = working_dir.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        n = args.get("n", 10)
        git_args = ["log", f"-{n}"]
        if args.get("oneline", True):
            git_args.append("--oneline")
        else:
            git_args += ["--pretty=format:%h %ad %an: %s", "--date=short"]
        if args.get("path"):
            git_args += ["--", args["path"]]
        rc, stdout, stderr = await _git_run(git_args, self._cwd)
        # Empty repo
        if rc != 0 and "does not have any commits" in stderr:
            return ToolResult(ok=True, data="(no commits yet)")
        return _git_result(rc, stdout, stderr)


class GitCommitTool(Tool):
    name = "git.commit"
    category = "git"
    description = "Stage specific files and create a commit. Only stages the listed files, not everything."
    parameters = {
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "Commit message",
            },
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of file paths to stage and commit",
            },
            "all_staged": {
                "type": "boolean",
                "description": "Commit everything currently staged (skip staging files list)",
            },
        },
        "required": ["message"],
    }

    def __init__(self, working_dir: Path):
        self._cwd = working_dir.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        message = args["message"]
        files = args.get("files", [])
        all_staged = args.get("all_staged", False)

        if not all_staged and files:
            # Validate paths are within sandbox
            for f in files:
                try:
                    _safe_path(self._cwd, f)
                except ValueError:
                    return ToolResult(ok=False, error=f"File outside project root: {f}")
            # Stage the specified files
            rc, stdout, stderr = await _git_run(["add", "--"] + files, self._cwd)
            if rc != 0:
                return ToolResult(ok=False, error=f"git add failed: {stderr.strip()}")

        rc, stdout, stderr = await _git_run(["commit", "-m", message], self._cwd)
        return _git_result(rc, stdout, stderr)


class GitBlameTool(Tool):
    name = "git.blame"
    category = "git"
    description = (
        "Show what revision and author last modified each line of a file. "
        "Useful for understanding when and by whom code was written."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "File path to blame",
            },
            "start_line": {
                "type": "integer",
                "description": "Start line for partial blame (1-based)",
            },
            "end_line": {
                "type": "integer",
                "description": "End line for partial blame (inclusive)",
            },
        },
        "required": ["file"],
    }

    def __init__(self, working_dir: Path):
        self._cwd = working_dir.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        file_path = args["file"]
        git_args = ["blame", "--date=short"]
        start = args.get("start_line")
        end = args.get("end_line")
        if start or end:
            s = start or 1
            e = end or ""
            git_args += ["-L", f"{s},{e}"]
        git_args.append(file_path)
        rc, stdout, stderr = await _git_run(git_args, self._cwd)
        return _git_result(rc, stdout, stderr)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register_git_tools(registry: Any, working_dir: Path) -> None:
    """Register all git tools with the registry."""
    registry.register(GitStatusTool(working_dir))
    registry.register(GitDiffTool(working_dir))
    registry.register(GitLogTool(working_dir))
    registry.register(GitCommitTool(working_dir))
    registry.register(GitBlameTool(working_dir))
