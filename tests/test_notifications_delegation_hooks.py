"""CAP-045: automatic completion/blocked/approval-needed notifications with deep links."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from thomas.notifications import delegation_hooks
from thomas.notifications.delegation_hooks import (
    build_notification,
    emit_delegation_notification,
    session_deep_link,
    set_active_dispatcher,
)
from thomas.notifications.dispatcher import NotificationDispatcher
from thomas.notifications.store import NotificationStore
from thomas.server.chat_delegation_emitter import _DelegationEmitter


class _FakeBot:
    def to_event_dict(self) -> dict[str, Any]:
        return {"bot_id": "bot-1", "bot_name": "Testbot"}


def _record(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "execution_id": "exec-123",
        "task_id": "task-9",
        "session_id": "sess-abc",
        "summary": "Refactor the widget pipeline",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def _stable_base_url(monkeypatch):
    monkeypatch.delenv("THOMAS_WEB_BASE_URL", raising=False)


@pytest.fixture()
def dispatcher(tmp_path):
    store = NotificationStore(str(tmp_path / "notifications.sqlite"))
    d = NotificationDispatcher(store=store)
    set_active_dispatcher(d)
    yield d
    set_active_dispatcher(None)


async def _emit(coro):
    return await asyncio.wait_for(coro, timeout=10)


# ---------------------------------------------------------------------------
# Hook-level mapping
# ---------------------------------------------------------------------------


def test_completed_emits_completion_with_deep_link(dispatcher):
    notif = emit_delegation_notification("completed", _record(), text="All done")
    assert notif is not None
    assert notif.type == "completion"
    assert notif.severity == "info"
    assert "Refactor the widget pipeline" in notif.title
    assert notif.action_url == "http://127.0.0.1:8899/?session=sess-abc"

    stored = dispatcher.store.list()
    assert len(stored) == 1
    assert stored[0].type == "completion"
    assert stored[0].action_url == "http://127.0.0.1:8899/?session=sess-abc"


def test_failed_emits_blocked_with_failure_summary(dispatcher):
    notif = emit_delegation_notification("failed", _record(), text="Worker crashed: out of disk")
    assert notif is not None
    assert notif.type == "blocked"
    assert notif.severity == "error"
    assert notif.body == "Worker crashed: out of disk"
    assert notif.action_url == "http://127.0.0.1:8899/?session=sess-abc"


def test_approval_needed_emits_approval_kind(dispatcher):
    notif = emit_delegation_notification("approval_needed", _record(), text="Awaiting your go-ahead")
    assert notif is not None
    assert notif.type == "approval_needed"
    assert notif.severity == "warn"
    assert notif.action_url == "http://127.0.0.1:8899/?session=sess-abc"


def test_duplicate_terminal_event_is_deduplicated(dispatcher):
    first = emit_delegation_notification("completed", _record())
    second = emit_delegation_notification("completed", _record())
    assert first is not None
    assert second is None  # deterministic notification_id -> suppressed
    assert len(dispatcher.store.list()) == 1


def test_unmapped_event_returns_none(dispatcher):
    assert emit_delegation_notification("progress", _record()) is None
    assert len(dispatcher.store.list()) == 0


def test_deep_link_encodes_session_id():
    assert session_deep_link("a b/c") == "http://127.0.0.1:8899/?session=a%20b%2Fc"
    assert session_deep_link("") == "http://127.0.0.1:8899/"


def test_build_notification_falls_back_without_summary():
    payload = build_notification("failed", {"execution_id": "e1", "session_id": "s1"})
    assert payload is not None
    assert payload["type"] == "blocked"
    assert payload["title"] == "Task blocked: background task"
    assert payload["notification_id"] == "delegation:failed:e1"


def test_emit_never_raises_on_broken_dispatcher():
    class _Broken:
        def notify(self, **kwargs):
            raise RuntimeError("store is on fire")

    assert emit_delegation_notification("completed", _record(), dispatcher=_Broken()) is None


# ---------------------------------------------------------------------------
# Emitter wiring (production hook points)
# ---------------------------------------------------------------------------


def test_emitter_completed_calls_notifier_with_completed_event():
    events: list[dict[str, Any]] = []
    calls: list[tuple[str, dict[str, Any], str]] = []

    async def emit_event(evt: dict[str, Any]) -> None:
        events.append(evt)

    def notifier(event: str, record: dict[str, Any], *, text: str = "") -> None:
        calls.append((event, record, text))

    emitter = _DelegationEmitter(emit_event, notifier=notifier)
    asyncio.run(_emit(emitter.completed(_record(), specialist_id="sp", bot=_FakeBot(), text="done")))

    assert [e["type"] for e in events] == ["delegation_completed"]
    assert calls == [("completed", _record(), "done")]


def test_emitter_failed_calls_notifier_with_failed_event():
    calls: list[tuple[str, dict[str, Any], str]] = []

    async def emit_event(evt: dict[str, Any]) -> None:
        return None

    def notifier(event: str, record: dict[str, Any], *, text: str = "") -> None:
        calls.append((event, record, text))

    emitter = _DelegationEmitter(emit_event, notifier=notifier)
    asyncio.run(_emit(emitter.failed(_record(), specialist_id="sp", bot=_FakeBot(), text="boom")))

    assert calls == [("failed", _record(), "boom")]


def test_emitter_approval_needed_calls_notifier():
    calls: list[str] = []

    async def emit_event(evt: dict[str, Any]) -> None:
        return None

    def notifier(event: str, record: dict[str, Any], *, text: str = "") -> None:
        calls.append(event)

    emitter = _DelegationEmitter(emit_event, notifier=notifier)
    asyncio.run(_emit(emitter.approval_needed(_record(), specialist_id="sp", bot=_FakeBot())))

    assert calls == ["approval_needed"]


def test_notifier_exception_does_not_break_delegation_events():
    events: list[dict[str, Any]] = []

    async def emit_event(evt: dict[str, Any]) -> None:
        events.append(evt)

    def notifier(event: str, record: dict[str, Any], *, text: str = "") -> None:
        raise RuntimeError("notification backend down")

    emitter = _DelegationEmitter(emit_event, notifier=notifier)
    # Must not raise.
    asyncio.run(_emit(emitter.completed(_record(), specialist_id="sp", bot=_FakeBot(), text="done")))
    asyncio.run(_emit(emitter.failed(_record(), specialist_id="sp", bot=_FakeBot(), text="boom")))

    assert [e["type"] for e in events] == ["delegation_completed", "delegation_failed"]


def test_emitter_default_notifier_uses_delegation_hooks(monkeypatch, dispatcher):
    calls: list[str] = []

    def fake_hook(event: str, record: dict[str, Any], *, text: str = "", dispatcher: Any = None) -> None:
        calls.append(event)

    monkeypatch.setattr(delegation_hooks, "emit_delegation_notification", fake_hook)

    async def emit_event(evt: dict[str, Any]) -> None:
        return None

    emitter = _DelegationEmitter(emit_event)
    asyncio.run(_emit(emitter.completed(_record(), specialist_id="sp", bot=_FakeBot(), text="done")))

    assert calls == ["completed"]


def test_emitter_end_to_end_persists_notification(dispatcher):
    async def emit_event(evt: dict[str, Any]) -> None:
        return None

    emitter = _DelegationEmitter(emit_event)
    asyncio.run(_emit(emitter.completed(_record(), specialist_id="sp", bot=_FakeBot(), text="shipped")))

    stored = dispatcher.store.list()
    assert len(stored) == 1
    assert stored[0].type == "completion"
    assert stored[0].action_url == "http://127.0.0.1:8899/?session=sess-abc"
