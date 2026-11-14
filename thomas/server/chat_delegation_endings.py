"""How a delegated worker and its watchdog end an execution: the first ending recorded stays, and the chat hears it.

Both can end the same execution. The worker completes, fails or sees your Stop; its watchdog times it out or records
your Stop. Each used to write its own ending over the other's and then announce its own, so you could be told "timed
out" for a task that had completed. Now every ending they write passes ``keep_first_terminal=True``
(``thomas.core.task_bot_first_ending``): the first one recorded stays, and a later one is only noted on the record.
The writer whose ending was refused announces the ending that was stored, in that ending's own words, and the emitter
passes on one ending per execution (``_DelegationEmitter._deliver_once``), so the chat hears it once.
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Any

from thomas.core import task_bot_runtime
from thomas.core.task_bot_first_ending import ending_was_refused
from thomas.server.chat_delegation_session import _normalize_record
from thomas.server.issue_ledger import record_issue

log = logging.getLogger(__name__)

_TERMINAL = frozenset(task_bot_runtime.TERMINAL_STATES)
# What an announcement may raise that a watchdog logs and moves past, as it did before this module.
_ANNOUNCE_ERRORS = (RuntimeError, OSError, ValueError, TypeError)


class Endings:
    """One execution's endings, as its worker or its watchdog writes and announces them."""

    def __init__(
        self, emitter: Any, execution_id: str, repo_root: str | Path | None, *, specialist_id: str, bot: Any
    ) -> None:
        self.emitter = emitter
        self.execution_id = execution_id
        self.repo_root = repo_root
        self.specialist_id = specialist_id
        self.bot = bot

    async def announce(self, ending: Any, text: str, *, completed: bool = False, quiet: bool = False) -> None:
        """Tell the chat how the execution ended. *completed* and *text* are this writer's own ending, used when it
        was the one recorded; when *ending* (what the write returned) says it was refused, the chat hears the stored
        ending and its words instead. *quiet*: a failed announcement is logged, not raised (the watchdog's way)."""
        record = _normalize_record(task_bot_runtime.get_execution(self.execution_id, self.repo_root))
        if ending_was_refused(ending):
            completed = str(record.get("state") or "") == "completed"
            text = str(record.get("last_progress") or record.get("progress_summary") or "")
        announce = self.emitter.completed if completed else self.emitter.failed
        try:
            await announce(record, specialist_id=self.specialist_id, bot=self.bot, text=text)
        except _ANNOUNCE_ERRORS:
            if not quiet:
                raise
            log.debug("delegation ending announcement failed for %s", self.execution_id, exc_info=True)

    async def fail(
        self, summary: str, *, blocker: str, text: str | None = None, quiet: bool = False, **fields: Any
    ) -> None:
        """Record a failure, unless the execution has already ended, and announce whichever ending stands."""
        ending = task_bot_runtime.fail_execution(
            self.execution_id,
            actor=self.bot.name,
            summary=summary,
            blocker=blocker,
            repo_root=self.repo_root,
            keep_first_terminal=True,
            **fields,
        )
        self._keep_salvage(ending, fields.get("salvaged_artifacts"))
        await self.announce(ending, summary if text is None else text, quiet=quiet)

    async def cancel(self, summary: str, *, text: str | None = None, quiet: bool = False, **fields: Any) -> None:
        """Record your Stop, unless the execution has already ended, and announce whichever ending stands."""
        ending = task_bot_runtime.cancel_execution(
            self.execution_id,
            actor=self.bot.name,
            summary=summary,
            repo_root=self.repo_root,
            keep_first_terminal=True,
            **fields,
        )
        self._keep_salvage(ending, fields.get("salvaged_artifacts"))
        await self.announce(ending, summary if text is None else text, quiet=quiet)

    def _keep_salvage(self, ending: Any, salvaged: list[str] | None) -> None:
        """A refused failure or Stop still leaves the files it salvaged on a record that did not complete: the work
        is on disk either way, and the stored ending may have been written without them (the stale sweep, say)."""
        if not salvaged or not ending_was_refused(ending):
            return
        with task_bot_runtime._record_lock(self.execution_id, self.repo_root):
            current = task_bot_runtime.get_execution(self.execution_id, self.repo_root) or {}
            kept = [str(item) for item in current.get("salvaged_artifacts") or []]
            merged = kept + [str(item) for item in salvaged if str(item) not in kept]
            if str(current.get("state") or "") != "completed" and merged != kept:
                task_bot_runtime.update_execution(
                    self.execution_id,
                    salvaged_artifacts=merged,
                    actor=self.bot.name,
                    repo_root=self.repo_root,
                    force=True,
                )

    async def crashed(self, crash: BaseException) -> None:
        """End an execution whose worker thread died with an exception and recorded no ending of its own.

        Before, the watchdog re-raised the exception, nothing was recorded and nothing was said: the task showed
        "running" until the stale sweep failed it 15 minutes later. The ending names the exception's type and where
        it was raised, never its text, which can carry a provider's words or a secret; it is recorded for repair,
        and announced once like every other ending."""
        frames = traceback.extract_tb(crash.__traceback__)
        site = f" at {Path(frames[-1].filename).name}:{frames[-1].lineno}" if frames else ""
        reason = f"{type(crash).__name__}{site}"
        log.warning("provider-native worker thread crashed for %s: %s", self.execution_id, reason)
        record_issue(
            surface="chat-worker",
            kind="worker_crashed",
            message=f"worker thread crashed: {reason}"[:300],
            context={"execution_id": self.execution_id},
            repo_root=self.repo_root,
        )
        summary = f"Background execution failed: the worker stopped with {reason}."
        await self.fail(summary, blocker="provider_native_failed", quiet=True)


def attach_proof_unless_ended(
    execution_id: str, *, repo_root: str | Path | None, **proof: Any
) -> dict[str, Any] | None:
    """``task_bot_runtime.attach_proof``, unless the execution has already ended.

    A worker that finishes after its watchdog ended the execution must not write its proof and its summary over the
    stored ending: the record would then read "failed" beside the late worker's own result. Checked and written under
    the record's lock, so no ending can land in between. Returns None when nothing was written."""
    with task_bot_runtime._record_lock(execution_id, repo_root):
        current = task_bot_runtime.get_execution(execution_id, repo_root) or {}
        if str(current.get("state") or "").strip().lower() in _TERMINAL:
            return None
        return task_bot_runtime.attach_proof(execution_id, repo_root=repo_root, **proof)


__all__ = ["Endings", "attach_proof_unless_ended"]
