"""``task.spawn``: the Build agent delegating a piece of work to another agent.

The spec says the Build agent is itself a task manager -- solo for small work,
spawning agents for bigger work -- and that every spawned agent must appear in
the Build activity panel. The worker had no spawn capability at all, so neither
half existed.

The panel renders the Build session's transcript, so making a child "appear" is
literal: its steps are written into that same transcript as forge events, with
the child's name on them. A lead running three helpers produces one readable
story rather than three invisible ones.

Bounded on purpose:

* **A child cannot spawn.** ``run_child`` builds the child's tool set without
  this tool, so the recursion is one level by construction rather than by a
  depth counter someone has to remember to check.
* **A child that fails is a result, not a casualty.** The error is recorded and
  returned to the lead, which decides what to do. Rule 0: a helper falling over
  must not end the run.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

from thomas.server.chat_delegation_build_transcript import forge_line, record_line
from thomas.server.chat_delegation_emitter import beat_worker
from thomas.tools.task_spawn import SpawnAgentTool as DelegationTool

# The child's own event stream: (title, instructions) -> worker-style events.
ChildRunner = Callable[[str, str], AsyncIterator[dict[str, Any]]]


def _label(title: str, name: str) -> str:
    """Put the child's name on its step so the panel can tell agents apart."""
    return f"{title} > {name}" if name else title


class SpawnAgentTool(DelegationTool):
    """Server transcript adapter for the shared delegation lifecycle."""

    def __init__(self, *, execution_id: str, run_child: ChildRunner) -> None:
        self._execution_id = str(execution_id or "")

        async def child(_child_id: str, title: str, instructions: str):
            async for event in run_child(title, instructions):
                yield event

        super().__init__(run_child=child, record_event=self._record_child)

    def _record_child(self, title: str, event: dict[str, Any]) -> None:
        # A helper's step is the lead's sign of life. The lead emits nothing of its own
        # while it waits, and its watchdogs failed it as silent while the helper worked.
        beat_worker(self._execution_id)
        self._record(self._child_line(title, event))

    def _child_line(self, title: str, event: dict[str, Any]) -> str | None:
        """One child event as a forge line, carrying the child's name."""
        kind = str(event.get("type") or "")
        if kind in ("tool_start", "tool_output"):
            tagged = dict(event)
            tagged["name"] = _label(title, str(event.get("name") or ""))
            return forge_line(tagged)
        if kind == "text":
            return forge_line({"type": "text", "text": f"[{title}] {event.get('text') or ''}"})
        if kind == "error":
            error = event.get("error") or event.get("text") or "worker failed"
            return forge_line({"type": "error", "error": f"{title} failed: {error}"})
        return forge_line(event)

    def _record(self, line: str | None) -> None:
        if line:
            record_line(self._execution_id, line)


def register_spawn_tool(registry: Any, *, execution_id: str, run_child: ChildRunner) -> None:
    """Give one run the ability to delegate. Omitted for a child, by design."""
    registry.register(SpawnAgentTool(execution_id=execution_id, run_child=run_child))


__all__ = ["ChildRunner", "SpawnAgentTool", "register_spawn_tool"]
