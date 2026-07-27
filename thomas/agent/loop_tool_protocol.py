"""Tool-call classification and recovery helpers for the main agent loop."""

from __future__ import annotations

import json
import re
from typing import Any

_MAX_TOOL_RESULT_CHARS = 5_000
_CODE_INSPECTION_TOOLS = frozenset(
    {
        "code.find_definition",
        "code.find_references",
        "code.project_structure",
        "code.search",
        "diff.preview",
        "fs.list_dir",
        "fs.read_file",
        "fs.search",
    }
)
_CODE_MUTATION_TOOLS = frozenset({"diff.apply_patch", "diff.create", "fs.write_file", "fs.write_protected_file"})
_CODE_SHELL_TOOLS = frozenset({"shell.exec"})
_CODE_TOOL_ALIASES = {
    tool.replace(".", "_"): tool for tool in _CODE_INSPECTION_TOOLS | _CODE_MUTATION_TOOLS | _CODE_SHELL_TOOLS
}
_MAX_PRE_EDIT_INSPECTIONS = 6
_MAX_POST_EDIT_INSPECTIONS = 6


def is_inspection_tool(tool_name: str) -> bool:
    """True when a tool can only look, never change anything.

    Callers deciding whether a run that changed no files nonetheless succeeded
    need this: reading a file to answer a question is not evidence of an edit
    that failed, while attempting a write and changing nothing is. Unknown names
    answer False, so an unrecognised tool is treated as capable of writing.
    """
    raw = str(tool_name or "").strip()
    if not raw:
        return False
    return _CODE_TOOL_ALIASES.get(raw, raw) in _CODE_INSPECTION_TOOLS
_SHELL_MUTATION_COMMAND_RE = re.compile(
    r"(?:^|[;&|]\s*|\s)(?:python(?:3)?|py|node|deno|bun|ruby|perl|cmd\s+/c|"
    r"sed\s+-i|npm\s+(?:i|install|uninstall|update)|npx|pnpm|yarn|"
    r"git\s+(?:add|apply|checkout|cherry-pick|clean|commit|merge|mv|pull|push|rebase|reset|restore|rm|switch))\b",
    re.IGNORECASE,
)


def _tool_spec_name(spec: object) -> str:
    if not isinstance(spec, dict):
        return ""
    function = spec.get("function")
    return str(spec.get("name") or (function.get("name") if isinstance(function, dict) else "") or "")


def _is_code_mutation_name(name: str) -> bool:
    return _canonical_code_tool_name(name) in _CODE_MUTATION_TOOLS


def _canonical_code_tool_name(name: str) -> str:
    value = str(name or "").lower()
    return _CODE_TOOL_ALIASES.get(value, value)


def _shell_command_is_mutation(args: dict[str, Any]) -> bool:
    command = str(args.get("command") or args.get("cmd") or args.get("shell") or "").lower()
    has_write_marker = any(
        marker in command
        for marker in (
            ">",
            "set-content",
            "add-content",
            "out-file",
            "new-item",
            "remove-item",
            "move-item",
            "copy-item",
            "apply_patch",
            "git apply",
            "tee ",
            "touch ",
            "mkdir ",
            "rm ",
            "mv ",
            "cp ",
        )
    )
    return has_write_marker or bool(_SHELL_MUTATION_COMMAND_RE.search(command))


def _code_tool_action(name: str, args: dict[str, Any]) -> str:
    canonical = _canonical_code_tool_name(name)
    if canonical in _CODE_MUTATION_TOOLS:
        return "mutation"
    if canonical in _CODE_INSPECTION_TOOLS:
        return "inspection"
    if canonical in _CODE_SHELL_TOOLS:
        return "mutation" if _shell_command_is_mutation(args) else "inspection"
    return "other"


def _tool_result_with_recovery(tool_name: str, result_text: str) -> str:
    """Add one concrete recovery instruction for a missing requested file."""
    if tool_name.lower() != "fs.read_file" or "file not found" not in result_text.lower():
        return result_text
    return (
        f"{result_text}\n\nRecovery: this file does not exist. Do not read it again; "
        "create it with fs.write_file when the requested task requires that file."
    )


def _failed_tool_signature(tool_name: str, args: dict[str, Any], result_text: str) -> str:
    """Identify one exact failing call without conflating a tool's other uses."""
    args_signature = json.dumps(args, sort_keys=True, separators=(",", ":"))
    error_signature = " ".join(result_text.lower().split())[:500]
    return f"{tool_name}:{args_signature}:{error_signature}"


def _record_failed_tool(counts: dict[str, int], tool_name: str, args: dict[str, Any], result_text: str) -> int:
    """Count an exact failure across intervening successful inspection calls."""
    signature = _failed_tool_signature(tool_name, args, result_text)
    counts[signature] = counts.get(signature, 0) + 1
    return counts[signature]
