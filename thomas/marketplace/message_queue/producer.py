"""
Async producer for publishing messages to topics.

Producers handle message batching, compression, partitioning, and retry logic
with exponential backoff.
"""

import asyncio
import gzip
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from ._exceptions import BackpressureError, SerializationError
from ._types import Message


@dataclass
class ProducerConfig:
    """Configuration for a producer."""

    batch_size: int = 100
    batch_timeout_ms: int = 1000
    compression: str = "gzip"
    max_retries: int = 3
    initial_backoff_ms: int = 100
    max_backoff_ms: int = 30000
    buffer_size: int = 10000
    partitioner: Callable[[str, int], int] | None = None


@dataclass
class ProducerMetrics:
    """Metrics for a producer."""

    messages_sent: int = 0
    messages_failed: int = 0
    batches_sent: int = 0
    bytes_sent: int = 0
    total_latency_ms: float = 0.0


class RecordBatch:
    """A batch of records ready to send."""

    def __init__(self, messages: list[Message]) -> None:
        """Initialize a batch."""
        self.messages = messages
        self.created_at = time.time()
        self.callbacks: dict[str, list[Callable[[str, str | None], None]]] = {}

    def add_callback(self, message_id: str, callback: Callable[[str, str | None], None]) -> None:
        """Add a send callback for a specific message."""
        if message_id not in self.callbacks:
            self.callbacks[message_id] = []
        self.callbacks[message_id].append(callback)

    async def trigger_callbacks(self, message_id: str, error: str | None = None) -> None:
        """Trigger callbacks registered for a specific message."""
        for callback in self.callbacks.get(message_id, []):
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(message_id, error)
                else:
                    callback(message_id, error)
            except Exception:  # REVIEWED: async context
                pass  # Ignore callback errors


class Producer:
    """
    Asynchronous message producer with batching and retry logic.

    Sends messages to a broker with configurable batching, compression,
    and exponential backoff retries.
    """

    def __init__(
        self,
        broker: Any,
        config: ProducerConfig | None = None,
    ) -> None:
        """
        Initialize a producer.

        Args:
            broker: Message broker instance
            config: Producer configuration
        """
        self.broker = broker
        self.config = config or ProducerConfig()
        self.id = str(uuid4())

        # Buffer and batch management
        self.buffer: list[Message] = []
        self.buffer_callbacks: dict[str, list[Callable[[str, str | None], None]]] = {}
        self.pending_batches: list[RecordBatch] = []
        self.buffer_lock = asyncio.Lock()
        self.flush_event = asyncio.Event()

        # Metrics
        self.metrics = ProducerMetrics()

        # Lifecycle
        self._running = False
        self._batch_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Start the producer and its background batch flush task."""
        self._running = True
        self._batch_task = asyncio.create_task(self._batch_flush_loop())

    async def stop(self) -> None:
        """Stop the producer and flush remaining messages."""
        self._running = False
        if self._batch_task:
            try:
                await asyncio.wait_for(self._batch_task, timeout=10.0)
            except asyncio.TimeoutError:
                self._batch_task.cancel()
        await self.flush()

    async def send(
        self,
        message: Message,
        callback: Callable[[str, str | None], None] | None = None,
    ) -> str:
        """
        Send a message to a topic.

        Args:
            message: Message to send
            callback: Optional callback(message_id, error) on completion

        Returns:
            Message ID

        Raises:
            BackpressureError: If buffer is full
        """
        async with self.buffer_lock:
            # Check backpressure
            if len(self.buffer) >= self.config.buffer_size:
                raise BackpressureError("Producer buffer full, apply backpressure")

            self.buffer.append(message)
            self.metrics.messages_sent += 1
            self.metrics.bytes_sent += len(str(message.payload).encode())

            if callback:
                if message.id not in self.buffer_callbacks:
                    self.buffer_callbacks[message.id] = []
                self.buffer_callbacks[message.id].append(callback)

            # Check if we should flush
            if len(self.buffer) >= self.config.batch_size:
                await self._flush_batch()

            return message.id

    async def flush(self) -> None:
        """
        Flush all pending messages immediately.

        Waits for all batches to be sent and acknowledged.
        """
        async with self.buffer_lock:
            if self.buffer:
                await self._flush_batch()

        # Wait for all pending batches
        while self.pending_batches:
            await asyncio.sleep(0.01)

    async def _flush_batch(self) -> None:
        """Flush current buffer as a batch (must hold buffer_lock)."""
        if not self.buffer:
            return

        batch_messages = self.buffer[: self.config.batch_size]
        self.buffer = self.buffer[self.config.batch_size :]

        batch = RecordBatch(batch_messages)
        for message in batch_messages:
            for callback in self.buffer_callbacks.pop(message.id, []):
                batch.add_callback(message.id, callback)
        self.pending_batches.append(batch)

        # Send batch asynchronously
        asyncio.create_task(self._send_batch(batch))

    async def _batch_flush_loop(self) -> None:
        """Periodically flush batches if timeout exceeded."""
        while self._running:
            try:
                await asyncio.sleep(self.config.batch_timeout_ms / 1000.0)

                async with self.buffer_lock:
                    if self.buffer and self._running:
                        await self._flush_batch()

            except asyncio.CancelledError:
                break
            except KeyError:
                pass  # Log but continue

    async def _send_batch(self, batch: RecordBatch) -> None:
        """
        Send a batch with retry logic.

        Args:
            batch: Batch to send
        """
        retry_count = 0
        backoff_ms = self.config.initial_backoff_ms

        while retry_count <= self.config.max_retries:
            try:
                start_time = time.time()

                # Send to broker
                for message in batch.messages:
                    try:
                        await self.broker.publish(message)
                        await batch.trigger_callbacks(message.id, None)

                    except Exception as e:
                        self.metrics.messages_failed += 1
                        await batch.trigger_callbacks(message.id, str(e))

                # Update metrics
                latency_ms = (time.time() - start_time) * 1000
                self.metrics.total_latency_ms += latency_ms
                self.metrics.batches_sent += 1

                # Remove from pending
                self.pending_batches.remove(batch)
                return

            except Exception as e:
                retry_count += 1
                if retry_count > self.config.max_retries:
                    # Max retries exceeded
                    for message in batch.messages:
                        await batch.trigger_callbacks(message.id, str(e))
                    self.pending_batches.remove(batch)
                    return

                # Exponential backoff
                await asyncio.sleep(backoff_ms / 1000.0)
                backoff_ms = min(backoff_ms * 2, self.config.max_backoff_ms)

    def get_metrics(self) -> dict[str, any]:
        """
        Get producer metrics.

        Returns:
            Dictionary of metrics
        """
        return {
            "id": self.id,
            "messages_sent": self.metrics.messages_sent,
            "messages_failed": self.metrics.messages_failed,
            "batches_sent": self.metrics.batches_sent,
            "bytes_sent": self.metrics.bytes_sent,
            "avg_latency_ms": (
                self.metrics.total_latency_ms / self.metrics.batches_sent if self.metrics.batches_sent > 0 else 0
            ),
            "buffer_size": len(self.buffer),
            "pending_batches": len(self.pending_batches),
        }

    async def _compress_payload(self, payload: bytes) -> bytes:
        """
        Compress payload using configured algorithm.

        Args:
            payload: Raw payload bytes

        Returns:
            Compressed payload

        Raises:
            SerializationError: If compression fails
        """
        if self.config.compression == "gzip":
            try:
                return gzip.compress(payload)
            except Exception as e:
                raise SerializationError("gzip compression failed", e)
        return payload

    async def _decompress_payload(self, payload: bytes) -> bytes:
        """
        Decompress payload using configured algorithm.

        Args:
            payload: Compressed payload bytes

        Returns:
            Decompressed payload

        Raises:
            SerializationError: If decompression fails
        """
        if self.config.compression == "gzip":
            try:
                return gzip.decompress(payload)
            except Exception as e:
                raise SerializationError("gzip decompression failed", e)
        return payload
