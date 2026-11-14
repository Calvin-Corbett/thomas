"""Whether a run left a tool failure unresolved: the one sign that a run which changed no files did not finish.

Three places judge whether a run that changed nothing still answered (``dispatch_agent_loop``,
``dispatch_claude_cli`` and ``evolve_agent_run_status._confirmed_conversation_reply``), and they must agree. Each
disqualified a run for ANY failed tool call, so a run that confirmed finished work and hit one failed probe on the way
was filed as crashed: on 2026-09-27 four Thomas projects never handed in their finished changes because a search
found nothing, a probe exited 1, or ``check.run`` refused an option before every later check passed.

A failed look changes nothing and never counts. A failed file edit, or a failed call with no name (it could have been
one), stands until a later file edit succeeds. Any other failed call stands until a later write-capable call succeeds.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from thomas.agent.loop_tool_protocol import _CODE_MUTATION_TOOLS, is_inspection_tool

# The agent loop's file-editing tools, and the Claude CLI's own names for them.
FILE_EDIT_TOOLS = frozenset({*_CODE_MUTATION_TOOLS, "edit", "write", "multiedit", "notebookedit"})


class ToolFailures:
    """Feed it a run's events in order; ``unresolved`` says whether a failed call was never moved past."""

    def __init__(self, *, inspection: Callable[[str], bool] = is_inspection_tool) -> None:
        self.inspection = inspection
        self.saw_tool = False
        self.saw_named_tool = False
        self.saw_mutating_tool = False
        self.file_edit_failed = False
        self.other_failed = False
        self._call: dict[str, Any] = {}

    @property
    def unresolved(self) -> bool:
        return self.file_edit_failed or self.other_failed

    def observe(self, event: dict[str, Any]) -> None:
        kind = str(event.get("fc") or "")
        if kind not in {"tool", "tool_result"}:
            return
        self.saw_tool = True
        name = str(event.get("name") or "").strip()
        if name and name != "tool":
            self.saw_named_tool = True
        if kind == "tool":
            self._call = event
            if self._is_write(event):
                self.saw_mutating_tool = True
            return
        call, self._call = self._call, {}
        if event.get("waiting"):
            return  # tests still queued or running (check.run): no verdict, so neither a failure nor a success
        # Results carry their own name/access (agent loop) or inherit the call's (CLI).
        if not name or name == "tool":
            name = str(call.get("name") or "").strip()
        if name and name != "tool":
            self.saw_named_tool = True
        access = str(event.get("access") or call.get("access") or "").strip()
        file_edit = not name or name == "tool" or name.casefold() in FILE_EDIT_TOOLS
        # A fixed inspection name stays read-only even if a stale access stamp says write.
        if not file_edit and (self.inspection(name) or access == "read"):
            return
        self.saw_mutating_tool = True
        if event.get("is_error"):
            if file_edit:
                self.file_edit_failed = True
            else:
                self.other_failed = True
            return
        if file_edit:
            self.file_edit_failed = False
        self.other_failed = False

    def _is_write(self, event: dict[str, Any]) -> bool:
        access = str(event.get("access") or "").strip()
        return access == "write" or (access != "read" and not self.inspection(str(event.get("name") or "")))


__all__ = ["FILE_EDIT_TOOLS", "ToolFailures"]
