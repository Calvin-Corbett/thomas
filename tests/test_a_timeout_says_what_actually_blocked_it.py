"""A watchdog timeout must carry the block that caused it, not just the clock.

Measured 2026-09-19 by driving the Thomas UI. A chat task card was blocked from
writing inside thomas/agent/ - correctly - and the run then hit the 135s stall
watchdog. What the person was told was:

    "The refactor stalled after 135 seconds and produced no completed changes.
     I can retry by splitting the work into smaller, targeted steps."

Every word true, and the advice impossible: scope was never the obstacle. The
runtime-protection block was known to the run and discarded, because the timeout
is reported from `_run_agent_worker_supervised`, which never reaches the finaliser
where `result_with_policy_remedy` composes remedies.

The fix is a refusal sink the supervisor hands to the worker, so the cause can
survive to the moment the person is told the run failed. This is pinned here
rather than in tests/test_chat_delegation.py, which holds the sibling supervisor
tests but is 1647 lines - past the 1200-line hard limit already.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from thomas.server import chat_delegation

RUNTIME_BLOCK = (
    "BLOCKED: 'thomas/agent/loop_execution_errors.py' is inside protected runtime "
    "directory 'thomas/agent/'. Agent-spawned tools cannot modify Thomas's own runtime code."
)

STALE_RECORD = {
    "execution_id": "exec-native",
    "conversation_id": "sess-native",
    "state": "executing",
    "summary": "split loop_execution.py",
    "progress_summary": "Provider-native worker is running.",
    "last_heartbeat_at": "2000-01-01T00:00:00+00:00",
    "bot_id": "nova",
}


class _BotStub:
    id = "nova"
    name = "Nova"

    def to_event_dict(self) -> dict[str, str]:
        return {"bot_id": self.id, "bot_name": self.name}


def _alive_then_stalled(seen_sink: dict[str, object] | None = None):
    """Heartbeats that are fresh while the worker runs, then stop.

    The watchdog fires on the FIRST poll if the record is already stale, so a
    permanently-stale fixture never lets the worker run at all - and then nothing
    could ever have recorded a refusal. That is not the sequence being fixed. The
    real one is: the worker starts, hits a block, and only then goes quiet.
    """
    calls = {"n": 0}

    def _get_execution(*_args, **_kwargs):
        calls["n"] += 1
        record = dict(STALE_RECORD)
        if calls["n"] <= 3 and not (seen_sink or {}).get("ready"):
            record["last_heartbeat_at"] = datetime.now(timezone.utc).isoformat()
        return record

    return _get_execution


def _timeout_summary(refusals: list[str], tmp_path: Path) -> str:
    """Drive the supervisor to its timeout branch and return the reported summary."""
    emitter = SimpleNamespace(failed=AsyncMock())
    state: dict[str, object] = {}

    async def _runner(_app, **kwargs):  # noqa: ANN001, ANN003
        sink = kwargs.get("policy_refusal_sink")
        for refusal in refusals:
            if sink is not None:
                sink.append(refusal)
        state["ready"] = True
        await asyncio.sleep(5)

    with (
        patch("thomas.server.chat_delegation._WORKER_FIRST_EVENT_TIMEOUT_S", 0.05),
        patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", _alive_then_stalled(state)),
        patch("thomas.server.chat_delegation.task_bot_runtime.fail_execution") as fail_execution,
    ):
        asyncio.run(
            chat_delegation._run_agent_worker_supervised(
                _runner,
                {},
                execution_id="exec-native",
                specialist_id="coding",
                bot=_BotStub(),
                emitter=emitter,
                repo_root=tmp_path,
                worker_kwargs={},
            )
        )

    assert fail_execution.called, "the watchdog must terminalize the run"
    return str(fail_execution.call_args.kwargs["summary"])


def test_the_timeout_message_names_the_block_that_caused_it(tmp_path: Path) -> None:
    summary = _timeout_summary([RUNTIME_BLOCK], tmp_path)

    assert "Redesign" in summary, "the person must be told the route that works"
    assert "135" in summary or "within" in summary, "the timeout itself is still reported"


def test_a_timeout_with_no_refusal_is_left_exactly_as_it_was(tmp_path: Path) -> None:
    """No refusal, no invented cause. A plain stall stays a plain stall."""
    summary = _timeout_summary([], tmp_path)

    assert "Redesign" not in summary
    assert "produced no" in summary


def test_the_worker_is_handed_a_sink_at_all(tmp_path: Path) -> None:
    """The seam itself: without this kwarg the cause can never reach the watchdog."""
    seen: dict[str, object] = {}

    async def _runner(_app, **kwargs):  # noqa: ANN001, ANN003
        seen["sink"] = kwargs.get("policy_refusal_sink")
        seen["ready"] = True
        await asyncio.sleep(5)

    emitter = SimpleNamespace(failed=AsyncMock())
    with (
        patch("thomas.server.chat_delegation._WORKER_FIRST_EVENT_TIMEOUT_S", 0.05),
        patch("thomas.server.chat_delegation.task_bot_runtime.get_execution", _alive_then_stalled(seen)),
        patch("thomas.server.chat_delegation.task_bot_runtime.fail_execution"),
    ):
        asyncio.run(
            chat_delegation._run_agent_worker_supervised(
                _runner,
                {},
                execution_id="exec-native",
                specialist_id="coding",
                bot=_BotStub(),
                emitter=emitter,
                repo_root=tmp_path,
                worker_kwargs={},
            )
        )

    assert isinstance(seen.get("sink"), list), "the supervisor must pass a mutable sink to the worker"
