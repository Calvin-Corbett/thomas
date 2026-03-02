import asyncio
import fnmatch
import json
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class HookType(str, Enum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    STOP = "Stop"


@dataclass(frozen=True)
class HookConfig:
    hook_type: HookType
    matcher: str
    command: str
    timeout: int = 10


@dataclass
class HookResult:
    hook_type: HookType
    tool_name: str
    command: str
    exit_code: int
    stdout: str
    stderr: str
    error: str | None = None

    @property
    def success(self) -> bool:
        return self.exit_code == 0 and self.error is None

    @property
    def blocked(self) -> bool:
        return self.hook_type == HookType.PRE_TOOL_USE and self.exit_code == 2

    @property
    def display_status(self) -> str:
        if self.error is not None:
            return "error"
        if self.blocked:
            return "blocked"
        if self.success:
            return "success"
        return "failed"


class HookRunner:
    def __init__(self, hooks: list[HookConfig]) -> None:
        self._hooks = hooks

    @classmethod
    def from_project(cls, project_root: Path) -> "HookRunner":
        hooks = load_hooks_config(project_root)
        return cls(hooks)

    @property
    def has_hooks(self) -> bool:
        return len(self._hooks) > 0

    def get_hooks(self, hook_type: HookType, tool_name: str) -> list[HookConfig]:
        matching = []
        for hook in self._hooks:
            if hook.hook_type != hook_type:
                continue
            if fnmatch.fnmatch(tool_name, hook.matcher):
                matching.append(hook)
        return matching

    async def run_hooks(
        self,
        hook_type: HookType,
        tool_name: str,
        tool_args: Any | None = None,
        tool_result: Any | None = None,
    ) -> list["HookResult"]:
        hooks = self.get_hooks(hook_type, tool_name)
        results = []
        for hook in hooks:
            result = await self._run_single(hook, tool_name, tool_args, tool_result)
            results.append(result)
        return results

    async def _run_single(
        self,
        hook: HookConfig,
        tool_name: str,
        tool_args: Any | None,
        tool_result: Any | None,
    ) -> "HookResult":
        context = {
            "hook_type": hook.hook_type.value,
            "tool_name": tool_name,
            "tool_args": tool_args,
            "tool_result": tool_result,
        }
        stdin_data = json.dumps(context).encode("utf-8")
        try:
            proc = await asyncio.create_subprocess_shell(
                hook.command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(input=stdin_data),
                timeout=hook.timeout,
            )
            return HookResult(
                hook_type=hook.hook_type,
                tool_name=tool_name,
                command=hook.command,
                exit_code=proc.returncode if proc.returncode is not None else -1,
                stdout=stdout_bytes.decode("utf-8", errors="replace"),
                stderr=stderr_bytes.decode("utf-8", errors="replace"),
            )
        except asyncio.TimeoutError:
            return HookResult(
                hook_type=hook.hook_type,
                tool_name=tool_name,
                command=hook.command,
                exit_code=-1,
                stdout="",
                stderr="",
                error=f"Hook timed out after {hook.timeout}s",
            )
        except Exception as exc:
            return HookResult(
                hook_type=hook.hook_type,
                tool_name=tool_name,
                command=hook.command,
                exit_code=-1,
                stdout="",
                stderr="",
                error=str(exc),
            )


def load_hooks_config(project_root: Path) -> list[HookConfig]:
    """Load hooks configuration from .thomas/hooks.json or .thomas/settings.json."""
    thomas_dir = project_root / ".thomas"

    hooks_json = thomas_dir / "hooks.json"
    if hooks_json.exists():
        try:
            with open(hooks_json, encoding="utf-8") as f:
                data = json.load(f)
            return _parse_hooks_json(data)
        except Exception as exc:
            logger.warning("Failed to load hooks from %s: %s", hooks_json, exc)
            return []

    settings_json = thomas_dir / "settings.json"
    if settings_json.exists():
        try:
            with open(settings_json, encoding="utf-8") as f:
                data = json.load(f)
            if "hooks" in data:
                return _parse_hooks_json(data["hooks"])
        except Exception as exc:
            logger.warning("Failed to load hooks from %s: %s", settings_json, exc)
            return []

    return []


def _parse_hooks_json(data: Any) -> list[HookConfig]:
    """Parse hook JSON structure. Supports a top-level list or a dict with a nested "hooks" key."""
    if isinstance(data, dict) and "hooks" in data:
        data = data["hooks"]

    if not isinstance(data, list):
        logger.warning("Hooks config must be a list, got %s", type(data).__name__)
        return []

    configs: list[HookConfig] = []
    for entry in data:
        if not isinstance(entry, dict):
            logger.warning("Skipping invalid hook entry: %r", entry)
            continue
        try:
            raw_type = entry.get("type", "")
            hook_type = HookType(raw_type)
        except ValueError:
            logger.warning("Unknown hook type %r, skipping", entry.get("type"))
            continue
        matcher = entry.get("matcher", "*")
        command = entry.get("command", "")
        if not command:
            logger.warning("Hook entry missing command, skipping: %r", entry)
            continue
        timeout = int(entry.get("timeout", 10))
        configs.append(
            HookConfig(
                hook_type=hook_type,
                matcher=matcher,
                command=command,
                timeout=timeout,
            )
        )
    return configs


_TOOL_DISPLAY_NAMES: dict[str, str] = {
    "fs.read_file": "Read",
    "fs.write_file": "Write",
    "fs.edit_file": "Edit",
    "fs.delete_file": "Delete",
    "fs.list_dir": "List",
    "fs.create_dir": "MkDir",
    "fs.move": "Move",
    "fs.copy": "Copy",
    "shell.exec": "Ran command",
    "shell.run": "Ran command",
    "search.grep": "Grep",
    "search.glob": "Glob",
    "search.find": "Find",
    "web.fetch": "Fetch",
    "web.search": "Search",
    "git.status": "Git status",
    "git.diff": "Git diff",
    "git.commit": "Git commit",
    "git.log": "Git log",
    "git.add": "Git add",
    "git.push": "Git push",
    "git.pull": "Git pull",
    "notebook.read": "Read notebook",
    "notebook.edit": "Edit notebook",
}


def tool_display_name(tool_name: str) -> str:
    """Return a human-readable display name for a tool."""
    if tool_name in _TOOL_DISPLAY_NAMES:
        return _TOOL_DISPLAY_NAMES[tool_name]
    parts = tool_name.split(".")
    return parts[-1].replace("_", " ").title()


def tool_summary_line(tool_name: str, tool_args: Any | None, duration_ms: float) -> str:
    """Build a compact one-line summary for a tool call.

    Examples:
        Read: src/main.py (0.2s)
        Ran command: pytest tests/ (1.4s)
    """
    display = tool_display_name(tool_name)
    duration_s = duration_ms / 1000.0
    duration_str = f"({duration_s:.1f}s)"

    detail = ""
    if isinstance(tool_args, dict):
        for key in ("path", "file_path", "filepath", "command", "query", "pattern", "url"):
            if key in tool_args:
                val = str(tool_args[key])
                if len(val) > 60:
                    val = val[:57] + "..."
                detail = val
                break

    if detail:
        return f"{display}: {detail} {duration_str}"
    return f"{display} {duration_str}"


def format_hook_result_line(result: "HookResult") -> str:
    """Format a hook result as a single descriptive line.

    Example:
        PreToolUse:fs.write_file hook success
        PostToolUse:shell.exec hook error: timed out after 10s
    """
    prefix = f"{result.hook_type.value}:{result.tool_name} hook"
    status = result.display_status
    if result.error:
        return f"{prefix} {status}: {result.error}"
    return f"{prefix} {status}"
