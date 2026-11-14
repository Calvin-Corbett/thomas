"""Repair feedback for stage-2 builders (after LIVE STAGE2-03, LIVE-PLAN-02-ADDENDUM-01 disclosure decision). No Thomas import.

LIVE STAGE2-03 feedback named only a case id, or a check name with its message cut off, so builders could not act on it. The
disclosure decision: repair feedback includes, for each failing visible check, its message (exception and location, as the
evaluation child reported it), and for each failing oracle case its arguments, the expected result and the observed result.
Hidden test SOURCE text is never shown: feedback is built only from the routing evidence (check ids, messages and oracle
arguments, expectations and observations), never from check files. Every item and the whole text are bounded in size.

After LIVE STAGE3-02 the feedback also ends with HOW TO RESUBMIT. In that run six of the seven repaired builders spent their whole
round-2 request budget editing their file and never resubmitted: a candidate is submitted only when the builder ENDS ITS TURN with
a plain reply and no tool calls (thomas/agent/loop_execution.py hands that moment to the pre-terminal integration hold), and
nothing in the feedback said so. The block is procedural only - it never names the defect, the rule or the fix - and it is
appended after the evidence is bounded, so truncation can never drop it.
"""

from __future__ import annotations

import json
from typing import Any

MAX_ITEM_CHARS = 1200
MAX_TEXT_CHARS = 8000
MAX_ITEMS = 10
RESUBMIT_HEADING = "How to resubmit (this is the only way your repaired module is checked again):"


def resubmit_lines(owned_path: str) -> list[str]:
    """Procedural only: what the builder must DO to have its fix evaluated. It never names the defect or the fix."""
    return [
        RESUBMIT_HEADING,
        f"- edit only {owned_path}, in the workspace you are already in;",
        "- then END YOUR TURN with a short plain-text reply and NO tool calls: that reply resubmits your module for the next "
        "combined check;",
        "- reading or writing files again does not resubmit it, and this round's request budget is limited, so resubmit as "
        "soon as the fix is in the file.",
    ]


def render_value(value: Any) -> str:
    """A readable Python-like rendering of a nowner_codec-encoded value."""
    if isinstance(value, dict):
        if "dc" in value:
            fields = ", ".join(f"{key}={render_value(item)}" for key, item in (value.get("fields") or {}).items())
            return f"{value['dc']}({fields})"
        if "list" in value:
            return "[" + ", ".join(render_value(item) for item in value["list"]) + "]"
        if "tuple" in value:
            items = [render_value(item) for item in value["tuple"]]
            return "(" + ", ".join(items) + ("," if len(items) == 1 else "") + ")"
        if "dict" in value:
            return "{" + ", ".join(f"{render_value(key)}: {render_value(item)}" for key, item in value["dict"]) + "}"
        if "decimal" in value:
            return f"Decimal({value['decimal']!r})"
        if "date" in value:
            return f"datetime.date.fromisoformat({value['date']!r})"
        return json.dumps(value, sort_keys=True)
    return repr(value)


def render_result(result: Any) -> str:
    if isinstance(result, dict) and "raises" in result:
        return f"raises {result['raises']}"
    if isinstance(result, dict) and "returns" in result:
        return f"returns {render_value(result['returns'])}"
    return render_value(result)


def _bounded(text: str, limit: int = MAX_ITEM_CHARS) -> str:
    return text if len(text) <= limit else text[: limit - 15] + " ...[truncated]"


def check_line(item: str) -> str:
    """'checks_x.py::check_y [error] TypeError: ... at x.py:19' -> '- checks_x.py::check_y (error): TypeError: ... at x.py:19'."""
    name, _, rest = str(item).partition(" [")
    status, _, message = rest.partition("] ")
    if not rest:
        return f"- {name}"
    return _bounded(f"- {name} ({status}): {message.strip() or '(no message)'}")


def case_lines(detail: dict[str, Any]) -> list[str]:
    args = ", ".join(render_value(argument) for argument in detail.get("args") or [])
    return [
        f"- {detail.get('case_id')} {detail.get('function')}",
        _bounded(f"  arguments: ({args})"),
        _bounded(f"  expected: {render_result(detail.get('expected'))}"),
        _bounded(f"  observed: {render_result(detail.get('observed'))}"),
    ]


def feedback_text(owned_path: str, evidence: dict[str, Any] | None) -> str:
    evidence = evidence or {}
    lines = [
        f"Your module {owned_path} fails the controller's checks with every peer module correct.",
        "Failing checks (message only; check source is not shown):",
    ]
    checks = list(evidence.get("isolation_failed_checks") or [])[:MAX_ITEMS]
    lines += [check_line(item) for item in checks] or ["- (none)"]
    lines.append("Behavioural cases not matched (arguments, expected and observed):")
    details = list(evidence.get("oracle_violation_details") or [])[:MAX_ITEMS]
    if details:
        for detail in details:
            lines += case_lines(detail)
    else:
        lines += [f"- {case_id}" for case_id in (evidence.get("oracle_violations") or [])[:MAX_ITEMS]] or ["- (none)"]
    instruction = "\n".join(resubmit_lines(owned_path))
    body = _bounded("\n".join(lines), max(0, MAX_TEXT_CHARS - len(instruction) - 2))
    return f"{body}\n\n{instruction}"


__all__ = [
    "MAX_ITEMS",
    "MAX_ITEM_CHARS",
    "MAX_TEXT_CHARS",
    "RESUBMIT_HEADING",
    "check_line",
    "feedback_text",
    "render_result",
    "render_value",
    "resubmit_lines",
]
