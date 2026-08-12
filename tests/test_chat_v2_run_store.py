from __future__ import annotations

import asyncio
from typing import Any

import pytest

from thomas.marketplace.observability import run_store
from thomas.server.app_keys import APP_RUN_STORE_ENABLED, APP_RUN_STORE_MODULE
from thomas.server.routes.chat_v2_run_store import ChatV2RunLifecycle, start_chat_v2_run


class _Writer:
    def __init__(self, module: _RunStore, run_id: str) -> None:
        self.module = module
        self.run_id = run_id

    def start(self) -> None:
        self.module.order.append("start")
        if self.module.start_error:
            raise RuntimeError("writer start failed")

    def record(self, event: dict[str, Any]) -> None:
        self.module.order.append("record")
        if self.module.record_error:
            raise RuntimeError("writer record failed")
        self.module.events.append(dict(event))

    def close(self) -> None:
        self.module.order.append("close")
        if self.module.close_error:
            raise TimeoutError("writer close failed")


class _RunStore:
    def __init__(
        self,
        *,
        start_error: bool = False,
        record_error: bool = False,
        close_error: bool = False,
        finalize_failures: int = 0,
    ) -> None:
        self.start_error = start_error
        self.record_error = record_error
        self.close_error = close_error
        self.finalize_failures = finalize_failures
        self.order: list[str] = []
        self.events: list[dict[str, Any]] = []
        self.finalized: list[dict[str, Any]] = []

    def create_run(self, metadata: dict[str, Any]) -> str:
        self.order.append("create")
        return str(metadata["run_id"])

    def ThreadedRunWriter(self, run_id: str) -> _Writer:  # noqa: N802 - production module contract
        return _Writer(self, run_id)

    def finalize_run(self, run_id: str, **payload: Any) -> None:
        self.order.append("finalize")
        if self.finalize_failures:
            self.finalize_failures -= 1
            raise RuntimeError("finalize failed")
        self.finalized.append({"run_id": run_id, **payload})


def _start(module: Any):
    app = {APP_RUN_STORE_ENABLED: True, APP_RUN_STORE_MODULE: module}
    return start_chat_v2_run(
        app,
        session_id="session-1",
        profile="sol",
        model_id="gpt-5.6",
        mode="thinking",
        autonomy_level=3,
    )


def test_writer_start_failure_finalizes_created_run_as_failed() -> None:
    module = _RunStore(start_error=True)

    recorder = _start(module)

    assert recorder.module is None
    assert module.order == ["create", "start", "close", "finalize"]
    assert module.finalized[0]["ok"] is False
    assert module.finalized[0]["error"] == "chat run persistence failed to start"


def test_writer_is_closed_before_successful_run_finalization() -> None:
    module = _RunStore()
    recorder = _start(module)
    recorder.record({"type": "token", "text": "hello"})

    recorder.finish(ok=True, usage={"total_tokens": 7})

    assert module.order == ["create", "start", "record", "close", "finalize"]
    assert module.events == [{"type": "token", "text": "hello"}]
    assert module.finalized[0]["ok"] is True
    assert module.finalized[0]["usage"] == {"total_tokens": 7}


def test_writer_close_failure_cannot_be_recorded_as_success() -> None:
    module = _RunStore(close_error=True)
    recorder = _start(module)

    recorder.finish(ok=True)

    assert module.order[-2:] == ["close", "finalize"]
    assert module.finalized[0]["ok"] is False
    assert module.finalized[0]["error"] == "chat run event persistence failed"


def test_event_write_failure_is_sticky_and_marks_run_failed() -> None:
    module = _RunStore(record_error=True)
    recorder = _start(module)

    recorder.record({"type": "token", "text": "lost"})
    recorder.record({"type": "token", "text": "ignored"})
    recorder.finish(ok=True)

    assert module.order.count("record") == 1
    assert module.finalized[0]["ok"] is False
    assert module.finalized[0]["error"] == "chat run event persistence failed"


def test_finish_is_idempotent_after_success() -> None:
    module = _RunStore()
    recorder = _start(module)

    recorder.finish(ok=True)
    recorder.finish(ok=True)

    assert module.order.count("close") == 1
    assert module.order.count("finalize") == 1


def test_finalize_failure_can_be_retried_without_closing_writer_twice() -> None:
    module = _RunStore(finalize_failures=1)
    recorder = _start(module)

    recorder.finish(ok=True)
    recorder.finish(ok=True)

    assert module.order.count("close") == 1
    assert module.order.count("finalize") == 2
    assert module.finalized[0]["ok"] is True


def test_real_run_store_flushes_events_before_success(tmp_path) -> None:
    run_store.init_db(tmp_path / "chat-v2-runs.sqlite3")
    try:
        recorder = _start(run_store)
        recorder.record({"type": "token", "text": "persist me"})

        recorder.finish(ok=True, usage={"total_tokens": 2})

        persisted = run_store.get_run(recorder.run_id)
        assert persisted["run"]["ok"] == 1
        assert persisted["run"]["usage"] == {"total_tokens": 2}
        assert [event["payload"]["text"] for event in persisted["events"]] == ["persist me"]
    finally:
        run_store.shutdown(reset_db_path=True)


@pytest.mark.asyncio
async def test_cancelled_handler_finalizes_failed_run_once_and_cancels_launcher() -> None:
    class _Recorder:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def finish(self, *, ok: bool, usage=None) -> None:  # noqa: ANN001
            self.calls.append({"ok": ok, "usage": usage})

    recorder = _Recorder()
    lifecycle_ready = asyncio.Event()
    wait_forever = asyncio.Event()
    state: dict[str, object] = {}

    async def _handler() -> None:
        lifecycle = ChatV2RunLifecycle(recorder, usage=lambda: {"total_tokens": 9})  # type: ignore[arg-type]
        launcher = lifecycle.track_launcher(asyncio.create_task(wait_forever.wait()))
        state.update(lifecycle=lifecycle, launcher=launcher)
        lifecycle_ready.set()
        await wait_forever.wait()

    task = asyncio.create_task(_handler())
    await lifecycle_ready.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    await asyncio.sleep(0)

    lifecycle = state["lifecycle"]
    launcher = state["launcher"]
    assert recorder.calls == [{"ok": False, "usage": {"total_tokens": 9}}]
    assert isinstance(launcher, asyncio.Task) and launcher.cancelled()
    assert isinstance(lifecycle, ChatV2RunLifecycle)
    lifecycle.finish(ok=True)
    assert len(recorder.calls) == 1
