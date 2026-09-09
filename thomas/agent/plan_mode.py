"""Plan mode support for the Thomas agent loop.

Provides the :func:`plan_to_markdown` compatibility helper used by CLI and
other callers that still import the function from ``thomas.agent``.
"""

from __future__ import annotations


def plan_to_markdown(plan: object) -> str:
    """Convert a plan-like object to readable Markdown.

    Keep this implementation local to the ``agent`` module so it does not create a
    cross-layer import to ``thomas.cli``.
    """

    task_description = getattr(plan, "task_description", "")
    status = str(getattr(plan, "status", "unknown")) if getattr(plan, "status", None) is not None else "unknown"
    plan_id = getattr(plan, "plan_id", "")
    steps = getattr(plan, "steps", []) or []

    title = task_description if task_description else "Plan"
    lines = [f"# Plan: {title}", ""]
    status_line = f"**Status:** {status}"
    if plan_id:
        status_line += f"  |  **ID:** `{plan_id}`"
    lines.append(status_line)
    lines.append("")

    if not steps:
        lines.append("*(no steps)*")
    else:
        for index, step in enumerate(steps, 1):
            step_status = str(getattr(step, "status", "")).lower()
            status_icon = {
                "pending": "[ ]",
                "running": "[~]",
                "done": "[x]",
                "skipped": "[-]",
                "error": "[!]",
            }.get(step_status, "[ ]")
            description = str(getattr(step, "description", str(step)))
            lines.append(f"{index}. {status_icon} {description}")
            result = str(getattr(step, "result", ""))
            if result:
                lines.append(f"   > {result[:200]}")

    return "\n".join(lines)
