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


_NOT_A_REPO = "not a git repository"


def _git_result(rc: int, stdout: str, stderr: str, cwd: Path | None = None) -> ToolResult:
    """Convert git subprocess output to a ToolResult.

    Outside a repository every git tool used to hand the model git's own
    ``fatal: not a git repository`` and nothing else; on TB-4.0 run 3 the
    model retried git.status three times in /app and the loop's stability
    guard killed the run. The refusal now says where git looked and what to
    use instead, and it is byte-identical on every retry so a repeat is
    recognised as a repeat.
    """
    if rc == 0:
        return ToolResult(ok=True, data=stdout.rstrip() or "(no output)")
    combined = stderr.strip() or stdout.strip() or "unknown git error"
    if _NOT_A_REPO in combined.lower():
        where = str(cwd) if cwd is not None else "the working directory"
        return ToolResult(
            ok=False,
            error=(
                f"{where} is not a git repository (no .git here or in any parent), so the git "
                "tools cannot be used for it. Do not call them again for this folder: use "
                "fs.list_dir / fs.read_file to inspect files and shell.exec for other commands."
            ),
        )
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
        return _git_result(rc, stdout, stderr, self._cwd)


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
        return _git_result(rc, stdout, stderr, self._cwd)


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
        return _git_result(rc, stdout, stderr, self._cwd)


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
        return _git_result(rc, stdout, stderr, self._cwd)


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
        return _git_result(rc, stdout, stderr, self._cwd)


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


async def _gh_run(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run the GitHub CLI. Returns (returncode, stdout, stderr); -1 when gh is missing."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "gh",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(cwd),
        )
        stdout_b, stderr_b = await proc.communicate()
    except FileNotFoundError:
        return -1, "", "gh executable not found in PATH"
    return (
        proc.returncode or 0,
        stdout_b.decode("utf-8", errors="replace"),
        stderr_b.decode("utf-8", errors="replace"),
    )


class GitPullRequestTool(Tool):
    name = "git.pull_request"
    category = "git"
    description = (
        "Open a pull request for the current branch with the GitHub CLI (gh). Give a clear title and a body that "
        "says what changed and why. Set push=true to push the branch first; it is never pushed otherwise."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "Pull request title."},
            "body": {"type": "string", "description": "Pull request description (Markdown)."},
            "base": {"type": "string", "description": "Base branch (default: the repository default)."},
            "draft": {"type": "boolean", "description": "Open as a draft (default false)."},
            "push": {"type": "boolean", "description": "Push the current branch to origin first (default false)."},
        },
        "required": ["title", "body"],
    }

    def __init__(self, working_dir: Path):
        self._cwd = working_dir.resolve()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        title = str(args.get("title") or "").strip()
        body = str(args.get("body") or "").strip()
        if not title:
            return ToolResult(ok=False, error="git.pull_request needs a title.")
        if bool(args.get("push", False)):
            rc, out, err = await _git_run(["push", "-u", "origin", "HEAD"], self._cwd)
            if rc != 0:
                return ToolResult(ok=False, error=f"push failed before the pull request: {err.strip() or out.strip()}")
        gh_args = ["pr", "create", "--title", title, "--body", body or title]
        base = str(args.get("base") or "").strip()
        if base:
            gh_args += ["--base", base]
        if bool(args.get("draft", False)):
            gh_args.append("--draft")
        rc, out, err = await _gh_run(gh_args, self._cwd)
        if rc == -1:
            return ToolResult(
                ok=False,
                error="The GitHub CLI (gh) is not installed or not on PATH; install it and run `gh auth login`.",
            )
        if rc != 0:
            return ToolResult(ok=False, error=(err.strip() or out.strip() or "gh pr create failed"))
        return ToolResult(
            ok=True, data={"url": out.strip().splitlines()[-1] if out.strip() else "", "output": out.strip()}
        )


def register_git_tools(registry: Any, working_dir: Path) -> None:
    """Register all git tools with the registry."""
    registry.register(GitStatusTool(working_dir))
    registry.register(GitDiffTool(working_dir))
    registry.register(GitLogTool(working_dir))
    registry.register(GitCommitTool(working_dir))
    registry.register(GitBlameTool(working_dir))
    registry.register(GitPullRequestTool(working_dir))
