"""
Task result storage and retrieval system.

Manages storage and retrieval of task results with:
- Result persistence with TTL
- Batch result retrieval
- Result callbacks
- Result streaming support
- Automatic cleanup of expired results
"""

import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID

from thomas.marketplace.task_queue._types import TaskResult, TaskStatus


class ResultStore:
    """
    Stores and retrieves task results with TTL support.

    Results are automatically cleaned up after TTL expiration.
    Supports batch retrieval and result callbacks.
    """

    def __init__(self, ttl_seconds: int = 86400) -> None:
        """
        Initialize a ResultStore.

        Args:
            ttl_seconds: Time-to-live for results in seconds. Default 24 hours.
        """
        self.ttl_seconds: int = ttl_seconds
        self._results: dict[str | UUID, TaskResult] = {}
        self._result_timestamps: dict[str | UUID, datetime] = {}
        self._callbacks: dict[str | UUID, list[Callable[[TaskResult], None]]] = {}
        self._lock: threading.RLock = threading.RLock()

    def store(self, result: TaskResult) -> None:
        """
        Store a task result.

        Args:
            result: TaskResult to store.
        """
        with self._lock:
            self._results[result.task_id] = result
            self._result_timestamps[result.task_id] = datetime.utcnow()

            # Trigger callbacks
            callbacks = self._callbacks.get(result.task_id, [])
            for callback in callbacks:
                try:
                    callback(result)
                except Exception:
                    pass  # Ignore callback errors

    def get(self, task_id: str | UUID) -> TaskResult | None:
        """
        Retrieve a stored result.

        Args:
            task_id: ID of the task.

        Returns:
            TaskResult if found and not expired, None otherwise.
        """
        with self._lock:
            self._cleanup_expired()

            if task_id not in self._results:
                return None

            result = self._results[task_id]
            timestamp = self._result_timestamps[task_id]

            if self._is_expired(timestamp):
                del self._results[task_id]
                del self._result_timestamps[task_id]
                return None

            return result

    def exists(self, task_id: str | UUID) -> bool:
        """
        Check if a result exists and is not expired.

        Args:
            task_id: ID of the task.

        Returns:
            True if result exists and is not expired.
        """
        return self.get(task_id) is not None

    def delete(self, task_id: str | UUID) -> bool:
        """
        Delete a stored result.

        Args:
            task_id: ID of the task.

        Returns:
            True if result was deleted, False if not found.
        """
        with self._lock:
            if task_id in self._results:
                del self._results[task_id]
                del self._result_timestamps[task_id]
                self._callbacks.pop(task_id, None)
                return True
            return False

    def get_batch(self, task_ids: list[str | UUID]) -> dict[str | UUID, TaskResult | None]:
        """
        Retrieve multiple results at once.

        Args:
            task_ids: List of task IDs to retrieve.

        Returns:
            Dictionary mapping task IDs to results (or None if not found).
        """
        with self._lock:
            return {task_id: self.get(task_id) for task_id in task_ids}

    def register_callback(
        self,
        task_id: str | UUID,
        callback: Callable[[TaskResult], None],
    ) -> None:
        """
        Register a callback to be invoked when result is stored.

        Args:
            task_id: ID of the task to monitor.
            callback: Function to call with the result.
        """
        with self._lock:
            if task_id not in self._callbacks:
                self._callbacks[task_id] = []
            self._callbacks[task_id].append(callback)

    def get_by_status(self, status: TaskStatus) -> list[TaskResult]:
        """
        Get all results with a specific status.

        Args:
            status: TaskStatus to filter by.

        Returns:
            List of matching TaskResults.
        """
        with self._lock:
            self._cleanup_expired()
            return [result for result in self._results.values() if result.status == status]

    def clear(self) -> None:
        """Clear all stored results."""
        with self._lock:
            self._results.clear()
            self._result_timestamps.clear()
            self._callbacks.clear()

    def cleanup_expired(self) -> int:
        """
        Remove all expired results.

        Returns:
            Number of results removed.
        """
        with self._lock:
            return self._cleanup_expired()

    def size(self) -> int:
        """Get number of stored results."""
        with self._lock:
            return len(self._results)

    def get_stats(self) -> dict[str, Any]:
        """
        Get statistics about stored results.

        Returns:
            Dictionary with stats including total, by status, etc.
        """
        with self._lock:
            self._cleanup_expired()

            stats: dict[str, int] = {"total": len(self._results)}
            for status in TaskStatus:
                count = sum(1 for result in self._results.values() if result.status == status)
                stats[f"status_{status.value}"] = count

            return stats

    def _cleanup_expired(self) -> int:
        """
        Remove expired results.

        Returns:
            Number of results removed.
        """
        datetime.utcnow()
        expired = [task_id for task_id, timestamp in self._result_timestamps.items() if self._is_expired(timestamp)]

        for task_id in expired:
            del self._results[task_id]
            del self._result_timestamps[task_id]
            self._callbacks.pop(task_id, None)

        return len(expired)

    def _is_expired(self, timestamp: datetime) -> bool:
        """Check if a result has expired."""
        elapsed = (datetime.utcnow() - timestamp).total_seconds()
        return elapsed > self.ttl_seconds

    def __repr__(self) -> str:
        return f"ResultStore(size={self.size()}, ttl={self.ttl_seconds}s)"


class StreamingResultStore(ResultStore):
    """
    Extended result store with streaming support.

    Allows iterating over results as they arrive.
    """

    def __init__(self, ttl_seconds: int = 86400) -> None:
        """
        Initialize a StreamingResultStore.

        Args:
            ttl_seconds: Time-to-live for results.
        """
        super().__init__(ttl_seconds)
        self._pending_results: list[TaskResult] = []
        self._stream_event: threading.Event = threading.Event()

    def stream_results(self, timeout: float | None = None) -> list[TaskResult]:
        """
        Wait for and retrieve pending results.

        Args:
            timeout: Seconds to wait for results.

        Returns:
            List of pending results.
        """
        self._stream_event.clear()
        self._stream_event.wait(timeout=timeout)

        with self._lock:
            results = list(self._pending_results)
            self._pending_results.clear()
            return results

    def store(self, result: TaskResult) -> None:
        """Store a result and notify stream listeners."""
        with self._lock:
            self._pending_results.append(result)
            self._stream_event.set()
        super().store(result)

    def __repr__(self) -> str:
        return f"StreamingResultStore(size={self.size()}, pending={len(self._pending_results)})"
