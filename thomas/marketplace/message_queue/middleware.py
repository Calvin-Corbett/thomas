"""
Message middleware pipeline for composable processing.

Implements chainable middleware for logging, metrics, transformation,
filtering, and retry logic.
"""

import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

from ._types import Message


class Middleware(ABC):
    """Base class for message middleware."""

    @abstractmethod
    async def process_inbound(self, message: Message) -> Message | None:
        """
        Process inbound message.

        Args:
            message: Inbound message

        Returns:
            Modified message, or None to drop message
        """
        pass

    @abstractmethod
    async def process_outbound(self, message: Message) -> Message | None:
        """
        Process outbound message.

        Args:
            message: Outbound message

        Returns:
            Modified message, or None to drop message
        """
        pass


class LoggingMiddleware(Middleware):
    """Middleware that logs message events."""

    def __init__(self, logger: Callable[[str], Any] | None = None) -> None:
        """
        Initialize logging middleware.

        Args:
            logger: Logger function (default: print)
        """
        self.logger = logger or print

    async def process_inbound(self, message: Message) -> Message | None:
        """Log inbound message."""
        self.logger(
            f"[INBOUND] Topic: {message.topic}, ID: {message.id}, Payload size: {len(str(message.payload).encode())}"
        )
        return message

    async def process_outbound(self, message: Message) -> Message | None:
        """Log outbound message."""
        self.logger(f"[OUTBOUND] Topic: {message.topic}, ID: {message.id}, Retries: {message.retry_count}")
        return message


class MetricsMiddleware(Middleware):
    """Middleware that collects metrics."""

    def __init__(self) -> None:
        """Initialize metrics middleware."""
        self.inbound_count = 0
        self.outbound_count = 0
        self.dropped_count = 0
        self.total_inbound_bytes = 0
        self.total_outbound_bytes = 0

    async def process_inbound(self, message: Message) -> Message | None:
        """Track inbound metrics."""
        self.inbound_count += 1
        self.total_inbound_bytes += len(str(message.payload).encode())
        return message

    async def process_outbound(self, message: Message) -> Message | None:
        """Track outbound metrics."""
        self.outbound_count += 1
        self.total_outbound_bytes += len(str(message.payload).encode())
        return message

    def get_metrics(self) -> dict:
        """Get collected metrics."""
        return {
            "inbound_count": self.inbound_count,
            "outbound_count": self.outbound_count,
            "dropped_count": self.dropped_count,
            "total_inbound_bytes": self.total_inbound_bytes,
            "total_outbound_bytes": self.total_outbound_bytes,
        }


class TransformationMiddleware(Middleware):
    """Middleware that transforms message payload."""

    def __init__(
        self,
        transform_fn: Callable[[Any], Any],
    ) -> None:
        """
        Initialize transformation middleware.

        Args:
            transform_fn: Function to transform payload
        """
        self.transform_fn = transform_fn

    async def process_inbound(self, message: Message) -> Message | None:
        """Transform inbound message payload."""
        try:
            message.payload = self.transform_fn(message.payload)
            return message
        except Exception:  # REVIEWED: broad catch
            return None

    async def process_outbound(self, message: Message) -> Message | None:
        """Transform outbound message payload."""
        try:
            message.payload = self.transform_fn(message.payload)
            return message
        except Exception:  # REVIEWED: broad catch
            return None


class FilterMiddleware(Middleware):
    """Middleware that filters messages based on predicate."""

    def __init__(
        self,
        predicate: Callable[[Message], bool],
    ) -> None:
        """
        Initialize filter middleware.

        Args:
            predicate: Function to determine if message passes filter
        """
        self.predicate = predicate
        self.filtered_count = 0

    async def process_inbound(self, message: Message) -> Message | None:
        """Filter inbound messages."""
        if not self.predicate(message):
            self.filtered_count += 1
            return None
        return message

    async def process_outbound(self, message: Message) -> Message | None:
        """Filter outbound messages."""
        if not self.predicate(message):
            self.filtered_count += 1
            return None
        return message


class RetryMiddleware(Middleware):
    """Middleware that implements retry logic."""

    def __init__(
        self,
        max_retries: int = 3,
        initial_backoff_ms: int = 100,
    ) -> None:
        """
        Initialize retry middleware.

        Args:
            max_retries: Maximum retries
            initial_backoff_ms: Initial backoff duration
        """
        self.max_retries = max_retries
        self.initial_backoff_ms = initial_backoff_ms
        self.retry_count = 0

    async def process_inbound(self, message: Message) -> Message | None:
        """Check if message should be retried on inbound."""
        if message.retry_count > self.max_retries:
            return None
        return message

    async def process_outbound(self, message: Message) -> Message | None:
        """Track retries on outbound."""
        if message.retry_count > 0:
            self.retry_count += 1
        return message


class HeaderMiddleware(Middleware):
    """Middleware that adds/modifies message headers."""

    def __init__(
        self,
        headers: dict,
    ) -> None:
        """
        Initialize header middleware.

        Args:
            headers: Headers to add to all messages
        """
        self.headers = headers

    async def process_inbound(self, message: Message) -> Message | None:
        """Add headers to inbound messages."""
        for key, value in self.headers.items():
            message.set_header(key, value)
        return message

    async def process_outbound(self, message: Message) -> Message | None:
        """Add headers to outbound messages."""
        for key, value in self.headers.items():
            message.set_header(key, value)
        return message


class TimingMiddleware(Middleware):
    """Middleware that tracks message processing time."""

    def __init__(self) -> None:
        """Initialize timing middleware."""
        self.message_times: dict = {}
        self.total_latency_ms = 0.0
        self.processed_count = 0

    async def process_inbound(self, message: Message) -> Message | None:
        """Record inbound time."""
        self.message_times[message.id] = time.time()
        return message

    async def process_outbound(self, message: Message) -> Message | None:
        """Calculate processing time."""
        if message.id in self.message_times:
            elapsed = time.time() - self.message_times[message.id]
            self.total_latency_ms += elapsed * 1000
            self.processed_count += 1
            del self.message_times[message.id]
        return message

    def get_avg_latency_ms(self) -> float:
        """Get average processing latency."""
        if self.processed_count == 0:
            return 0.0
        return self.total_latency_ms / self.processed_count


class MiddlewarePipeline:
    """
    Composable middleware pipeline for message processing.

    Chains multiple middleware components to form a processing pipeline.
    """

    def __init__(self) -> None:
        """Initialize middleware pipeline."""
        self.inbound_chain: list[Middleware] = []
        self.outbound_chain: list[Middleware] = []

    def add_inbound(self, middleware: Middleware) -> "MiddlewarePipeline":
        """
        Add inbound middleware.

        Args:
            middleware: Middleware to add

        Returns:
            Self for chaining
        """
        self.inbound_chain.append(middleware)
        return self

    def add_outbound(self, middleware: Middleware) -> "MiddlewarePipeline":
        """
        Add outbound middleware.

        Args:
            middleware: Middleware to add

        Returns:
            Self for chaining
        """
        self.outbound_chain.append(middleware)
        return self

    def add_bidirectional(self, middleware: Middleware) -> "MiddlewarePipeline":
        """
        Add middleware to both chains.

        Args:
            middleware: Middleware to add

        Returns:
            Self for chaining
        """
        self.inbound_chain.append(middleware)
        self.outbound_chain.append(middleware)
        return self

    async def process_inbound(self, message: Message) -> Message | None:
        """
        Process message through inbound chain.

        Args:
            message: Message to process

        Returns:
            Processed message or None if dropped
        """
        for middleware in self.inbound_chain:
            if message is None:
                return None
            message = await middleware.process_inbound(message)
        return message

    async def process_outbound(self, message: Message) -> Message | None:
        """
        Process message through outbound chain.

        Args:
            message: Message to process

        Returns:
            Processed message or None if dropped
        """
        for middleware in self.outbound_chain:
            if message is None:
                return None
            message = await middleware.process_outbound(message)
        return message
