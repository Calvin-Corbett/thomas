"""A card raised by background work is filed under the chat that asked for it.

A worker knows only its execution id; ``set_chat_from_execution`` reads the chat
from the execution record. It read ``session_id``, but the record names the chat
``conversation_id`` and a background execution has no ``session_id`` at all, so
every such card was filed under the run's per-attempt id, where no page looks.
Observed live on 2026-09-22: an approval card waited ten minutes unseen.
"""

from __future__ import annotations

import contextvars
from typing import Any

import pytest

from thomas.core import session_scope, task_bot_runtime


def _chat_for(record: dict[str, Any] | None, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(task_bot_runtime, "get_execution", lambda _execution_id, _root: record)

    def _bind() -> str:
        session_scope.set_chat_from_execution("exec-7")
        return session_scope.active_chat_id()

    return contextvars.copy_context().run(_bind)


@pytest.mark.parametrize("key", ["conversation_id", "session_id", "thread_id"])
def test_the_chat_is_read_under_any_name_the_record_uses(key: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert _chat_for({key: "chat-42"}, monkeypatch) == "chat-42"


def test_a_record_without_a_chat_leaves_the_card_where_it_was(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _chat_for({"status": "running"}, monkeypatch) == ""
    assert _chat_for(None, monkeypatch) == ""
