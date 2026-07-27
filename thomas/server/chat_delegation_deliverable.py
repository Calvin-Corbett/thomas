"""Evidence-backed deliverable helpers for delegated workers.

Natural-language meaning belongs to the frontier model.  This module only
reports structured tool outcomes and files observed on disk; it never infers
completion, file intent, side effects, or artifact requirements from prose.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from thomas.server.chat_delegation_deliverable_postprocess import (
    executability_warning,
    render_report_pdfs,
    runtime_executability_warning,
)
from thomas.server.chat_delegation_workspace import (
    files_changed_since as _files_changed_since,
)
from thomas.server.chat_delegation_workspace import (
    snapshot_workspace_files as _snapshot_workspace_files,
)
from thomas.server.chat_delegation_workspace import (
    workspace_mtimes as _workspace_mtimes,
)


def _cap(text: str, limit: int) -> str:
    value = str(text or "")
    return value if len(value) <= limit else value[: limit - 3] + "..."


def _worker_summary_line(result_text_parts: list[str] | None) -> str:
    """Return the last non-empty line without assigning semantic status."""

    raw = "".join(str(part) for part in (result_text_parts or []) if part is not None).strip()
    if not raw:
        return ""
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    return " ".join((lines[-1] if lines else raw).split())


_INTERNAL_META_LINE_RE = re.compile(r"^\s*(?:thinking\s*:|\[thinking\])", re.IGNORECASE)


def _worker_answer_text(result_text_parts: list[str] | None) -> str:
    """Preserve model-authored output while excluding explicit thought labels."""

    raw = "".join(str(part) for part in (result_text_parts or []) if part is not None).strip()
    return "\n".join(line for line in raw.splitlines() if not _INTERNAL_META_LINE_RE.match(line)).strip()


def _build_result_summary(
    result_text_parts: list[str],
    tools_used: list[str],
    created_files: list[str] | None = None,
    *,
    succeeded_tools: list[str] | None = None,
    failed_tools: list[str] | None = None,
    prompt: str = "",
) -> str:
    """Present actual files/tool receipts plus untouched model-authored text."""

    del prompt
    created = [str(path) for path in (created_files or []) if str(path).strip()]
    succeeded = [str(name) for name in (succeeded_tools or []) if str(name).strip()]
    failed = [str(name) for name in (failed_tools or []) if str(name).strip()]
    answer = _worker_answer_text(result_text_parts)

    if created:
        shown = created[:8]
        files_text = ", ".join(shown)
        if len(created) > len(shown):
            files_text += f" (+{len(created) - len(shown)} more)"
        base = f"Created {files_text}."
        return _cap(f"{base} {answer}" if answer else base, 64_000)
    if failed:
        base = f"Tool failures: {', '.join(failed[:5])}."
        return _cap(f"{base} {answer}" if answer else base, 64_000)
    if answer:
        return _cap(answer, 64_000)
    if succeeded:
        return f"Completed using: {', '.join(succeeded[:5])}."
    if tools_used:
        return f"Tool run ended without a terminal result: {', '.join(str(name) for name in tools_used[:5])}."
    return "The worker returned no output."


def quality_tier_clause(effort: str, autonomy_level: int = 4) -> str:
    """Build-quality instruction derived from an explicit structured effort tier."""

    from thomas.core.token_economy import normalize_token_economy_level

    del autonomy_level
    level = normalize_token_economy_level(effort)
    if level == "cheap":
        return (
            "BUILD QUALITY = QUICK. Produce only the requested deliverable as directly as possible. "
            "Do not add unrelated project scaffolding."
        )
    if level == "max":
        return (
            "BUILD QUALITY = THOROUGH. Produce a polished, robust deliverable. Supporting files are "
            "appropriate only when they materially improve the result."
        )
    return "BUILD QUALITY = STANDARD. Produce a complete, focused deliverable without unrelated tooling."


def _handoff_block(recent_messages: list[dict[str, Any]] | None, *, limit: int = 6) -> str:
    """Curate bounded transcript evidence for a model-authored worker brief."""

    messages = [message for message in (recent_messages or []) if isinstance(message, dict)]
    turns: list[str] = []
    for message in messages[-limit:]:
        role = str(message.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = " ".join(str(message.get("content") or "").split())
        if not content:
            continue
        who = "User" if role == "user" else "Thomas"
        turns.append(f"{who}: {content[:397] + '...' if len(content) > 400 else content}")
    if not turns:
        return ""
    return (
        "Recent conversation evidence for resolving references only:\n"
        "--- recent conversation ---\n" + "\n".join(turns) + "\n--- end conversation ---"
    )


class _WorkerRetry(RuntimeError):
    """A worker attempt may be retried."""


class _WorkerFatal(RuntimeError):
    """A deterministic worker failure must not be retried."""


def _resolve_created(
    work_dir: Path | None,
    attempt_baseline: dict[str, tuple[int, int]],
    result_text_parts: list[str],
    tools_used: list[str],
) -> list[str]:
    """Return only files actually changed during this attempt."""

    del result_text_parts, tools_used
    return _files_changed_since(work_dir, attempt_baseline)


def _artifacts_from_created(created_files: list[str] | None) -> list[dict[str, Any]]:
    """Build structured UI artifact records from observed files."""

    artifacts: list[dict[str, Any]] = []
    for raw in created_files or []:
        relative = str(raw or "").strip()
        if not relative:
            continue
        extension = Path(relative).suffix.lstrip(".").lower()
        artifacts.append(
            {
                "path": relative,
                "name": Path(relative).name,
                "type": extension or "file",
                "actions": ["open", "download"],
            }
        )
    return artifacts


__all__ = [
    "_WorkerFatal",
    "_WorkerRetry",
    "_artifacts_from_created",
    "_build_result_summary",
    "_files_changed_since",
    "_handoff_block",
    "_resolve_created",
    "_snapshot_workspace_files",
    "_worker_summary_line",
    "_workspace_mtimes",
    "executability_warning",
    "quality_tier_clause",
    "render_report_pdfs",
    "runtime_executability_warning",
]
