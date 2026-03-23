"""
Task batching for efficient bulk processing.

Implements batch task handling with:
- Batch task grouping
- Batch execution
- Batch splitting and result aggregation
- Batch state management
"""

import threading
from collections.abc import Callable
from typing import Any
from uuid import uuid4

from thomas.marketplace.task_queue._exceptions import BatchError
from thomas.marketplace.task_queue._types import Task, TaskStatus


class BatchTask(Task):
    """Represents a batch of tasks to be processed together."""

    def __init__(
        self,
        name: str,
        func: Callable[..., Any],
        batch_items: list[tuple[tuple, dict[str, Any]]],
        priority: int = 0,
        timeout: float = 300.0,
        **kwargs: Any,
    ) -> None:
        """
        Initialize a BatchTask.

        Args:
            name: Name of the batch task.
            func: Function that processes a batch.
            batch_items: List of (args, kwargs) tuples for items in batch.
            priority: Task priority.
            timeout: Task timeout in seconds.
            **kwargs: Additional task attributes.
        """
        self.batch_items: list[tuple[tuple, dict[str, Any]]] = batch_items
        self.batch_size: int = len(batch_items)
        self.batch_id: str = str(uuid4())
        self.batch_results: list[Any] = []

        super().__init__(
            name=name,
            func=func,
            args=(),
            kwargs={"batch_items": batch_items},
            priority=priority,
            timeout=timeout,
            metadata={
                "batch_id": self.batch_id,
                "batch_size": self.batch_size,
                **kwargs.get("metadata", {}),
            },
            **kwargs,
        )

    def __repr__(self) -> str:
        return (
            f"BatchTask(id={self.task_id}, name={self.name}, "
            f"batch_size={self.batch_size}, status={self.status.value})"
        )


class BatchExecutor:
    """
    Executes batched tasks and aggregates results.

    Handles batch splitting, parallel item processing within a batch,
    and result aggregation.
    """

    def __init__(
        self,
        batch_timeout: float = 60.0,
        max_batch_size: int = 100,
    ) -> None:
        """
        Initialize a BatchExecutor.

        Args:
            batch_timeout: Timeout for entire batch.
            max_batch_size: Maximum items in a batch.
        """
        self.batch_timeout: float = batch_timeout
        self.max_batch_size: int = max_batch_size
        self._batches: dict[str, BatchTask] = {}
        self._batch_lock: threading.RLock = threading.RLock()
        self._accumulator: dict[str, list[tuple[tuple, dict[str, Any]]]] = {}
        self._accumulator_lock: threading.RLock = threading.RLock()

    def add_to_batch(
        self,
        batch_name: str,
        args: tuple,
        kwargs: dict[str, Any],
        task_func: Callable[..., Any],
        priority: int = 0,
    ) -> BatchTask | None:
        """
        Add an item to a batch. Creates batch task when full.

        Args:
            batch_name: Name of the batch group.
            args: Arguments for this item.
            kwargs: Keyword arguments for this item.
            task_func: Function that processes batches.
            priority: Task priority.

        Returns:
            BatchTask if batch is full and ready to execute, None otherwise.
        """
        with self._accumulator_lock:
            if batch_name not in self._accumulator:
                self._accumulator[batch_name] = []

            self._accumulator[batch_name].append((args, kwargs))

            if len(self._accumulator[batch_name]) >= self.max_batch_size:
                items = self._accumulator.pop(batch_name)
                return BatchTask(
                    name=batch_name,
                    func=task_func,
                    batch_items=items,
                    priority=priority,
                )

            return None

    def flush_batch(
        self,
        batch_name: str,
        task_func: Callable[..., Any],
        priority: int = 0,
    ) -> BatchTask | None:
        """
        Create a batch task from accumulated items.

        Args:
            batch_name: Name of the batch group.
            task_func: Function that processes batches.
            priority: Task priority.

        Returns:
            BatchTask if items exist, None if accumulator is empty.
        """
        with self._accumulator_lock:
            if batch_name in self._accumulator and self._accumulator[batch_name]:
                items = self._accumulator.pop(batch_name)
                return BatchTask(
                    name=batch_name,
                    func=task_func,
                    batch_items=items,
                    priority=priority,
                )
            return None

    def execute_batch(self, batch_task: BatchTask) -> list[Any]:
        """
        Execute a batch task.

        Args:
            batch_task: BatchTask to execute.

        Returns:
            List of results from batch execution.

        Raises:
            BatchError: If batch execution fails.
        """
        try:
            results = batch_task.func(batch_items=batch_task.batch_items)
            batch_task.batch_results = results
            batch_task.status = TaskStatus.COMPLETED
            return results
        except Exception as e:
            batch_task.status = TaskStatus.FAILED
            raise BatchError(batch_task.batch_id, f"Batch execution failed: {e}")

    def split_batch(
        self,
        batch_task: BatchTask,
        chunk_size: int,
    ) -> list[BatchTask]:
        """
        Split a large batch into smaller batches.

        Args:
            batch_task: BatchTask to split.
            chunk_size: Maximum items per new batch.

        Returns:
            List of new BatchTask instances.
        """
        if chunk_size >= batch_task.batch_size:
            return [batch_task]

        new_batches = []
        for i in range(0, batch_task.batch_size, chunk_size):
            chunk = batch_task.batch_items[i : i + chunk_size]
            new_batch = BatchTask(
                name=batch_task.name,
                func=batch_task.func,
                batch_items=chunk,
                priority=batch_task.priority,
                timeout=batch_task.timeout,
                metadata=dict(batch_task.metadata),
            )
            new_batch.metadata["parent_batch_id"] = batch_task.batch_id
            new_batches.append(new_batch)

        return new_batches

    def aggregate_results(
        self,
        batch_results: list[list[Any]],
    ) -> list[Any]:
        """
        Aggregate results from multiple batch executions.

        Args:
            batch_results: List of result lists from batch tasks.

        Returns:
            Flattened list of all results.
        """
        aggregated = []
        for results in batch_results:
            if isinstance(results, list):
                aggregated.extend(results)
            else:
                aggregated.append(results)
        return aggregated

    def get_accumulator_size(self, batch_name: str) -> int:
        """
        Get number of items in a batch accumulator.

        Args:
            batch_name: Name of the batch.

        Returns:
            Number of accumulated items.
        """
        with self._accumulator_lock:
            return len(self._accumulator.get(batch_name, []))

    def get_all_accumulators(self) -> dict[str, int]:
        """
        Get sizes of all batch accumulators.

        Returns:
            Dictionary mapping batch names to item counts.
        """
        with self._accumulator_lock:
            return {name: len(items) for name, items in self._accumulator.items()}

    def clear_accumulator(self, batch_name: str) -> bool:
        """
        Clear a batch accumulator.

        Args:
            batch_name: Name of the batch.

        Returns:
            True if accumulator existed and was cleared.
        """
        with self._accumulator_lock:
            if batch_name in self._accumulator:
                del self._accumulator[batch_name]
                return True
            return False

    def __repr__(self) -> str:
        return f"BatchExecutor(max_size={self.max_batch_size}, " f"accumulators={len(self._accumulator)})"


class BatchProcessor:
    """
    High-level interface for batch processing workflows.

    Handles batch creation, submission, and result collection.
    """

    def __init__(self, executor: BatchExecutor | None = None) -> None:
        """
        Initialize a BatchProcessor.

        Args:
            executor: Optional BatchExecutor instance.
        """
        self.executor: BatchExecutor = executor or BatchExecutor()
        self._batch_map: dict[str, BatchTask] = {}
        self._lock: threading.RLock = threading.RLock()

    def create_batch(
        self,
        batch_name: str,
        batch_func: Callable[..., Any],
        items: list[tuple[tuple, dict[str, Any]]],
        priority: int = 0,
    ) -> BatchTask:
        """
        Create a batch task.

        Args:
            batch_name: Name for the batch.
            batch_func: Function to process the batch.
            items: List of (args, kwargs) tuples.
            priority: Task priority.

        Returns:
            Created BatchTask.
        """
        batch = BatchTask(
            name=batch_name,
            func=batch_func,
            batch_items=items,
            priority=priority,
        )

        with self._lock:
            self._batch_map[batch.batch_id] = batch

        return batch

    def get_batch(self, batch_id: str) -> BatchTask | None:
        """
        Retrieve a batch by ID.

        Args:
            batch_id: ID of the batch.

        Returns:
            BatchTask or None if not found.
        """
        with self._lock:
            return self._batch_map.get(batch_id)

    def remove_batch(self, batch_id: str) -> bool:
        """
        Remove a batch.

        Args:
            batch_id: ID of the batch.

        Returns:
            True if removed, False if not found.
        """
        with self._lock:
            if batch_id in self._batch_map:
                del self._batch_map[batch_id]
                return True
            return False

    def __repr__(self) -> str:
        return f"BatchProcessor(batches={len(self._batch_map)})"
