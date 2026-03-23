"""
Process manager for long-running process coordination.

Manages orchestration of multi-step processes with state tracking,
correlation, and timeout handling.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from ._exceptions import ProcessManagerException


@dataclass
class ProcessStep:
    """Configuration for a process step."""

    name: str
    handler: Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
    timeout_seconds: int | None = None
    retry_count: int = 0


@dataclass
class ProcessInstance:
    """
    Running instance of a process.

    Tracks state, progress, and context across steps.
    """

    process_id: str
    process_type: str
    status: str  # "running", "completed", "failed", "paused"
    context: dict[str, Any] = field(default_factory=dict)
    completed_steps: list[str] = field(default_factory=list)
    current_step: str | None = None
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    timeout_at: datetime | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class ProcessManager:
    """
    Coordinates long-running business processes.

    Manages process instances, state transitions, and correlation
    tracking across multiple steps.
    """

    def __init__(self) -> None:
        """Initialize process manager."""
        self._processes: dict[str, ProcessDefinition] = {}
        self._instances: dict[str, ProcessInstance] = {}
        self._lock = asyncio.Lock()
        self._event_handlers: list[Callable] = []

    def define_process(
        self,
        name: str,
        steps: list[ProcessStep],
        timeout_seconds: int | None = None,
    ) -> ProcessDefinition:
        """
        Define a new process.

        Args:
            name: Process name
            steps: Process steps in order
            timeout_seconds: Overall timeout

        Returns:
            ProcessDefinition
        """
        definition = ProcessDefinition(
            name=name,
            steps=steps,
            timeout_seconds=timeout_seconds,
        )
        self._processes[name] = definition
        return definition

    async def start_process(
        self,
        process_type: str,
        initial_context: dict[str, Any] | None = None,
        process_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProcessInstance:
        """
        Start a new process instance.

        Args:
            process_type: Type of process to start
            initial_context: Initial context data
            process_id: Optional custom process ID
            metadata: Optional metadata

        Returns:
            ProcessInstance

        Raises:
            ProcessManagerException: If process not defined
        """
        async with self._lock:
            if process_type not in self._processes:
                raise ProcessManagerException(f"Process type not defined: {process_type}")

            pid = process_id or str(uuid.uuid4())
            definition = self._processes[process_type]

            instance = ProcessInstance(
                process_id=pid,
                process_type=process_type,
                status="running",
                context=initial_context or {},
                metadata=metadata or {},
                timeout_at=(
                    datetime.utcnow() + timedelta(seconds=definition.timeout_seconds)
                    if definition.timeout_seconds
                    else None
                ),
            )

            self._instances[pid] = instance
            return instance

    async def execute_process(
        self,
        process_type: str,
        initial_context: dict[str, Any] | None = None,
    ) -> ProcessInstance:
        """
        Execute a complete process.

        Runs all steps sequentially with automatic coordination.

        Args:
            process_type: Type of process to execute
            initial_context: Initial context

        Returns:
            Completed ProcessInstance

        Raises:
            ProcessManagerException: If execution fails
        """
        instance = await self.start_process(
            process_type,
            initial_context,
        )

        definition = self._processes[process_type]

        try:
            for step in definition.steps:
                # Check timeout
                if instance.timeout_at:
                    if datetime.utcnow() > instance.timeout_at:
                        instance.status = "failed"
                        raise ProcessManagerException(f"Process {instance.process_id} exceeded timeout")

                instance.current_step = step.name

                # Execute step with retry
                result = await self._execute_step_with_retry(
                    step,
                    instance.context,
                )

                instance.context.update(result)
                instance.completed_steps.append(step.name)
                instance.updated_at = datetime.utcnow()

            instance.status = "completed"
            instance.current_step = None

        except Exception as e:
            instance.status = "failed"
            raise ProcessManagerException(f"Process {instance.process_id} failed: {str(e)}")

        return instance

    async def _execute_step_with_retry(
        self,
        step: ProcessStep,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """
        Execute step with retry logic.

        Args:
            step: Step to execute
            context: Current context

        Returns:
            Step result

        Raises:
            ProcessManagerException: If step fails
        """
        last_error = None

        for attempt in range(step.retry_count + 1):
            try:
                timeout = step.timeout_seconds or 30.0
                return await asyncio.wait_for(
                    step.handler(context),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                last_error = ProcessManagerException(f"Step {step.name} timed out after {step.timeout_seconds}s")
            except Exception as e:
                last_error = e

            if attempt < step.retry_count:
                await asyncio.sleep(0.5)

        if last_error:
            raise last_error
        raise ProcessManagerException(f"Step {step.name} failed")

    async def pause_process(self, process_id: str) -> None:
        """
        Pause running process.

        Args:
            process_id: Process to pause
        """
        async with self._lock:
            instance = self._instances.get(process_id)
            if instance:
                instance.status = "paused"

    async def resume_process(self, process_id: str) -> None:
        """
        Resume paused process.

        Args:
            process_id: Process to resume
        """
        async with self._lock:
            instance = self._instances.get(process_id)
            if instance and instance.status == "paused":
                instance.status = "running"

    async def get_instance(self, process_id: str) -> ProcessInstance | None:
        """
        Get process instance.

        Args:
            process_id: Process ID

        Returns:
            ProcessInstance or None
        """
        async with self._lock:
            return self._instances.get(process_id)

    async def list_instances(
        self,
        process_type: str | None = None,
        status: str | None = None,
    ) -> list[ProcessInstance]:
        """
        List process instances.

        Args:
            process_type: Filter by type
            status: Filter by status

        Returns:
            List of instances
        """
        async with self._lock:
            results = list(self._instances.values())

            if process_type:
                results = [i for i in results if i.process_type == process_type]

            if status:
                results = [i for i in results if i.status == status]

            return results

    async def get_by_correlation(self, correlation_id: str) -> list[ProcessInstance]:
        """
        Get instances by correlation ID.

        Args:
            correlation_id: Correlation ID to search

        Returns:
            Matching instances
        """
        async with self._lock:
            return [instance for instance in self._instances.values() if instance.correlation_id == correlation_id]

    def subscribe_to_events(self, handler: Callable) -> None:
        """
        Subscribe to process events.

        Args:
            handler: Event handler callback
        """
        self._event_handlers.append(handler)

    async def _publish_event(self, event: str, instance: ProcessInstance) -> None:
        """Publish process event."""
        for handler in self._event_handlers:
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(event, instance)
                else:
                    handler(event, instance)
            except Exception:  # REVIEWED: async context
                pass

    async def clear(self) -> None:
        """Clear all instances (for testing)."""
        async with self._lock:
            self._instances.clear()


@dataclass
class ProcessDefinition:
    """Definition of a long-running process."""

    name: str
    steps: list[ProcessStep]
    timeout_seconds: int | None = None

    def __post_init__(self) -> None:
        """Validate definition."""
        if not self.steps:
            raise ValueError("Process must have at least one step")
