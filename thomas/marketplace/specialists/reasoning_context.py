"""Read-only repository context and honest hand-off receipts for chat reasoning."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[3]
_READ_TOOL_NAMES = ("fs.read_file", "fs.list_dir", "fs.search", "web.search", "web.fetch")
_PREMATURE_HANDOFF_COMPLETION_RE = re.compile(
    r"\b(?:done|finished|completed|built|created|made|delivered|ready)\b"
    r"|\bi(?:'ve| have)\s+(?:got|built|created|made|finished|completed)\b",
    re.IGNORECASE,
)


def honest_handoff_confirmation(response: str) -> str:
    """Return a start receipt without claiming that delegated output exists."""

    text = str(response or "").strip()
    if text and not _PREMATURE_HANDOFF_COMPLETION_RE.search(text):
        return text
    # Thomas-first voice: the user should feel THOMAS is handling it, not that
    # they got routed to a separate "task manager." (Calvin, 2026-07-20.)
    return "On it — I'm getting this done now and I'll share the result the moment it's ready."


def repo_self_context() -> str:
    """Describe Thomas's identity, repository, and intentionally read-only tools."""

    return (
        "WHERE YOU ARE — repo & self awareness (you know this for real):\n"
        f"- You ARE this software. Your own source code lives in the repository at "
        f"{_REPO_ROOT}, and the project is named 'Thomas'. If asked who you are or what "
        "you're part of: you're Thomas, an AI-first workspace platform, and this repo is "
        "your own codebase — say so plainly, don't call yourself a generic 'AI assistant'.\n"
        "- You can READ files to ground your answers — call fs.read_file (a path), "
        "fs.list_dir (a folder), or fs.search (find text). Read the real thing (e.g. "
        "IDENTITY.md, SOUL.md, README.md, AGENTS.md, or any source file) instead of "
        "guessing. Reading is your superpower.\n"
        "- You can research current information directly with web.search and web.fetch. "
        "Cite source URLs in your answer. Use these tools in the current chat turn; do not "
        "hand ordinary web research to a background task.\n"
        "- You CANNOT write, edit, delete, or run commands — reading is your only "
        "filesystem power, by design. Anything that changes files is the task manager's "
        "job (hand it off). So, honestly: 'I can read this, but I can't change it.'\n\n"
    )


def read_tool_specs(registry: Any) -> list[dict]:
    """Build model function specs for registered read-only grounding tools."""

    specs: list[dict] = []
    if not (registry and hasattr(registry, "get")):
        return specs
    for name in _READ_TOOL_NAMES:
        try:
            tool = registry.get(name)
        except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
            tool = None
        if tool is None:
            continue
        specs.append(
            {
                "type": "function",
                "function": {
                    "name": str(getattr(tool, "name", name)),
                    "description": str(getattr(tool, "description", "") or "")[:1024],
                    "parameters": getattr(tool, "parameters", None) or {"type": "object", "properties": {}},
                },
            }
        )
    return specs
