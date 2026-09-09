"""Immutable tool authority shared by foreground Chat and delegated workers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .chat_tool_policy_model import (
    _CHANNEL_PREFIXES,
    _CHANNEL_TOOLS,
    _EXTERNAL_PREFIXES,
    _EXTERNAL_TOOLS,
    _LOCAL_PATH_ARGUMENTS,
    _SAFE_READ_PREFIXES,
    _SAFE_READ_TOOLS,
    _SHELL_TOOLS,
    _TOOL_PREFIXES,
    _WRITE_PREFIXES,
    _WRITE_TOOLS,
    ToolRuntimePolicy,
)


def canonical_tool_name(name: Any) -> str:
    canonical = str(name or "").strip().casefold()
    for prefix in _TOOL_PREFIXES:
        if canonical.startswith(prefix):
            return canonical[len(prefix) :]
    return canonical


def _is_write_tool(name: str) -> bool:
    return name in _WRITE_TOOLS or name.startswith(_WRITE_PREFIXES)


def _is_classified_tool(name: str) -> bool:
    return bool(
        name in _SAFE_READ_TOOLS
        or name.startswith(_SAFE_READ_PREFIXES)
        or name in _SHELL_TOOLS
        or _is_write_tool(name)
        or name in _EXTERNAL_TOOLS
        or name.startswith(_EXTERNAL_PREFIXES)
        or name in _CHANNEL_TOOLS
        or name.startswith(_CHANNEL_PREFIXES)
        or name.startswith(("browser.", "git."))
    )


def _first_disabled_policy(policy: ToolRuntimePolicy) -> str:
    checks = (
        ("allow_shell", policy.allow_shell),
        ("allow_file_write", policy.allow_file_write),
        ("allow_network", policy.allow_network),
        ("allow_browser", policy.allow_browser),
        ("allow_channels", policy.allow_channels),
        ("allow_git", policy.allow_git),
    )
    return next((name for name, enabled in checks if not enabled), "")


def _tool_denial(name: str, policy: ToolRuntimePolicy) -> str:
    if not _is_classified_tool(name):
        disabled = _first_disabled_policy(policy)
        if disabled or policy.allowed_paths:
            boundary = disabled or "allowed_paths"
            return f"{boundary} policy denied unclassified tool capability"
    if name in _SHELL_TOOLS and not policy.allow_shell:
        return "allow_shell policy denied shell execution"
    if name in {"shell.exec", "ssh.exec"} and not policy.allow_file_write:
        return "allow_file_write policy denied unrestricted shell execution"
    if name in {"shell.exec", "ssh.exec"} and not policy.allow_network:
        return "allow_network policy denied unrestricted shell execution"
    if _is_write_tool(name) and not policy.allow_file_write:
        return "allow_file_write policy denied state mutation"
    if name.startswith("git.") and not policy.allow_git:
        return "allow_git policy denied git access"
    if name.startswith("browser.") and not policy.allow_browser:
        return "allow_browser policy denied browser access"
    if (name in _CHANNEL_TOOLS or name.startswith(_CHANNEL_PREFIXES)) and not policy.allow_channels:
        return "allow_channels policy denied connector access"
    if (name in _EXTERNAL_TOOLS or name.startswith(_EXTERNAL_PREFIXES)) and not policy.allow_network:
        return "allow_network policy denied external access"
    return ""


def _resolved_path(raw: Any, base_root: Path) -> Path | None:
    text = str(raw or "").strip()
    if not text:
        return None
    candidate = Path(text).expanduser()
    if not candidate.is_absolute():
        candidate = base_root / candidate
    try:
        return candidate.resolve(strict=False)
    except OSError:
        return None


def _path_allowed(raw: Any, allowed_paths: tuple[str, ...], base_root: Path) -> bool:
    candidate = _resolved_path(raw, base_root)
    if candidate is None:
        return False
    for raw_root in allowed_paths:
        root = _resolved_path(raw_root, base_root)
        if root is not None and (candidate == root or root in candidate.parents):
            return True
    return False


def _flatten_path_values(raw: Any) -> list[Any]:
    """Return scalar path arguments from either one path or a path collection."""
    if raw in (None, ""):
        return []
    if isinstance(raw, (list, tuple, set, frozenset)):
        values: list[Any] = []
        for item in raw:
            values.extend(_flatten_path_values(item))
        return values
    return [raw]


def _local_tool_paths(name: str, payload: dict[str, Any]) -> list[Any] | None:
    """Resolve declared local-path arguments, or ``None`` for non-path tools."""
    keys = _LOCAL_PATH_ARGUMENTS.get(name)
    if keys is None:
        return None
    paths: list[Any] = []
    for key in keys:
        paths.extend(_flatten_path_values(payload.get(key)))
    return paths


def policy_allows_path(policy: ToolRuntimePolicy, raw: Any, *, base_root: str | Path = ".") -> bool:
    """Return whether a concrete path is inside every configured runtime boundary."""
    if not policy.allowed_paths:
        return True
    return _path_allowed(raw, policy.allowed_paths, Path(base_root).resolve())


def _patch_paths(raw_patch: Any) -> list[str]:
    paths: list[str] = []
    for line in str(raw_patch or "").splitlines():
        if not line.startswith(("--- ", "+++ ")):
            continue
        path = line[4:].split("\t", 1)[0].strip()
        if path == "/dev/null":
            continue
        if path.startswith(("a/", "b/")):
            path = path[2:]
        if path:
            paths.append(path)
    return paths


class PolicyToolRegistryView:
    """Read-through registry view that hides and rejects policy-denied tools."""

    def __init__(self, base: Any, policy: ToolRuntimePolicy, *, base_root: str | Path = ".") -> None:
        self._base = base
        self.policy = policy
        self._base_root = Path(base_root).resolve()
        self.denied: list[str] = []

    def _resolved_name(self, name: Any) -> str:
        canonical = canonical_tool_name(name)
        try:
            tool = self._base.get(str(name or "")) or self._base.get(canonical)
        except (AttributeError, LookupError, TypeError, ValueError):
            tool = None
        return canonical_tool_name(getattr(tool, "name", "") or canonical)

    def _denial(self, name: Any, args: dict[str, Any] | None = None) -> str:
        canonical = self._resolved_name(name)
        denial = _tool_denial(canonical, self.policy)
        if denial:
            return denial
        payload = dict(args or {})
        ssh_action = str(payload.get("action") or "").strip().casefold() if canonical == "ssh.exec" else ""
        if canonical == "ssh.exec" and ssh_action in {"download", "upload", "write_file"}:
            if not self.policy.allow_file_write:
                return "allow_file_write policy denied SSH file mutation"
        is_command = canonical == "shell.exec" or (canonical == "ssh.exec" and ssh_action == "execute")
        if canonical in {"shell.exec", "ssh.exec"}:
            if self.policy.require_command_approval:
                return "require_command_approval policy blocks shell.exec"
            if is_command and self.policy.allowed_paths:
                return "allowed_paths policy disables unrestricted shell execution"
            if is_command and self.policy.blocked_commands:
                return "blocked_commands policy disables unrestricted shell execution"
        paths = _local_tool_paths(canonical, payload)
        if canonical == "ssh.exec" and (payload.get("key_path") or ssh_action in {"upload", "download"}):
            paths = _flatten_path_values(payload.get("key_path"))
            if ssh_action in {"upload", "download"}:
                paths.extend(_flatten_path_values(payload.get("local_path")))
        if args is not None and self.policy.allowed_paths and paths is not None:
            if not paths or any(not _path_allowed(path, self.policy.allowed_paths, self._base_root) for path in paths):
                return "allowed_paths policy denied filesystem access"
        if args is not None and self.policy.allowed_paths and canonical == "diff.apply_patch":
            paths = _patch_paths(payload.get("patch"))
            if not paths or any(not _path_allowed(path, self.policy.allowed_paths, self._base_root) for path in paths):
                return "allowed_paths policy denied patch target"
        return ""

    def get(self, name: str) -> Any | None:
        if self._denial(name):
            return None
        canonical = canonical_tool_name(name)
        return self._base.get(name) or (self._base.get(canonical) if canonical != name else None)

    def list_tools(self, category: str | None = None) -> list[Any]:
        return [tool for tool in self._base.list_tools(category) if not self._denial(getattr(tool, "name", ""))]

    def list_categories(self) -> list[str]:
        return sorted({str(tool.category) for tool in self.list_tools() if getattr(tool, "category", "")})

    def search(self, query: str, limit: int = 10) -> list[Any]:
        allowed = [tool for tool in self._base.search(query, limit=limit) if not self._denial(tool.name)]
        return allowed[:limit]

    def get_openai_specs(self, category: str | None = None) -> list[dict[str, Any]]:
        return [tool.get_spec().to_openai() for tool in self.list_tools(category)]

    async def execute(self, name: str, args: dict[str, Any]) -> Any:
        denial = self._denial(name, args)
        if denial:
            from thomas.tools.base import ToolResult

            self.denied.append(str(name))
            return ToolResult(ok=False, error=denial)
        canonical = canonical_tool_name(name)
        resolved = self._base.get(name)
        if resolved is None and canonical != name:
            resolved = self._base.get(canonical)
        return await self._base.execute(str(getattr(resolved, "name", "") or canonical), args)

    def __len__(self) -> int:
        return len(self.list_tools())

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None

    def __iter__(self):
        return iter(self.list_tools())

    def __bool__(self) -> bool:
        return bool(self.list_tools())


def tool_policy_from_payload(payload: dict[str, Any] | None) -> ToolRuntimePolicy | None:
    """Rehydrate the immutable tool subset passed to a background worker."""
    data = dict(payload or {})
    if not data:
        return None
    return ToolRuntimePolicy(
        allow_shell=bool(data.get("allow_shell", False)),
        allow_file_write=bool(data.get("allow_file_write", False)),
        allow_network=bool(data.get("allow_network", False)),
        allow_browser=bool(data.get("allow_browser", False)),
        allow_channels=bool(data.get("allow_channels", False)),
        allow_git=bool(data.get("allow_git", False)),
        require_command_approval=bool(data.get("require_command_approval", False)),
        tool_timeout_s=max(5, int(data.get("tool_timeout_s", 120) or 120)),
        max_parallel_tools=max(1, int(data.get("max_parallel_tools", 6) or 6)),
        allowed_paths=tuple(str(item) for item in data.get("allowed_paths", ()) if str(item).strip()),
        blocked_commands=tuple(str(item).casefold() for item in data.get("blocked_commands", ()) if str(item).strip()),
    )


__all__ = [
    "PolicyToolRegistryView",
    "ToolRuntimePolicy",
    "canonical_tool_name",
    "policy_allows_path",
    "tool_policy_from_payload",
]
