"""Evidence extraction for the task checklist gate (recovered June 2026 work).

Only tool events are inspected - never text deltas - so a reply that merely
*claims* to have read a file contributes nothing. The worker declares its own
task type on its first line; this reads that label, it is not a classifier.
"""

from __future__ import annotations

import re
from typing import Any

from thomas.core import task_checklist

# Commands that read/inspect a file. Tool calls surface as display strings
# ("cat thomas/core/x.py", "sed -n 1,40p thomas/agent/dispatch.py", "read_file").
_READ_COMMAND_RE = re.compile(
    r"\b(?:cat|less|more|head|tail|sed|awk|grep|rg|nl|view|open|bat|type|"
    r"get-content|select-string|read|read_file|readfile|read_text)\b",
    re.I,
)
_TASK_TYPE_LABEL_RE = re.compile(r"TASK_TYPE\s*[:=]\s*([A-Za-z_]+)", re.I)

TASK_TYPE_INSTRUCTION = (
    " Begin your very first line with `TASK_TYPE: <type>` where <type> is exactly one of "
    "review_explain, code_change, research, plan - your own classification of this task. "
    "If the task makes any claim about how the system works it is review_explain, and you must "
    "read the relevant source files and cite concrete file:line references before finishing."
)


def extract_read_paths(event: dict[str, Any]) -> list[str]:
    """Real source-file READ paths from one ``tool_start`` event, else ``[]``."""

    if str(event.get("type") or "") != "tool_start":
        return []
    name = str(event.get("name") or "").strip()
    if not name:
        return []
    if name.lower().startswith("edit:"):  # engaging a file to edit it implies it was read
        candidate = name[len("edit:") :].strip().replace("\\", "/")
        return [candidate] if task_checklist.is_source_path(candidate) else []
    if not _READ_COMMAND_RE.search(name):
        return []
    found: list[str] = []
    for token in re.split(r"\s+", name):
        cleaned = token.strip().strip("\"'`(),;").replace("\\", "/")
        if task_checklist.is_source_path(cleaned):
            found.append(cleaned)
    return found


def extract_task_type_label(text: str) -> str:
    """The task type the worker declared, or '' if none seen yet."""

    match = _TASK_TYPE_LABEL_RE.search(str(text or ""))
    return match.group(1).strip().lower() if match else ""
