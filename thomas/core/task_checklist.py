"""Per-task-type completion checklists — Praxis task playbooks.

A task's TYPE is picked by the MODEL (not keyword matching), and the type selects
a small checklist of **machine-checkable** items that must be satisfied before the
task may complete. This module is pure data + pure evaluation: it takes *evidence*
(which files were actually read, the final output text) as plain data and never
inspects live events itself — so it is safe for ``thomas/core`` (no agent/server
imports) and unit-testable with no mocks. Each caller adapts its own event stream
(codex-bridge dicts, native ``AgentEvent``s, …) into ``read_paths`` and passes it
in.

The headline rule: an "evidence_read" item is satisfied ONLY by a real observed
read of a source file — never by words in the reply.

Flag-gated by ``THOMAS_TASK_CHECKLISTS`` (off by default → today's behaviour).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable, Sequence


class TaskType(str, Enum):
    """The small, fixed set of task types the model labels a task with."""

    REVIEW_EXPLAIN = "review_explain"  # any claim about how the system works
    CODE_CHANGE = "code_change"
    RESEARCH = "research"
    PLAN = "plan"

    @classmethod
    def coerce(cls, value: Any, *, default: str = "review_explain") -> TaskType:
        """Map any label to a TaskType. Fail-closed: an unknown/blank label
        becomes the *strictest* type (review_explain, which demands evidence), so
        a missing or garbled model label never weakens the gate."""
        raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        try:
            return cls(raw)
        except ValueError:
            return cls(default)


# Check kinds. evidence_read is verified from REAL read events; citation/output
# are verified against the produced deliverable.
KIND_EVIDENCE_READ = "evidence_read"
KIND_CITATION = "citation"
KIND_OUTPUT = "output"

_FLAG_ENV = "THOMAS_TASK_CHECKLISTS"


def checklists_enabled() -> bool:
    """True unless the checklist gate is switched off (``THOMAS_TASK_CHECKLISTS=0``); on by default."""
    return str(os.getenv(_FLAG_ENV, "")).strip().lower() not in {"0", "false", "off", "no"}


@dataclass
class ChecklistItem:
    item_id: str
    kind: str
    description: str
    satisfied: bool = False
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "kind": self.kind,
            "description": self.description,
            "satisfied": bool(self.satisfied),
            "detail": self.detail,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChecklistItem:
        return cls(
            item_id=str(data.get("item_id") or ""),
            kind=str(data.get("kind") or ""),
            description=str(data.get("description") or ""),
            satisfied=bool(data.get("satisfied", False)),
            detail=str(data.get("detail") or ""),
        )


def _template(task_type: TaskType) -> list[ChecklistItem]:
    """The per-type checklist. review_explain is the first shipped playbook;
    the others attach an (empty) checklist and stay pass-through until their own
    playbooks ship — so turning the flag on never blocks a type we haven't
    designed a contract for yet."""
    if task_type == TaskType.REVIEW_EXPLAIN:
        return [
            ChecklistItem(
                "read_source",
                KIND_EVIDENCE_READ,
                "Read at least one relevant source file before explaining how the system works.",
            ),
            ChecklistItem(
                "cite_file_line",
                KIND_CITATION,
                "Cite at least one concrete file:line in the explanation.",
            ),
        ]
    return []  # code_change / research / plan: pass-through for now


def build_checklist(task_type: Any) -> list[ChecklistItem]:
    """A fresh checklist for a task type (all items start unsatisfied)."""
    return _template(TaskType.coerce(task_type))


# ── evidence evaluation (pure; caller supplies the evidence) ─────────

# A file:line reference like ``thomas/core/x.py:42`` or ``scripts\\a.py : 7``.
_FILE_LINE_RE = re.compile(
    r"[\w./\\-]+\.(?:py|ts|tsx|js|jsx|md|toml|json|ya?ml|go|rs|java|sh|css|html)\s*:\s*\d+",
    re.IGNORECASE,
)
_SOURCE_EXT = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".go",
    ".rs",
    ".java",
    ".sh",
    ".toml",
    ".yaml",
    ".yml",
    ".json",
    ".css",
    ".html",
    ".md",
)


def _is_source_path(path: str) -> bool:
    p = str(path or "").strip().lower().replace("\\", "/")
    return bool(p) and p.endswith(_SOURCE_EXT)


def is_source_path(path: str) -> bool:
    """Public: True if ``path`` names a source file (by extension). Callers that
    translate their own event stream into ``read_paths`` use this so the single
    definition of "source file" stays in this module."""
    return _is_source_path(path)


def has_file_line_citation(text: str) -> bool:
    """True if the text contains at least one ``path.ext:line`` citation."""
    return bool(_FILE_LINE_RE.search(str(text or "")))


def evaluate_checklist(
    items: Sequence[ChecklistItem],
    *,
    read_paths: Iterable[str] | None = None,
    output_text: str = "",
    scope: Sequence[str] = (),
) -> list[ChecklistItem]:
    """Return a copy of ``items`` with each item's ``satisfied`` recomputed from
    the supplied evidence. ``read_paths`` are the files the run *actually read*
    (extracted by the caller from real tool events). ``output_text`` is the final
    deliverable. Never inspects words-as-proof for evidence_read items."""
    reads = {str(p).strip().replace("\\", "/") for p in (read_paths or []) if str(p).strip()}
    source_reads = {p for p in reads if _is_source_path(p)}
    out = str(output_text or "")

    updated: list[ChecklistItem] = []
    for it in items:
        satisfied, detail = bool(it.satisfied), it.detail
        if it.kind == KIND_EVIDENCE_READ:
            satisfied = bool(source_reads)
            detail = (
                "read source: " + ", ".join(sorted(source_reads)[:3])
                if satisfied
                else "no source-file read observed in tool events"
            )
        elif it.kind == KIND_CITATION:
            satisfied = has_file_line_citation(out)
            detail = "found file:line citation" if satisfied else "no file:line citation in the output"
        elif it.kind == KIND_OUTPUT:
            satisfied = bool(out.strip())
            detail = "output present" if satisfied else "no output produced"
        updated.append(ChecklistItem(it.item_id, it.kind, it.description, satisfied, detail))
    return updated


def checklist_satisfied(items: Sequence[ChecklistItem]) -> bool:
    """True if every item is satisfied (an empty checklist is trivially satisfied)."""
    return all(bool(it.satisfied) for it in (items or []))


def unmet_items(items: Sequence[ChecklistItem]) -> list[ChecklistItem]:
    return [it for it in (items or []) if not it.satisfied]


def checklist_to_dicts(items: Sequence[ChecklistItem]) -> list[dict[str, Any]]:
    return [it.to_dict() for it in (items or [])]


def checklist_from_dicts(rows: Sequence[dict[str, Any]] | None) -> list[ChecklistItem]:
    return [ChecklistItem.from_dict(r) for r in (rows or []) if isinstance(r, dict)]


__all__ = [
    "TaskType",
    "ChecklistItem",
    "KIND_EVIDENCE_READ",
    "KIND_CITATION",
    "KIND_OUTPUT",
    "checklists_enabled",
    "build_checklist",
    "evaluate_checklist",
    "checklist_satisfied",
    "unmet_items",
    "has_file_line_citation",
    "is_source_path",
    "checklist_to_dicts",
    "checklist_from_dicts",
]
