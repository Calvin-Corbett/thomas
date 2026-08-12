"""Shell execution tool with sandboxing and timeout."""

from __future__ import annotations

import asyncio
import functools
import os
import re
import sys
from pathlib import Path
from typing import Any

from thomas.tools.base import Tool, ToolResult
from thomas.tools.filesystem import _safe_path
from thomas.tools.shell_spool import (
    OUTCOME_HUNG,
    OUTCOME_NOT_FOUND,
    OUTCOME_TIMEOUT,
    SpoolResult,
    run_spooled_command,
)

_GIT_TOPOLOGY_MUTATION_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bgit\s+clone\b", re.I), "git clone"),
    (re.compile(r"\bgit\s+init\b", re.I), "git init"),
    (
        re.compile(r"\bgit\s+worktree\s+(?:add|move|remove|prune|repair)\b", re.I),
        "git worktree mutation",
    ),
    (
        re.compile(r"\bgit\s+(?:checkout|switch)\s+[^;&|\n]*(?:-b|-B|-c|-C|--create|--orphan)\b", re.I),
        "git branch creation",
    ),
    (
        re.compile(
            r"\bgit\s+branch\s+"
            r"(?!(?:$|-(?:a|r|v|vv|av|va|rv|vr|ar|ra)\b|"
            r"--(?:all|list|show-current|contains|merged|no-merged|remotes|verbose|"
            r"format|points-at|sort|color|column|abbrev)(?:=|\b)))",
            re.I,
        ),
        "git branch mutation",
    ),
)


def _git_topology_mutation_reason(command: str) -> str | None:
    text = str(command or "").strip()
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", text)
    for pattern, label in _GIT_TOPOLOGY_MUTATION_PATTERNS:
        if pattern.search(normalized):
            return (
                "Blocked by Thomas repo-topology guard: agents cannot create side clones, "
                f"branches, or worktrees with shell.exec ({label}). Work in the assigned "
                "canonical checkout and ask the human for an explicit repository-topology change."
            )
    return None


class ShellTool(Tool):
    name = "shell.exec"
    category = "shell"
    description = (
        "Execute a shell command and return its output. "
        "Commands run in the project directory with a timeout. "
        "Use for: running tests, installing packages, git operations, "
        "build commands, and other system tasks."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default: 30, max: 300)",
            },
            "cwd": {
                "type": "string",
                "description": "Working directory (relative to project root)",
            },
        },
        "required": ["command"],
    }

    def __init__(
        self,
        working_dir: Path,
        default_timeout: int = 30,
        max_timeout: int = 300,
        allowed: bool = True,
        idle_timeout: float = 120.0,
        hang_retries: int = 1,
    ):
        self._cwd = working_dir.resolve()
        self._default_timeout = default_timeout
        self._max_timeout = max_timeout
        self._allowed = allowed
        # Hang detection: kill the process tree if it is still running but has
        # produced no output for this many seconds, then retry automatically.
        self._idle_timeout = idle_timeout
        self._hang_retries = hang_retries

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        if not self._allowed:
            return ToolResult(
                ok=False,
                error="Shell execution is disabled in configuration (tools.allow_shell = false)",
            )

        command = args["command"]
        topology_block = _git_topology_mutation_reason(command)
        if topology_block:
            return ToolResult(ok=False, error=topology_block)

        timeout = min(
            args.get("timeout", self._default_timeout),
            self._max_timeout,
        )
        cwd = self._cwd
        if "cwd" in args:
            rel = str(args["cwd"])
            try:
                cwd = _safe_path(self._cwd, rel)
            except ValueError as e:
                return ToolResult(ok=False, error=str(e))
            if not cwd.exists() or not cwd.is_dir():
                return ToolResult(ok=False, error=f"cwd is not a directory: {rel}")

        # Use appropriate shell for the platform
        if sys.platform == "win32":
            shell_cmd = ["cmd", "/c", command]
        else:
            shell_cmd = ["bash", "-c", command]

        # Spooled runner: streams output incrementally (no blocking
        # communicate()), writes the complete output to an on-disk spool file,
        # detects output-idle hangs, kills the process tree (Windows-safe), and
        # retries once on hang. Runs on a worker thread so it works on any
        # event loop (including Windows Selector loops, where asyncio
        # subprocesses raise NotImplementedError).
        loop = asyncio.get_running_loop()
        runner = functools.partial(
            run_spooled_command,
            shell_cmd,
            cwd=str(cwd),
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
            timeout=float(timeout),
            idle_timeout=self._idle_timeout,
            hang_retries=self._hang_retries,
        )
        result = await loop.run_in_executor(None, runner)

        if result.outcome == OUTCOME_NOT_FOUND:
            return ToolResult(
                ok=False,
                error=f"Shell not found. Command: {command}",
            )

        output = _format_spooled_output(result)

        if result.outcome == OUTCOME_TIMEOUT:
            return ToolResult(
                ok=False,
                data=output,
                error=f"Command timed out after {timeout}s: {command}",
            )

        if result.outcome == OUTCOME_HUNG:
            evidence = result.hang_events[-1]
            return ToolResult(
                ok=False,
                data=output,
                error=(
                    f"Command hung: no output for {evidence.idle_seconds:.1f}s; "
                    f"killed pid {evidence.killed_pid}; "
                    f"attempts {result.attempts}: {command}"
                ),
            )

        exit_code = result.exit_code
        return ToolResult(
            ok=exit_code == 0,
            data=output,
            error=f"Exit code {exit_code}" if exit_code != 0 else None,
        )


def _format_spooled_output(result: SpoolResult) -> str:
    """Build the inline (truncated) output string from a spooled run.

    Keeps the historical shape (stdout, ``[stderr]`` block, ``[exit code: N]``,
    100k truncation) and appends the spool file path — the complete output is
    always retrievable from disk — plus hang/retry evidence when a hang
    occurred.
    """
    parts: list[str] = []
    if result.stdout.strip():
        parts.append(result.stdout.rstrip())
    if result.stderr.strip():
        parts.append(f"[stderr]\n{result.stderr.rstrip()}")
    parts.append(f"[exit code: {result.exit_code}]")
    output = "\n".join(parts)

    # Truncate very long output inline; the spool file keeps everything.
    max_len = 100_000
    if len(output) > max_len:
        output = output[:max_len] + f"\n... (truncated, {len(output)} chars total; complete output in spool file)"

    output += f"\n[spool: {result.spool_path}]"
    if result.hang_events:
        evidence = result.hang_events[-1]
        output += (
            f"\n[hang-retry: attempts={result.attempts}, "
            f"last_idle={evidence.idle_seconds:.1f}s, "
            f"killed_pid={evidence.killed_pid}]"
        )
    return output


def register_shell_tools(registry: Any, working_dir: Path, config_timeout: int = 30, allowed: bool = True) -> None:
    """Register shell tools with the registry."""
    registry.register(ShellTool(working_dir, default_timeout=config_timeout, allowed=allowed))
