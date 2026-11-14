"""A delegated task keeps the first ending recorded for it, and the chat hears that ending once.

A worker and its watchdog can both end the same execution. Every ending used to be written with force=True and
announced by whoever wrote it, so the second replaced the first and the chat heard both: "timed out" for a task
that had completed, or "completed" for one the watchdog had already failed. These tests use real execution records
in a temporary project, the real supervisor and finaliser, and a real ``_DelegationEmitter`` whose chat stream and
notifier are recorded. The last test covers marking a reported completion on the record it was read from.
"""

from __future__ import annotations

import asyncio
import contextlib
import shutil
import threading
from pathlib import Path
from typing import Any

import pytest

from thomas.core import task_bot_runtime as rt
from thomas.marketplace.orchestrator import background_completions
from thomas.server import chat_delegation_runner as runner
from thomas.server.chat_delegation_emitter import _DelegationEmitter
from thomas.server.chat_delegation_session import _normalize_record, session_active_delegations

TIMED_OUT = "Background execution failed: provider-native worker produced no further progress within 135s."
STATES = {"completed": "completed", "timed out": "failed", "stopped": "cancelled"}


class _Bot:
    id = name = "nova"

    def to_event_dict(self) -> dict[str, str]:
        return {"bot_id": "nova"}


class _Chat:
    """A real emitter whose chat stream and notifications are recorded."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.notices: list[tuple[str, str]] = []
        self.emitter = _DelegationEmitter(self._emit, notifier=self._notify)

    async def _emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def _notify(self, event: str, record: dict[str, Any], *, text: str = "") -> None:
        self.notices.append((event, text))

    def endings(self) -> list[tuple[str, str]]:
        kinds = {"delegation_completed", "delegation_failed"}
        return [(e["type"], str(e.get("last_progress") or "")) for e in self.events if e["type"] in kinds]


def _executing(root: Path, session_id: str = "chat") -> str:
    eid = rt.create_execution(session_id=session_id, summary="Write out.txt", repo_root=root)["execution_id"]
    for state in ("classified", "queued", "claimed", "executing"):
        rt.update_execution(eid, state=state, claimed_owner="nova", actor="nova", repo_root=root)
    return eid


def _end(how: str, eid: str, root: Path, **flag: Any) -> dict[str, Any]:
    if how == "completed":
        return rt.complete_execution(
            eid, actor="nova", summary="Wrote out.txt.", verified_success=True, repo_root=root, **flag
        )
    if how == "timed out":
        return rt.fail_execution(
            eid, actor="nova", summary=TIMED_OUT, blocker="provider_native_timeout", repo_root=root, **flag
        )
    return rt.cancel_execution(eid, actor="nova", summary="Stopped by you.", repo_root=root, **flag)


@pytest.mark.parametrize(
    ("first", "later"),
    [("completed", "timed out"), ("timed out", "completed"), ("stopped", "completed"), ("timed out", "stopped")],
)
def test_a_later_ending_is_noted_and_the_first_one_stays(tmp_path: Path, first: str, later: str) -> None:
    eid = _executing(tmp_path)
    _end(first, eid, tmp_path)
    stored = rt.get_execution(eid, tmp_path)

    refused = _end(later, eid, tmp_path, keep_first_terminal=True)

    record = rt.get_execution(eid, tmp_path)
    assert refused["terminal_write_applied"] is False
    assert (record["state"], record["blocker"], record["progress_summary"]) == (
        stored["state"], stored["blocker"], stored["progress_summary"],
    )  # fmt: skip
    assert record["state"] == STATES[first]
    late = record["late_terminal_requests"]
    assert [entry["state"] for entry in late] == [STATES[later]], late
    assert "terminal_write_applied" not in record, "the marker is for the caller, never stored"


def test_callers_that_do_not_ask_keep_the_old_behaviour(tmp_path: Path) -> None:
    eid = _executing(tmp_path)
    _end("completed", eid, tmp_path, keep_first_terminal=True)
    _end("timed out", eid, tmp_path)
    assert rt.get_execution(eid, tmp_path)["state"] == "failed"


def test_a_watchdog_that_times_out_a_worker_which_completed_meanwhile_announces_nothing_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The watchdog decides the worker is silent; while it stops the worker, the worker records its completion and
    announces it. The watchdog's timeout must not replace that completion, and the chat must not hear "timed out"."""
    eid = _executing(tmp_path)
    monkeypatch.setattr(runner, "_WORKER_FIRST_EVENT_TIMEOUT_S", 0.2)
    monkeypatch.setattr(runner, "_WORKER_IDLE_EVENT_TIMEOUT_S", 0.2)
    monkeypatch.setattr(runner, "_WORKER_WATCHDOG_GRACE_S", 0.0)
    chat = _Chat()

    async def worker(_app: Any, *, emitter: Any, **_kwargs: Any) -> None:
        try:
            await asyncio.sleep(60)
        except asyncio.CancelledError:  # its completion was already under way when the stop came
            done = rt.complete_execution(
                eid, actor="nova", summary="Wrote out.txt.", verified_success=True, repo_root=tmp_path
            )
            await emitter.completed(
                _normalize_record(done), specialist_id="reasoning", bot=_Bot(), text="Wrote out.txt."
            )

    async def main() -> None:
        await asyncio.wait_for(
            runner._run_agent_worker_supervised(
                worker, None, execution_id=eid, specialist_id="reasoning", bot=_Bot(), emitter=chat.emitter,
                repo_root=tmp_path, worker_kwargs={},
            ),
            timeout=30,
        )  # fmt: skip

    asyncio.run(main())
    record = rt.get_execution(eid, tmp_path)
    assert record["state"] == "completed", record["progress_summary"]
    assert [entry["blocker"] for entry in record.get("late_terminal_requests") or []] == ["provider_native_timeout"]
    assert chat.endings() == [("delegation_completed", "Wrote out.txt.")]
    assert [event for event, _text in chat.notices] == ["completed"]


@pytest.mark.parametrize("watchdog_was_heard", [True, False])
def test_a_worker_that_finishes_after_its_watchdog_timed_it_out_keeps_the_timeout(
    tmp_path: Path, watchdog_was_heard: bool
) -> None:
    """The watchdog failed the execution; then the worker's own finish arrives. The record keeps the timeout and its
    words, the late worker writes no proof over it, and the chat hears the timeout once. When the watchdog's own
    report never reached the chat (its delivery failed), the late worker's report carries the stored timeout, never
    its own completion."""
    eid = _executing(tmp_path)
    work = tmp_path / "workspace"
    work.mkdir()
    (work / "out.txt").write_text("done\n", encoding="utf-8")
    chat = _Chat()

    async def main() -> None:
        _end("timed out", eid, tmp_path)  # the watchdog, first
        if watchdog_was_heard:
            timed_out = _normalize_record(rt.get_execution(eid, tmp_path))
            await chat.emitter.failed(timed_out, specialist_id="reasoning", bot=_Bot(), text=TIMED_OUT)
        await runner._finalize_worker_completion(
            chat.emitter, eid, work, "Write out.txt", {}, ["Wrote out.txt."], ["fs.write_file"], ["fs.write_file"],
            [], {}, _Bot(), "reasoning", tmp_path,
        )  # fmt: skip

    asyncio.run(main())
    record = rt.get_execution(eid, tmp_path)
    assert (record["state"], record["blocker"], record["progress_summary"]) == (
        "failed", "provider_native_timeout", TIMED_OUT,
    )  # fmt: skip
    assert not (record.get("proof") or {}).get("artifacts"), "the late worker wrote its proof over the stored ending"
    assert [entry["state"] for entry in record.get("late_terminal_requests") or []] == ["completed"]
    assert chat.endings() == [("delegation_failed", TIMED_OUT)]
    assert [event for event, _text in chat.notices] == ["failed"]


def test_one_ending_reaches_the_chat_and_a_failed_delivery_is_delivered_by_the_next_report() -> None:
    chat = _Chat()
    record = {"execution_id": "exec-one-ending", "session_id": "chat"}
    broken = {"once": True}
    real_emit = chat._emit

    async def emit(event: dict[str, Any]) -> None:
        if broken.pop("once", False):
            raise RuntimeError("the chat stream was closed")
        await real_emit(event)

    chat.emitter._emit_event = emit
    gate = asyncio.Event()

    async def slow(event: dict[str, Any]) -> None:
        await gate.wait()
        await real_emit(event)

    async def main() -> None:
        with pytest.raises(RuntimeError):
            await chat.emitter.failed(record, specialist_id="r", bot=_Bot(), text=TIMED_OUT)
        chat.emitter._emit_event = slow  # a report arrives while another is being delivered
        first = asyncio.create_task(chat.emitter.completed(record, specialist_id="r", bot=_Bot(), text="Done."))
        second = asyncio.create_task(chat.emitter.failed(record, specialist_id="r", bot=_Bot(), text=TIMED_OUT))
        await asyncio.sleep(0.05)
        gate.set()
        await asyncio.gather(first, second)
        await chat.emitter.failed(record, specialist_id="r", bot=_Bot(), text=TIMED_OUT)

    asyncio.run(main())
    assert chat.endings() == [("delegation_completed", "Done.")]
    assert chat.notices == [("completed", "Done.")]


def test_a_reported_completion_is_marked_on_the_record_it_was_read_from(tmp_path: Path) -> None:
    """The same execution id in two projects: the chat read it from one, and that one is marked."""
    here, there = tmp_path / "here", tmp_path / "there"
    eid = _executing(here, session_id="chat-mark")
    _end("completed", eid, here)
    copy = rt.execution_path(eid, there)
    copy.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(rt.execution_path(eid, here), copy)
    from thomas.core import task_execution_roots

    task_execution_roots.register_root(there)

    rows = session_active_delegations("chat-mark", repo_root=here)
    assert [row.get("ledger_root") for row in rows] == [str(here.resolve())]
    background_completions._mark_completions_reported("chat-mark", rows)

    assert rt.get_execution(eid, here).get("reported_to_chat_at"), "the row's own record was not marked"
    assert not rt.get_execution(eid, there).get("reported_to_chat_at")


def test_a_worker_thread_that_crashes_ends_failed_and_says_so_once_without_its_text(tmp_path: Path) -> None:
    eid = _executing(tmp_path)
    chat = _Chat()

    async def worker(_app: Any, **_kwargs: Any) -> None:
        raise LookupError("the provider said: key sk-not-for-the-chat")

    asyncio.run(
        runner._run_agent_worker_supervised(
            worker, None, execution_id=eid, specialist_id="reasoning", bot=_Bot(), emitter=chat.emitter,
            repo_root=tmp_path, worker_kwargs={},
        )
    )  # fmt: skip
    record = rt.get_execution(eid, tmp_path)
    assert (record["state"], record["blocker"]) == ("failed", "provider_native_failed"), record["progress_summary"]
    assert "LookupError" in record["progress_summary"] and "sk-not-for-the-chat" not in record["progress_summary"]
    assert chat.endings() == [("delegation_failed", record["progress_summary"])]
    assert [event for event, _text in chat.notices] == ["failed"]


def test_an_ending_whose_chat_event_went_out_is_not_sent_again_after_its_notification_was_cancelled() -> None:
    chat = _Chat()
    record = {"execution_id": "exec-sent-once", "session_id": "chat"}
    entered, release = threading.Event(), threading.Event()
    chat.emitter._notifier = lambda *_a, **_k: (entered.set(), release.wait(5))

    async def main() -> None:
        first = asyncio.create_task(chat.emitter.completed(record, specialist_id="r", bot=_Bot(), text="Done."))
        await asyncio.to_thread(entered.wait, 5)
        first.cancel()  # cancelled while its notification runs: its chat event is already out
        with contextlib.suppress(asyncio.CancelledError):
            await first
        release.set()
        await chat.emitter.failed(record, specialist_id="r", bot=_Bot(), text=TIMED_OUT)

    asyncio.run(main())
    assert chat.endings() == [("delegation_completed", "Done.")]


def test_a_refused_stop_still_keeps_the_files_it_salvaged(tmp_path: Path) -> None:
    from thomas.server.chat_delegation_endings import Endings

    eid = _executing(tmp_path)
    rt.fail_execution(eid, actor="stale-sweep", summary="Interrupted.", blocker="stale_interrupted", repo_root=tmp_path)
    ends = Endings(_Chat().emitter, eid, tmp_path, specialist_id="reasoning", bot=_Bot())
    asyncio.run(ends.cancel("Stopped by you.", salvaged_artifacts=["out.txt"], quiet=True))
    record = rt.get_execution(eid, tmp_path)
    assert (record["state"], record["blocker"], record["salvaged_artifacts"]) == (
        "failed",
        "stale_interrupted",
        ["out.txt"],
    )
