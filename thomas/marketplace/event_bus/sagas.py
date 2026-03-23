"""
Saga/process manager for long-running workflows triggered by events.

Implements step tracking, compensation on failure, timeout handling,
and saga state persistence.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any

from ._types import Event


class SagaStatus(Enum):
    """Status of a saga execution."""

    STARTED = "started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    COMPENSATING = "compensating"
    COMPENSATED = "compensated"


@dataclass
class SagaStep:
    """
    A step in a saga workflow.

    Attributes:
        name: Step identifier
        action: Async callable to execute
        compensation: Optional compensation to undo action on failure
        timeout: Maximum execution time
    """

    name: str
    action: Callable
    compensation: Callable | None = None
    timeout: float = 30.0


@dataclass
class SagaState:
    """
    Persistent state of a saga execution.

    Attributes:
        saga_id: Unique saga identifier
        status: Current execution status
        started_at: When saga was started
        completed_at: When saga completed/failed
        current_step: Name of current step
        completed_steps: Names of completed steps
        failed_step: Name of failed step if any
        context: User data passed through saga
        error: Error message if failed
    """

    saga_id: str
    status: SagaStatus = SagaStatus.STARTED
    started_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None
    current_step: str = ""
    completed_steps: list[str] = field(default_factory=list)
    failed_step: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def is_complete(self) -> bool:
        """Check if saga has finished."""
        return self.status in (SagaStatus.COMPLETED, SagaStatus.FAILED)

    def duration(self) -> timedelta:
        """Get total execution time."""
        end = self.completed_at or datetime.utcnow()
        return end - self.started_at


class Saga:
    """
    Base class for saga/process manager definitions.

    Subclasses define the workflow steps and compensation logic.
    """

    def __init__(self, saga_id: str) -> None:
        self.saga_id = saga_id
        self.state = SagaState(saga_id=saga_id)
        self._steps: list[SagaStep] = []

    def add_step(
        self,
        name: str,
        action: Callable,
        compensation: Callable | None = None,
        timeout: float = 30.0,
    ) -> None:
        """
        Add a step to the saga.

        Args:
            name: Step name
            action: Async function to execute
            compensation: Optional undo function
            timeout: Max execution time
        """
        self._steps.append(SagaStep(name, action, compensation, timeout))

    def get_steps(self) -> list[SagaStep]:
        """Get all steps."""
        return self._steps[:]

    def get_state(self) -> SagaState:
        """Get current saga state."""
        return self.state


class SagaExecutor:
    """
    Executes sagas with step tracking and compensation.

    Maintains saga state, executes steps in order, and compensates
    on failure by executing compensation in reverse.
    """

    def __init__(self) -> None:
        self._sagas: dict[str, SagaState] = {}

    async def execute(self, saga: Saga) -> SagaState:
        """
        Execute a saga.

        Args:
            saga: The saga to execute

        Returns:
            Final saga state

        Raises:
            Raises exception on fatal failure
        """
        state = saga.get_state()
        self._sagas[saga.saga_id] = state
        state.status = SagaStatus.IN_PROGRESS

        steps = saga.get_steps()

        for step in steps:
            state.current_step = step.name

            try:
                await asyncio.wait_for(step.action(), timeout=step.timeout)
                state.completed_steps.append(step.name)

            except asyncio.TimeoutError:
                state.status = SagaStatus.FAILED
                state.failed_step = step.name
                state.error = f"Step {step.name} timeout"
                await self._compensate(saga, steps)
                state.status = SagaStatus.COMPENSATED
                state.completed_at = datetime.utcnow()
                return state

            except Exception as e:
                state.status = SagaStatus.FAILED
                state.failed_step = step.name
                state.error = str(e)
                await self._compensate(saga, steps)
                state.status = SagaStatus.COMPENSATED
                state.completed_at = datetime.utcnow()
                return state

        state.status = SagaStatus.COMPLETED
        state.completed_at = datetime.utcnow()
        return state

    async def _compensate(self, saga: Saga, steps: list[SagaStep]) -> None:
        """
        Execute compensation steps in reverse order.

        Args:
            saga: The saga being compensated
            steps: The saga steps to compensate
        """
        saga.state.status = SagaStatus.COMPENSATING

        completed = saga.state.completed_steps[:]

        steps_to_compensate = [s for s in steps if s.name in completed]

        for step in reversed(steps_to_compensate):
            if step.compensation:
                try:
                    await asyncio.wait_for(step.compensation(), timeout=step.timeout)
                except Exception:
                    pass

    def get_saga_state(self, saga_id: str) -> SagaState | None:
        """Get state of a saga."""
        return self._sagas.get(saga_id)

    def get_all_sagas(self) -> dict[str, SagaState]:
        """Get all saga states."""
        return self._sagas.copy()


class EventTriggeredSaga:
    """
    Saga triggered by domain events.

    Listens for specific event types and initiates corresponding sagas.
    """

    def __init__(self, executor: SagaExecutor) -> None:
        self.executor = executor
        self._handlers: dict[str, Callable] = {}

    def on_event_type(self, event_type: str) -> Callable:
        """
        Register handler for event type.

        Usage:
            saga_manager = EventTriggeredSaga(executor)

            @saga_manager.on_event_type('OrderPlaced')
            async def handle_order_placed(event: Event) -> Saga:
                saga = OrderProcessingSaga(event.source)
                saga.add_step('charge_card', charge_card_fn)
                saga.add_step('reserve_inventory', reserve_fn)
                return saga
        """

        def decorator(func: Callable) -> Callable:
            self._handlers[event_type] = func
            return func

        return decorator

    async def handle_event(self, event: Event) -> SagaState | None:
        """
        Handle an event, triggering appropriate saga.

        Args:
            event: The event that triggered the saga

        Returns:
            Saga state or None if no handler
        """
        handler = self._handlers.get(event.type)

        if not handler:
            return None

        saga = await self._call_handler(handler, event)

        if saga:
            return await self.executor.execute(saga)

        return None

    @staticmethod
    async def _call_handler(handler: Callable, event: Event) -> Saga | None:
        """Call handler, converting sync to async."""
        if asyncio.iscoroutinefunction(handler):
            return await handler(event)
        else:
            return await asyncio.to_thread(handler, event)


class SagaBuilder:
    """
    Fluent builder for creating sagas.

    Example:
        saga = (SagaBuilder('order-123')
                .add_step('charge_card', charge_fn)
                .add_step('reserve_inventory', reserve_fn, undo_reserve_fn)
                .build())
    """

    def __init__(self, saga_id: str) -> None:
        self.saga_id = saga_id
        self._steps: list[SagaStep] = []

    def add_step(
        self,
        name: str,
        action: Callable,
        compensation: Callable | None = None,
        timeout: float = 30.0,
    ) -> SagaBuilder:
        """Add a step."""
        self._steps.append(SagaStep(name, action, compensation, timeout))
        return self

    def with_context(self, context: dict[str, Any]) -> SagaBuilder:
        """Set context data."""
        self._context = context
        return self

    def build(self) -> Saga:
        """Build the saga."""
        saga = Saga(self.saga_id)
        for step in self._steps:
            saga.add_step(step.name, step.action, step.compensation, step.timeout)
        return saga
