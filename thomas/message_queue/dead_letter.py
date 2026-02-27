"""
Dead Letter Queue (DLQ) for handling failed messages.

Implements retry scheduling with exponential backoff, max retry enforcement,
poison pill detection, and DLQ monitoring.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ._exceptions import DeadLetterError
from ._types import Message


@dataclass
class DeadLetterConfig:
    """Configuration for the dead letter queue."""

    dlq_topic: str = "__dead_letter__"
    max_retries: int = 3
    initial_backoff_ms: int = 100
    max_backoff_ms: int = 30000
    backoff_multiplier: float = 2.0
    enable_poison_pill_detection: bool = True
    poison_pill_threshold: int = 10


@dataclass
class DLQMetadata:
    """Metadata for a message in the DLQ."""

    original_topic: str
    original_offset: int | None = None
    retry_count: int = 0
    error_reason: str = ""
    last_error_time: float | None = None
    next_retry_time: float | None = None
    is_poison_pill: bool = False


class DeadLetterQueue:
    """
    Dead Letter Queue for managing failed messages.

    Routes messages that exceed max retries to a DLQ topic,
    manages retry scheduling, and detects poison pills.
    """

    def __init__(
        self,
        broker: Any,
        config: DeadLetterConfig | None = None,
    ) -> None:
        """
        Initialize the DLQ.

        Args:
            broker: Message broker instance
            config: DLQ configuration
        """
        self.broker = broker
        self.config = config or DeadLetterConfig()

        # DLQ message storage
        self.dlq_messages: dict[str, tuple] = {}  # message_id -> (Message, metadata)
        self.retry_queue: dict[str, float] = {}  # message_id -> next_retry_time
        self.lock = asyncio.Lock()

        # Statistics
        self.total_dlq_messages = 0
        self.total_replayed = 0
        self.poison_pills_detected = 0

        # Replay callbacks
        self.replay_callbacks: list[Callable[[Message], Any]] = []

        # Background tasks
        self._running = False
        self._retry_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the DLQ and its background retry task."""
        async with self.lock:
            self._running = True
            self._retry_task = asyncio.create_task(self._retry_loop())

    async def stop(self) -> None:
        """Stop the DLQ and its background tasks."""
        async with self.lock:
            self._running = False

        if self._retry_task:
            try:
                self._retry_task.cancel()
                await asyncio.wait_for(self._retry_task, timeout=10.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    async def route_to_dlq(
        self,
        message: Message,
        original_topic: str,
        reason: str,
        original_offset: int | None = None,
    ) -> None:
        """
        Route a failed message to the DLQ.

        Args:
            message: Failed message
            original_topic: Original topic it was sent to
            reason: Reason for DLQ routing
            original_offset: Original offset (if applicable)

        Raises:
            DeadLetterError: Always (indicates message routed to DLQ)
        """
        async with self.lock:
            metadata = DLQMetadata(
                original_topic=original_topic,
                original_offset=original_offset,
                retry_count=message.retry_count,
                error_reason=reason,
                last_error_time=time.time(),
            )

            self.dlq_messages[message.id] = (message, metadata)
            self.total_dlq_messages += 1

            # Check for poison pill
            if self._is_poison_pill(message):
                metadata.is_poison_pill = True
                self.poison_pills_detected += 1

            # Schedule retry if under max retries
            if message.retry_count < self.config.max_retries:
                backoff_ms = self._calculate_backoff(message.retry_count)
                next_retry = time.time() + (backoff_ms / 1000.0)
                self.retry_queue[message.id] = next_retry
                metadata.next_retry_time = next_retry

        raise DeadLetterError(original_topic, reason, self.config.max_retries)

    async def schedule_retry(self, message_id: str, delay_ms: int) -> bool:
        """
        Schedule a retry for a DLQ message.

        Args:
            message_id: Message ID in DLQ
            delay_ms: Delay before retry in milliseconds

        Returns:
            True if scheduled, False if not found or max retries exceeded
        """
        async with self.lock:
            if message_id not in self.dlq_messages:
                return False

            message, metadata = self.dlq_messages[message_id]

            if message.retry_count >= self.config.max_retries:
                return False

            next_retry = time.time() + (delay_ms / 1000.0)
            self.retry_queue[message_id] = next_retry
            metadata.next_retry_time = next_retry
            return True

    async def replay(
        self,
        message_id: str,
        target_topic: str | None = None,
    ) -> Message | None:
        """
        Replay a DLQ message back to the original (or target) topic.

        Args:
            message_id: Message ID in DLQ
            target_topic: Topic to send to (default: original topic)

        Returns:
            The replayed message, or None if not found
        """
        async with self.lock:
            if message_id not in self.dlq_messages:
                return None

            message, metadata = self.dlq_messages[message_id]

        # Create new message for replay
        replay_msg = Message(
            id=message.id,
            topic=target_topic or metadata.original_topic,
            payload=message.payload,
            headers=dict(message.headers),
            retry_count=0,
            priority=message.priority,
            partition_key=message.partition_key,
            delivery_mode=message.delivery_mode,
        )

        try:
            # Publish to broker
            await self.broker.publish(replay_msg)
            self.total_replayed += 1

            # Remove from DLQ
            async with self.lock:
                del self.dlq_messages[message_id]
                self.retry_queue.pop(message_id, None)

            # Trigger callbacks
            for callback in self.replay_callbacks:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(replay_msg)
                    else:
                        callback(replay_msg)
                except KeyError:
                    pass

            return replay_msg

        except KeyError:
            return None

    async def replay_all(self, original_topic: str | None = None) -> int:
        """
        Replay all DLQ messages.

        Args:
            original_topic: Only replay messages from this topic (default: all)

        Returns:
            Number of messages replayed
        """
        async with self.lock:
            messages_to_replay = []
            for msg_id, (msg, meta) in list(self.dlq_messages.items()):
                if original_topic is None or meta.original_topic == original_topic:
                    messages_to_replay.append(msg_id)

        replayed = 0
        for msg_id in messages_to_replay:
            if await self.replay(msg_id):
                replayed += 1

        return replayed

    async def _retry_loop(self) -> None:
        """Periodically retry scheduled messages."""
        while self._running:
            try:
                await asyncio.sleep(1.0)

                if self._running:
                    await self._process_retries()

            except asyncio.CancelledError:
                break
            except Exception:  # REVIEWED: async context
                pass

    async def _process_retries(self) -> None:
        """Process messages ready for retry."""
        async with self.lock:
            current_time = time.time()
            messages_to_retry = []

            for msg_id, retry_time in list(self.retry_queue.items()):
                if retry_time <= current_time:
                    messages_to_retry.append(msg_id)

        for msg_id in messages_to_retry:
            if msg_id in self.dlq_messages:
                message, metadata = self.dlq_messages[msg_id]

                # Create retry message
                retry_msg = Message(
                    id=message.id,
                    topic=metadata.original_topic,
                    payload=message.payload,
                    headers=dict(message.headers),
                    retry_count=message.retry_count + 1,
                    priority=message.priority,
                    partition_key=message.partition_key,
                    delivery_mode=message.delivery_mode,
                )

                try:
                    # Publish back to original topic
                    await self.broker.publish(retry_msg)
                    self.total_replayed += 1

                    # Remove from DLQ
                    async with self.lock:
                        del self.dlq_messages[msg_id]
                        self.retry_queue.pop(msg_id, None)

                except (ValueError, TypeError):
                    # Reschedule retry
                    next_backoff = self._calculate_backoff(message.retry_count + 1)
                    next_retry = time.time() + (next_backoff / 1000.0)

                    async with self.lock:
                        if msg_id in self.retry_queue:
                            self.retry_queue[msg_id] = next_retry

    def _calculate_backoff(self, retry_count: int) -> int:
        """
        Calculate exponential backoff.

        Args:
            retry_count: Number of retries already attempted

        Returns:
            Backoff time in milliseconds
        """
        backoff = self.config.initial_backoff_ms * (self.config.backoff_multiplier**retry_count)
        backoff = min(backoff, self.config.max_backoff_ms)
        return int(backoff)

    def _is_poison_pill(self, message: Message) -> bool:
        """
        Detect poison pill messages.

        A poison pill is a message that repeatedly fails
        at the same point in processing.

        Args:
            message: Message to check

        Returns:
            True if message is a poison pill
        """
        if not self.config.enable_poison_pill_detection:
            return False

        # Check if this message has been retried too many times
        # without making progress (same error)
        same_error_count = sum(
            1
            for msg_id, (msg, meta) in self.dlq_messages.items()
            if msg.id == message.id and meta.error_reason == message.get_header("error")
        )

        return same_error_count >= self.config.poison_pill_threshold

    def register_replay_callback(self, callback: Callable[[Message], Any]) -> None:
        """Register a callback to be called when message is replayed."""
        self.replay_callbacks.append(callback)

    async def get_dlq_stats(self) -> dict[str, any]:
        """
        Get DLQ statistics.

        Returns:
            Dictionary of DLQ metrics
        """
        async with self.lock:
            return {
                "total_dlq_messages": self.total_dlq_messages,
                "current_dlq_messages": len(self.dlq_messages),
                "pending_retries": len(self.retry_queue),
                "total_replayed": self.total_replayed,
                "poison_pills_detected": self.poison_pills_detected,
            }

    async def get_dlq_messages(self, max_results: int = 100) -> list[tuple]:
        """
        Get messages currently in the DLQ.

        Args:
            max_results: Maximum messages to return

        Returns:
            List of (Message, metadata) tuples
        """
        async with self.lock:
            return list(self.dlq_messages.values())[:max_results]
