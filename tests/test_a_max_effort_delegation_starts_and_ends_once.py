"""A Max-effort ("exhaustive") delegation starts on the delegation pool, reports, and keeps its watchdog's ending.

Two defects found in review of Step 17. Every Max-effort delegation crashed as it started: the worker thread hands
every runner a policy_refusal_sink, and _run_exhaustive_worker did not take one (a TypeError on dev). And when the
watchdog stopped a Max worker (a timeout, or your Stop), the runner's own cancellation branch recorded "Background
execution cancelled." first, so with the first ending kept, the watchdog's real reason was refused. These tests run
the real supervisor, worker thread and Max runner with real records in a temporary project; only the Max pipeline
and the chat stream are stand-ins.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.core import task_bot_runtime as rt
from thomas.server import chat_delegation_runner as runner
from thomas.server.chat_delegation_emitter import _DelegationEmitter
from thomas.server.chat_delegation_exhaustive_runner import _run_exhaustive_worker

RECEIPT = {
    "requested": {"profile": "p", "model": "m"},
    "active": {"profile": "p", "provider": "stand-in", "model": "m"},
    "attempts": [{"profile": "p", "provider": "stand-in", "model": "m", "status": "success"}],
    "pass_id": "answer",
    "role": "solver",
}


class _Bot:
    id = name = "nova"

    def to_event_dict(self) -> dict[str, str]:
        return {"bot_id": "nova"}


class _Chat:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.notices: list[str] = []
        self.emitter = _DelegationEmitter(self._emit, notifier=lambda event, *_a, **_k: self.notices.append(event))

    async def _emit(self, event: dict[str, Any]) -> None:
        self.events.append(event)

    def endings(self) -> list[tuple[str, str]]:
        kinds = {"delegation_completed", "delegation_failed"}
        return [(e["type"], str(e.get("last_progress") or "")) for e in self.events if e["type"] in kinds]


def _supervise(tmp_path: Path, chat: _Chat, *, cancel_when: threading.Event | None = None) -> str:
    eid = rt.create_execution(session_id="chat", summary="Answer it", repo_root=tmp_path)["execution_id"]
    for state in ("classified", "queued", "claimed", "executing"):
        rt.update_execution(eid, state=state, claimed_owner="nova", actor="nova", repo_root=tmp_path)
    work = tmp_path / "work"
    work.mkdir()
    kwargs = {
        "execution_id": eid, "prompt": "What is six times seven?", "specialist_id": "reasoning", "bot": _Bot(),
        "instructions": "Answer.", "repo_root": tmp_path, "work_dir": work, "profile": "p", "model_id": "m",
    }  # fmt: skip

    async def main() -> None:
        supervisor = asyncio.create_task(
            runner._run_agent_worker_supervised(
                _run_exhaustive_worker, None, execution_id=eid, specialist_id="reasoning", bot=_Bot(),
                emitter=chat.emitter, repo_root=tmp_path, worker_kwargs=kwargs,
            )
        )  # fmt: skip
        if cancel_when is not None:
            await asyncio.to_thread(cancel_when.wait, 15)
            rt.request_cancel(eid, actor="user", repo_root=tmp_path)
        await asyncio.wait_for(supervisor, timeout=30)
        if cancel_when is None:
            # A terminal record can precede the chat handoff: let that worker finish.
            for _ in range(200):
                if chat.endings():
                    break
                await asyncio.sleep(0.05)

    asyncio.run(main())
    return eid


def test_a_max_effort_delegation_starts_and_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import thomas.server.exhaustive_runtime as exhaustive_runtime

    async def pipeline(*_args: Any, on_model_runtime: Any, **_kwargs: Any) -> Any:
        await on_model_runtime(dict(RECEIPT))
        return SimpleNamespace(
            aborted=None, verified=True, review_passed=True, result="Six times seven is 42.", rubric={}
        )

    monkeypatch.setattr(exhaustive_runtime, "run_exhaustive_pipeline", pipeline)
    chat = _Chat()
    eid = _supervise(tmp_path, chat)

    record = rt.get_execution(eid, tmp_path)
    assert record["state"] == "completed", record["progress_summary"]
    assert [kind for kind, _text in chat.endings()] == ["delegation_completed"]
    assert chat.notices == ["completed"]


@pytest.mark.parametrize("how", ["timeout", "stop"])
def test_a_max_worker_stopped_by_its_watchdog_keeps_the_watchdogs_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, how: str
) -> None:
    import thomas.server.exhaustive_runtime as exhaustive_runtime

    window = 2.0 if how == "timeout" else 60.0
    for name in ("_WORKER_FIRST_EVENT_TIMEOUT_S", "_WORKER_IDLE_EVENT_TIMEOUT_S"):
        monkeypatch.setattr(runner, name, window)
    monkeypatch.setattr(runner, "_WORKER_WATCHDOG_GRACE_S", 0.0)
    started = threading.Event()

    async def pipeline(*_args: Any, **_kwargs: Any) -> Any:
        started.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(exhaustive_runtime, "run_exhaustive_pipeline", pipeline)
    chat = _Chat()
    eid = _supervise(tmp_path, chat, cancel_when=started if how == "stop" else None)

    record = rt.get_execution(eid, tmp_path)
    late = [entry["blocker"] for entry in record.get("late_terminal_requests") or []]
    assert late == [], f"another ending was written first: {record['progress_summary']}"
    if how == "timeout":
        assert (record["state"], record["blocker"]) == ("failed", "provider_native_timeout"), record["progress_summary"]
        assert record["progress_summary"].startswith("Background execution failed: provider-native worker produced no")
    else:
        assert (record["state"], record["progress_summary"]) == ("cancelled", "Stopped by you.")
    assert chat.endings() == [("delegation_failed", record["progress_summary"])]
