from __future__ import annotations

import asyncio
import json

from thomas.chat.event_stream import EventDispatcher


def test_dispatcher_adds_monotonic_sequence_and_stable_run_id() -> None:
    writes: list[bytes] = []

    async def send(data: bytes) -> None:
        writes.append(data)

    async def run() -> None:
        dispatcher = EventDispatcher(send, run_id="run-fixed")
        await asyncio.gather(
            dispatcher.emit({"type": "text", "text": "one"}),
            dispatcher.emit({"type": "text", "text": "two"}),
        )

    asyncio.run(run())

    events = [json.loads(item) for item in writes]
    assert [event["seq"] for event in events] == [0, 1]
    assert {event["run_id"] for event in events} == {"run-fixed"}


def test_dispatcher_retry_reuses_sequence_and_counts_one_event() -> None:
    writes: list[bytes] = []
    attempts = 0

    async def send(data: bytes) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise ConnectionError("transient")
        writes.append(data)

    async def run() -> EventDispatcher:
        dispatcher = EventDispatcher(send, run_id="run-retry")
        await dispatcher.emit({"type": "done"})
        return dispatcher

    dispatcher = asyncio.run(run())

    assert attempts == 2
    assert dispatcher.event_count == 1
    assert json.loads(writes[0]) == {"type": "done", "seq": 0, "run_id": "run-retry"}


def test_dispatcher_drops_unserializable_event_without_retrying_unbound_data(caplog) -> None:
    attempts = 0

    async def send(_data: bytes) -> None:
        nonlocal attempts
        attempts += 1

    recursive: dict[str, object] = {"type": "text"}
    recursive["value"] = recursive

    async def run() -> EventDispatcher:
        dispatcher = EventDispatcher(send, run_id="run-serialize")
        await dispatcher.emit(recursive)
        return dispatcher

    dispatcher = asyncio.run(run())

    assert attempts == 0
    assert dispatcher.event_count == 0
    assert "Event serialization failed" in caplog.text


def test_dispatcher_keeps_streaming_after_operational_event_sink_failure(caplog) -> None:
    writes: list[bytes] = []

    async def send(data: bytes) -> None:
        writes.append(data)

    def persist(_event: dict[str, object]) -> None:
        raise OSError("run store unavailable")

    async def run() -> EventDispatcher:
        dispatcher = EventDispatcher(send, run_id="run-persist", event_sink=persist)
        await dispatcher.emit({"type": "text", "text": "still delivered"})
        return dispatcher

    dispatcher = asyncio.run(run())

    assert dispatcher.event_count == 1
    assert json.loads(writes[0])["text"] == "still delivered"
    assert "Event persistence failed without interrupting chat" in caplog.text
