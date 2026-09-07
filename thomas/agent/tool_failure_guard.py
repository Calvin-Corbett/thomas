"""Break a tool doom loop by disabling the repeated call, not by killing the run.

The loop used to abort the whole run the third time one identical tool call
failed the same way ("Tool loop stability issue"). On TB-4.0 run 3
(2026-09-04) that ended two 128+ iteration runs over ``git.status`` in a
non-git folder and ``eng.lint`` with no ``python`` on PATH: the model lost
everything it had built for a tool it did not need.

Frontier harnesses (LangChain LoopDetection, Claude Code) do the cheaper
thing: refuse the repeated call, tell the model why, and continue. This guard
does that. The abort survives only as a backstop, for a model that keeps
issuing a call it has already been told is disabled.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from thomas.agent.loop_tool_protocol import _record_failed_tool


def _call_signature(tool_name: str, args: dict[str, Any]) -> str:
    return f"{tool_name}:{json.dumps(args, sort_keys=True, separators=(',', ':'))}"


@dataclass
class ToolFailureGuard:
    """Count identical failures; disable the call at ``limit``; abort at ``hammer_limit``."""

    limit: int = 3
    hammer_limit: int = 3
    _counts: dict[str, int] = field(default_factory=dict)
    _disabled: dict[str, int] = field(default_factory=dict)
    _abort_reason: str = ""

    def record_failure(self, tool_name: str, args: dict[str, Any], result_text: str) -> str | None:
        """Record one failed call. Returns the note to show the model when the call gets disabled."""
        count = _record_failed_tool(self._counts, tool_name, args, result_text)
        if count < self.limit:
            return None
        signature = _call_signature(tool_name, args)
        if signature in self._disabled:
            return None
        self._disabled[signature] = 0
        return (
            f"This exact {tool_name} call has failed {count} times with the same result, so it is "
            "disabled for the rest of this run. Do not repeat it; change the arguments, use a "
            "different tool, or carry on without it."
        )

    def check_before_call(self, tool_name: str, args: dict[str, Any]) -> str | None:
        """Refusal text for a disabled call, or None when the call may run."""
        signature = _call_signature(tool_name, args)
        if signature not in self._disabled:
            return None
        self._disabled[signature] += 1
        if self._disabled[signature] >= self.hammer_limit and not self._abort_reason:
            self._abort_reason = (
                f"{tool_name} was disabled after repeated identical failures and was still "
                f"called {self._disabled[signature]} more times; stopping to prevent token waste."
            )
        return (
            f"{tool_name} with these exact arguments is disabled for this run: it already failed "
            f"{self.limit} times with the same result. Do not call it again with these arguments."
        )

    def should_abort(self) -> bool:
        return bool(self._abort_reason)

    def abort_reason(self) -> str:
        return self._abort_reason


__all__ = ["ToolFailureGuard"]
