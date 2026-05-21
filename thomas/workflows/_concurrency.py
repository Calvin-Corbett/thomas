"""
Concurrency control for workflow execution.

Limits the maximum number of concurrently executing workflows and
queues new requests until capacity is available.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class ConcurrencyLimiter:
    """Controls maximum concurrent workflow executions."""

    def __init__(self, max_concurrent: int = 10):
        """Initialize concurrency limiter.

        Args:
            max_concurrent: Maximum concurrent workflows (default 10)
        """
        if max_concurrent <= 0:
            raise ValueError("max_concurrent must be positive")

        self.max_concurrent = max_concurrent
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._active_count = 0
        self._queued_count = 0
        self._lock = asyncio.Lock()

    async def acquire(self, workflow_id: str) -> None:
        """Acquire permission to run a workflow.

        Blocks if max_concurrent is reached.

        Args:
            workflow_id: ID of workflow to run
        """
        async with self._lock:
            self._queued_count += 1
            if self._queued_count > 1:
                logger.warning(f"Workflow queue building up: {self._queued_count} waiting, {self._active_count} active")

        # Wait for slot to become available
        await self._semaphore.acquire()

        async with self._lock:
            self._queued_count -= 1
            self._active_count += 1
            logger.debug(
                f"Acquired concurrency slot for {workflow_id} ({self._active_count}/{self.max_concurrent} active)"
            )

    async def release(self, workflow_id: str) -> None:
        """Release concurrency slot.

        Args:
            workflow_id: ID of workflow that finished
        """
        async with self._lock:
            self._active_count = max(0, self._active_count - 1)

        self._semaphore.release()
        logger.debug(
            f"Released concurrency slot from {workflow_id} ({self._active_count}/{self.max_concurrent} active)"
        )

    async def with_limit(self, workflow_id: str, coro):
        """Context manager-style acquisition and release.

        Args:
            workflow_id: ID of workflow
            coro: Coroutine to execute

        Returns:
            Result from coroutine
        """
        await self.acquire(workflow_id)
        try:
            return await coro
        finally:
            await self.release(workflow_id)

    async def status(self) -> dict:
        """Get concurrency status.

        Returns:
            Status dict with active, queued, and max counts
        """
        async with self._lock:
            return {
                "active": self._active_count,
                "queued": self._queued_count,
                "max_concurrent": self.max_concurrent,
                "available_slots": max(0, self.max_concurrent - self._active_count),
            }

    async def wait_for_available(self, timeout_s: float | None = None) -> bool:
        """Wait for an available concurrency slot.

        Args:
            timeout_s: Wait timeout in seconds (None = infinite)

        Returns:
            True if slot became available, False if timeout
        """
        try:
            await asyncio.wait_for(self._semaphore.acquire(), timeout=timeout_s)
            self._semaphore.release()
            return True
        except asyncio.TimeoutError:
            return False
