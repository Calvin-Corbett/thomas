"""Background task manager for the Thomas REPL.

Allows running agent prompts asynchronously while the user continues
interacting with the REPL.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class BackgroundTask:
    """Represents a single background agent run."""

    task_id: str
    prompt: str
    status: str = "pending"  # pending | running | done | error | cancelled
    result_text: str = ""
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    _future: asyncio.Task[Any] | None = field(default=None, repr=False)
    _surfaced: bool = False


class BackgroundTaskManager:
    """Manages background agent tasks for the REPL."""

    def __init__(self, repl: Any) -> None:
        self._repl = repl
        self._tasks: dict[str, BackgroundTask] = {}

    async def submit(self, prompt: str) -> str:
        """Submit a new background task. Returns the task ID."""
        task_id = f"bg-{uuid.uuid4().hex[:8]}"
        bt = BackgroundTask(task_id=task_id, prompt=prompt, started_at=time.time())
        self._tasks[task_id] = bt

        async def _run() -> None:
            bt.status = "running"
            try:
                # Capture the agent's final output text
                result_parts: list[str] = []
                from thomas.agent.loop import AgentLoop
                from thomas.core.events import EventType
                from thomas.core.token_economy import normalize_token_economy_level

                session_id = str(getattr(self._repl, "_repl_session_id", "") or "repl").strip() or "repl"
                agent = AgentLoop(
                    config=self._repl.config,
                    llm=self._repl._get_llm(),
                    tools=self._repl.tools,
                    conversation=list(self._repl._conversation),
                    memory=self._repl._memory,
                    thread_id=f"{session_id}-{task_id}",
                    autonomy_level=self._repl._autonomy_level,
                    session_id=session_id,
                    run_id=task_id,
                )
                token_economy = normalize_token_economy_level("optimal")
                async for event in agent.run(prompt, token_economy=token_economy):
                    if event.type == EventType.TEXT_DELTA:
                        text = str(event.data.get("text") or "")
                        if text:
                            result_parts.append(text)
                    elif event.type == EventType.AGENT_DONE:
                        final = str(event.data.get("text") or "").strip()
                        if final:
                            result_parts.clear()
                            result_parts.append(final)
                    elif event.type == EventType.AGENT_ERROR:
                        bt.error = str(event.data.get("error", "Unknown error"))
                bt.result_text = "".join(result_parts).strip()
                bt.status = "done" if not bt.error else "error"
            except asyncio.CancelledError:
                bt.status = "cancelled"
            except Exception as exc:
                bt.error = str(exc)
                bt.status = "error"
                log.debug("Background task %s failed: %s", task_id, exc)
            finally:
                bt.finished_at = time.time()

        bt._future = asyncio.create_task(_run())
        return task_id

    def get_task(self, task_id: str) -> BackgroundTask | None:
        """Look up a task by ID."""
        return self._tasks.get(task_id)

    def list_tasks(self) -> list[BackgroundTask]:
        """Return all tasks sorted by start time (newest first)."""
        return sorted(self._tasks.values(), key=lambda t: t.started_at, reverse=True)

    def surface_result(self, task_id: str) -> str:
        """Return a summary string for injecting into the conversation.

        Marks the task as surfaced so it is only injected once.
        """
        bt = self._tasks.get(task_id)
        if not bt or bt._surfaced:
            return ""
        if bt.status not in ("done", "error"):
            return ""
        bt._surfaced = True
        if bt.error:
            return f"[Background task {task_id} failed: {bt.error}]"
        snippet = bt.result_text[:2000] if bt.result_text else "(no output)"
        return f"[Background task {task_id} completed]\n\nPrompt: {bt.prompt}\n\nResult:\n{snippet}"

    async def cancel_all(self) -> None:
        """Cancel all running background tasks."""
        for bt in self._tasks.values():
            if bt._future and not bt._future.done():
                bt._future.cancel()
                bt.status = "cancelled"
                bt.finished_at = time.time()
