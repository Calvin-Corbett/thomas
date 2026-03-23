"""Delivery helpers for channel message retries and dead-lettering."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any


@dataclass
class DeadLetterEntry:
    message_id: str
    reason: str
    payload: dict[str, Any] | None = None


@dataclass
class DeliveryPolicy:
    max_retries: int = 3
    backoff_seconds: float = 0.25
    include_payload_in_dlq: bool = False


class DeliveryQueue:
    """Simple in-memory queue used by command/test surfaces."""

    def __init__(self, *, policy: DeliveryPolicy | None = None) -> None:
        self.policy = policy or DeliveryPolicy()
        self._queue: deque[tuple[dict[str, Any], int]] = deque()

    def enqueue(self, item: dict[str, Any]) -> None:
        self._queue.append((item, 0))

    def dequeue(self) -> dict[str, Any] | None:
        if not self._queue:
            return None
        item, _ = self._queue.popleft()
        return dict(item)

    def requeue(self, item: dict[str, Any], *, attempt: int = 0) -> None:
        self._queue.append((item, attempt))

    def __len__(self) -> int:
        return len(self._queue)
