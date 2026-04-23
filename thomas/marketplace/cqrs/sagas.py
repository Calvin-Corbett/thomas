"""
Saga pattern implementation for long-running transactions.

Manages distributed transactions across multiple aggregates with
automatic compensation on failure and timeout handling.
"""

from __future__ import annotations

import asyncio
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ._exceptions import (
    SagaCompensationException,
    SagaException,
    SagaTimeoutException,
)


class SagaStep(ABC):
    """
    Base class for saga steps.

    A step represents one part of a distributed transaction.
    """

    def __init__(self, name: str) -> None:
        """
        Initialize saga step.

        Args:
            name: Step name for logging
        """
        self.name = name

    @abstractmethod
    async def execute(self, context: dict[str, Any]) -> Any:
        """
        Execute step.

        Args:
            context: Shared context across steps

        Returns:
            Step result to be stored in context
        """
        pass

    @abstractmethod
    async def compensate(self, context: dict[str, Any]) -> None:
        """
        Compensate step (rollback).

        Called if saga fails after this step executed.

        Args:
            context: Shared context with previous results
        """
        pass


@dataclass
class SagaStepResult:
    """Result of saga step execution."""

    step_name: str
    success: bool
    result: Any | None = None
    error: str | None = None
    timestamp: datetime = field(default_factory=datetime.utcnow)


@dataclass
class SagaInstance:
    """
    Running instance of a saga.

    Tracks saga execution state and completed steps.
    """

    saga_id: str
    saga_type: str
    status: str  # "running", "completed", "failed", "compensating"
    context: dict[str, Any] = field(default_factory=dict)
    completed_steps: list[str] = field(default_factory=list)
    results: dict[str, SagaStepResult] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    timeout_at: datetime | None = None


class SagaBase(ABC):
    """
    Base class for sagas.

    Sagas orchestrate distributed transactions across multiple
    aggregates with automatic compensation.
    """

    def __init__(
        self,
        saga_id: str | None = None,
        timeout_seconds: int | None = None,
    ) -> None:
        """
        Initialize saga.

        Args:
            saga_id: Unique saga identifier
            timeout_seconds: Timeout for entire saga
        """
        self.saga_id = saga_id or str(uuid.uuid4())
        self.timeout_seconds = timeout_seconds
        self._steps: list[SagaStep] = []
        self._instance: SagaInstance | None = None

    def add_step(self, step: SagaStep) -> None:
        """
        Add step to saga.

        Args:
            step: Step to add
        """
        self._steps.append(step)

    async def execute(self) -> None:
        """
        Execute saga.

        Runs all steps in order with automatic compensation on failure.

        Raises:
            SagaException: If saga fails and compensation fails
            SagaTimeoutException: If timeout exceeded
        """
        self._instance = SagaInstance(
            saga_id=self.saga_id,
            saga_type=self.__class__.__name__,
            status="running",
            timeout_at=(datetime.utcnow() + timedelta(seconds=self.timeout_seconds) if self.timeout_seconds else None),
        )

        try:
            for step in self._steps:
                # Check timeout
                if self._instance.timeout_at:
                    if datetime.utcnow() > self._instance.timeout_at:
                        raise SagaTimeoutException(f"Saga {self.saga_id} exceeded timeout")

                try:
                    result = await step.execute(self._instance.context)
                    self._instance.context[step.name] = result
                    self._instance.completed_steps.append(step.name)
                    self._instance.results[step.name] = SagaStepResult(
                        step_name=step.name,
                        success=True,
                        result=result,
                    )
                except Exception as e:
                    # Step failed, compensate
                    self._instance.status = "compensating"
                    await self._compensate()
                    self._instance.status = "failed"
                    raise SagaException(f"Saga {self.saga_id} failed at step {step.name}: {str(e)}")

            self._instance.status = "completed"

        except Exception:
            if self._instance.status != "failed":
                self._instance.status = "failed"
            raise

    async def _compensate(self) -> None:
        """
        Compensate completed steps.

        Called when saga fails to rollback side effects.

        Raises:
            SagaCompensationException: If compensation fails
        """
        # Compensate in reverse order
        for step in reversed(self._steps):
            if step.name in self._instance.completed_steps:
                try:
                    await step.compensate(self._instance.context)
                except Exception as e:
                    raise SagaCompensationException(f"Failed to compensate step {step.name}: {str(e)}")

    def get_context(self) -> dict[str, Any]:
        """
        Get saga context.

        Returns:
            Shared context dictionary
        """
        return self._instance.context if self._instance else {}

    def get_instance(self) -> SagaInstance | None:
        """
        Get saga instance.

        Returns:
            SagaInstance or None
        """
        return self._instance

    def is_complete(self) -> bool:
        """
        Check if saga is complete.

        Returns:
            True if completed successfully
        """
        return self._instance and self._instance.status == "completed"

    def is_failed(self) -> bool:
        """
        Check if saga failed.

        Returns:
            True if failed
        """
        return self._instance and self._instance.status == "failed"


class SagaManager:
    """
    Manages saga instances and persistence.

    Tracks running sagas and coordinates execution.
    """

    def __init__(self) -> None:
        """Initialize saga manager."""
        self._sagas: dict[str, SagaInstance] = {}
        self._running: dict[str, SagaBase] = {}
        self._lock = asyncio.Lock()

    async def start_saga(self, saga: SagaBase) -> str:
        """
        Start a saga.

        Args:
            saga: Saga to execute

        Returns:
            Saga ID

        Raises:
            SagaException: If saga execution fails
        """
        async with self._lock:
            saga_id = saga.saga_id
            self._running[saga_id] = saga

        try:
            await saga.execute()
            async with self._lock:
                instance = saga.get_instance()
                if instance:
                    self._sagas[saga_id] = instance
            return saga_id
        except KeyError:
            async with self._lock:
                self._running.pop(saga_id, None)
            raise

    async def get_saga(self, saga_id: str) -> SagaInstance | None:
        """
        Get saga instance by ID.

        Args:
            saga_id: Saga ID to retrieve

        Returns:
            SagaInstance or None
        """
        async with self._lock:
            return self._sagas.get(saga_id)

    async def list_running(self) -> list[str]:
        """
        Get IDs of running sagas.

        Returns:
            List of saga IDs
        """
        async with self._lock:
            return list(self._running.keys())

    async def list_completed(self) -> list[str]:
        """
        Get IDs of completed sagas.

        Returns:
            List of saga IDs
        """
        async with self._lock:
            return [saga_id for saga_id, instance in self._sagas.items() if instance.status == "completed"]

    async def list_failed(self) -> list[str]:
        """
        Get IDs of failed sagas.

        Returns:
            List of saga IDs
        """
        async with self._lock:
            return [saga_id for saga_id, instance in self._sagas.items() if instance.status == "failed"]

    async def cancel_saga(self, saga_id: str) -> None:
        """
        Cancel running saga.

        Args:
            saga_id: Saga to cancel
        """
        async with self._lock:
            saga = self._running.pop(saga_id, None)
            if saga:
                instance = saga.get_instance()
                if instance:
                    instance.status = "failed"

    async def clear(self) -> None:
        """Clear all sagas (for testing)."""
        async with self._lock:
            self._sagas.clear()
            self._running.clear()
