from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from thomas.tools.email_calendar import EmailSendTool
from thomas.tools.email_operations import _EmailCalendarService


class _Provider:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def email_send(self, to: str, subject: str, body: str) -> dict[str, Any]:
        await asyncio.sleep(0.01)
        self.sent.append({"to": to, "subject": subject, "body": body})
        return {"id": f"send-{len(self.sent)}", "thread_id": "thread-1"}


@pytest.mark.asyncio
async def test_email_send_idempotency_suppresses_sequential_and_concurrent_retries() -> None:
    provider = _Provider()
    service = _EmailCalendarService(provider, SimpleNamespace(timezone="UTC"))
    kwargs = {
        "to": "owner@example.test",
        "subject": "Parity",
        "body": "Ready.",
        "idempotency_key": "stable-action-1",
    }

    first, replay = await asyncio.gather(service.email_send(**kwargs), service.email_send(**kwargs))
    third = await service.email_send(**kwargs)

    assert provider.sent == [{"to": "owner@example.test", "subject": "Parity", "body": "Ready."}]
    assert first["id"] == replay["id"] == third["id"] == "send-1"
    assert first["idempotent_replay"] is False
    assert replay["idempotent_replay"] is True
    assert third["idempotent_replay"] is True
    assert "idempotency_key" in EmailSendTool.params_schema["properties"]


@pytest.mark.asyncio
async def test_email_send_without_key_preserves_explicit_repeat_behavior() -> None:
    provider = _Provider()
    service = _EmailCalendarService(provider, SimpleNamespace(timezone="UTC"))

    await service.email_send("owner@example.test", "First", "One")
    await service.email_send("owner@example.test", "First", "One")

    assert len(provider.sent) == 2
