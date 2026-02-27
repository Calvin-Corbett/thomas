"""
Workflow Automation Engine

Main execution engine for running workflows with support for:
- Sequential and parallel step execution
- Conditional branching and loops
- State persistence and resumption
- Error handling with retry logic
- Human approval gates
- Integration with Thomas tools and event bus
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from .models import (
    ErrorAction,
    StepExecutionError,
    StepResult,
    StepStatus,
    Workflow,
    WorkflowExecutionError,
    WorkflowNotFoundError,
    WorkflowRun,
    WorkflowStatus,
)
from .persistence import WorkflowStore
from .steps import StepExecutor

logger = logging.getLogger(__name__)


class WorkflowEngine:
    """Main workflow execution engine.

    Manages workflow registration, execution, state persistence, and lifecycle.
    Supports pause/resume, cancellation, and comprehensive error handling.

    Attributes:
        store: Persistent storage for workflows and runs
        executor: Step executor
        max_concurrent_runs: Maximum concurrent workflows
        event_publisher: Optional event bus publisher
    """

    def __init__(
        self,
        store: WorkflowStore,
        executor: StepExecutor | None = None,
        max_concurrent_runs: int = 10,
        event_publisher: Callable[[str, dict[str, Any]], None] | None = None,
    ):
        """Initialize workflow engine.

        Args:
            store: Persistent storage backend
            executor: Step executor (creates default if None)
            max_concurrent_runs: Maximum concurrent workflow runs
            event_publisher: Optional callback for publishing events
        """
        self.store = store
        self.executor = executor or StepExecutor()
        self.max_concurrent_runs = max_concurrent_runs
        self.event_publisher = event_publisher

        self._running_runs: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def register_workflow(self, workflow: Workflow) -> None:
        """Register a workflow definition.

        Args:
            workflow: Workflow definition to register

        Raises:
            WorkflowValidationError: If workflow is invalid
        """
        workflow.validate()
        await self.store.save_workflow(workflow)
        self._emit("workflow_registered", {"workflow_id": workflow.workflow_id})
        logger.info(f"Registered workflow: {workflow.workflow_id}")

    async def start_workflow(
        self,
        workflow_id: str,
        inputs: dict[str, Any] | None = None,
    ) -> str:
        """Start a workflow execution.

        Args:
            workflow_id: ID of workflow to execute
            inputs: Input parameters for the workflow

        Returns:
            Run ID for tracking execution

        Raises:
            WorkflowNotFoundError: If workflow not found
            WorkflowExecutionError: If execution cannot start
        """
        async with self._lock:
            if len(self._running_runs) >= self.max_concurrent_runs:
                raise WorkflowExecutionError(f"Maximum concurrent runs ({self.max_concurrent_runs}) reached")

        # Load workflow definition
        workflow = await self.store.load_workflow(workflow_id)
        if not workflow:
            raise WorkflowNotFoundError(f"Workflow not found: {workflow_id}")

        # Create execution instance
        run_id = str(uuid.uuid4())
        run = WorkflowRun(
            run_id=run_id,
            workflow_id=workflow_id,
            status=WorkflowStatus.RUNNING,
            inputs=inputs or {},
        )

        await self.store.save_run(run)
        self._emit("workflow_started", {"run_id": run_id, "workflow_id": workflow_id})

        # Schedule execution
        task = asyncio.create_task(self._execute_workflow(run, workflow))
        async with self._lock:
            self._running_runs[run_id] = task

        # Cleanup on completion
        task.add_done_callback(lambda _: asyncio.create_task(self._cleanup_run(run_id)))

        logger.info(f"Started workflow: {workflow_id} (run: {run_id})")
        return run_id

    async def pause_workflow(self, run_id: str) -> None:
        """Pause a running workflow.

        Workflow will pause after the current step completes.

        Args:
            run_id: Run ID to pause

        Raises:
            WorkflowExecutionError: If run not found or not running
        """
        run = await self.store.load_run(run_id)
        if not run:
            raise WorkflowExecutionError(f"Run not found: {run_id}")

        if run.status != WorkflowStatus.RUNNING:
            raise WorkflowExecutionError(f"Cannot pause run with status: {run.status}")

        run.status = WorkflowStatus.PAUSED
        run.paused_at = datetime.now(timezone.utc).isoformat()
        await self.store.save_run(run)
        self._emit("workflow_paused", {"run_id": run_id})
        logger.info(f"Paused workflow: {run_id}")

    async def resume_workflow(self, run_id: str) -> None:
        """Resume a paused workflow.

        Args:
            run_id: Run ID to resume

        Raises:
            WorkflowExecutionError: If run not found or not paused
        """
        run = await self.store.load_run(run_id)
        if not run:
            raise WorkflowExecutionError(f"Run not found: {run_id}")

        if run.status != WorkflowStatus.PAUSED:
            raise WorkflowExecutionError(f"Cannot resume run with status: {run.status}")

        workflow = await self.store.load_workflow(run.workflow_id)
        if not workflow:
            raise WorkflowNotFoundError(f"Workflow not found: {run.workflow_id}")

        run.status = WorkflowStatus.RUNNING
        run.paused_at = None
        await self.store.save_run(run)
        self._emit("workflow_resumed", {"run_id": run_id})

        # Schedule execution
        task = asyncio.create_task(self._execute_workflow(run, workflow))
        async with self._lock:
            self._running_runs[run_id] = task

        logger.info(f"Resumed workflow: {run_id}")

    async def cancel_workflow(self, run_id: str) -> None:
        """Cancel a running workflow.

        Args:
            run_id: Run ID to cancel

        Raises:
            WorkflowExecutionError: If run not found or not running
        """
        run = await self.store.load_run(run_id)
        if not run:
            raise WorkflowExecutionError(f"Run not found: {run_id}")

        if run.status not in (WorkflowStatus.RUNNING, WorkflowStatus.PAUSED):
            raise WorkflowExecutionError(f"Cannot cancel run with status: {run.status}")

        # Cancel execution task
        async with self._lock:
            task = self._running_runs.get(run_id)
            if task and not task.done():
                task.cancel()

        run.status = WorkflowStatus.CANCELLED
        run.finished_at = datetime.now(timezone.utc).isoformat()
        await self.store.save_run(run)
        self._emit("workflow_cancelled", {"run_id": run_id})
        logger.info(f"Cancelled workflow: {run_id}")

    async def get_status(self, run_id: str) -> dict[str, Any]:
        """Get workflow run status.

        Args:
            run_id: Run ID

        Returns:
            Status dictionary with execution details

        Raises:
            WorkflowExecutionError: If run not found
        """
        run = await self.store.load_run(run_id)
        if not run:
            raise WorkflowExecutionError(f"Run not found: {run_id}")

        return {
            "run_id": run.run_id,
            "workflow_id": run.workflow_id,
            "status": run.status.value,
            "current_step": run.current_step,
            "executed_steps": run.executed_steps,
            "step_results": {sid: sr.to_dict() for sid, sr in run.step_results.items()},
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "paused_at": run.paused_at,
            "error": run.error,
            "progress": {
                "total_steps": len(run.executed_steps),
                "completed": sum(1 for sr in run.step_results.values() if sr.status == StepStatus.COMPLETED),
            },
        }

    async def list_workflows(self) -> list[dict[str, Any]]:
        """List all registered workflows.

        Returns:
            List of workflow metadata
        """
        workflows = await self.store.list_workflows()
        return [
            {
                "workflow_id": w.workflow_id,
                "name": w.name,
                "description": w.description,
                "version": w.version,
                "created_at": w.created_at,
                "updated_at": w.updated_at,
            }
            for w in workflows
        ]

    async def list_runs(
        self,
        workflow_id: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List workflow runs.

        Args:
            workflow_id: Filter by workflow ID
            status: Filter by status (running, completed, etc.)

        Returns:
            List of run details
        """
        runs = await self.store.list_runs(workflow_id=workflow_id, status=status)
        return [
            {
                "run_id": r.run_id,
                "workflow_id": r.workflow_id,
                "status": r.status.value,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "current_step": r.current_step,
            }
            for r in runs
        ]

    # ============================================================
    # Internal execution
    # ============================================================

    async def _execute_workflow(self, run: WorkflowRun, workflow: Workflow) -> None:
        """Execute a workflow to completion.

        Args:
            run: Execution instance
            workflow: Workflow definition
        """
        try:
            # Determine starting step
            current_step_id = run.current_step or workflow.entry_step

            while current_step_id:
                # Check for pause signal
                if run.status == WorkflowStatus.PAUSED:
                    await self.store.save_run(run)
                    return

                if run.status != WorkflowStatus.RUNNING:
                    await self.store.save_run(run)
                    return

                step_config = workflow.steps.get(current_step_id)
                if not step_config:
                    raise WorkflowExecutionError(f"Step not found: {current_step_id}")

                # Execute step with retry logic
                result = await self._execute_step_with_retry(step_config, run, workflow)
                run.step_results[current_step_id] = result
                run.executed_steps.append(current_step_id)
                run.current_step = current_step_id

                await self.store.save_run(run)

                # Handle errors
                if result.status == StepStatus.FAILED:
                    if step_config.error_action == ErrorAction.ABORT:
                        raise StepExecutionError(result.error)
                    elif step_config.error_action == ErrorAction.SKIP:
                        self._emit(
                            "step_skipped",
                            {"run_id": run.run_id, "step_id": current_step_id},
                        )

                # Determine next step
                outcome = "success" if result.status == StepStatus.COMPLETED else "failure"
                next_step_id = step_config.next_steps.get(outcome)
                if not next_step_id:
                    next_step_id = step_config.all_next

                current_step_id = next_step_id

            # Workflow completed successfully
            run.status = WorkflowStatus.COMPLETED
            run.finished_at = datetime.now(timezone.utc).isoformat()
            run.current_step = None
            await self.store.save_run(run)
            self._emit("workflow_completed", {"run_id": run.run_id})
            logger.info(f"Workflow completed: {run.run_id}")

        except Exception as e:
            run.status = WorkflowStatus.FAILED
            run.error = str(e)
            run.finished_at = datetime.now(timezone.utc).isoformat()
            await self.store.save_run(run)
            self._emit(
                "workflow_failed",
                {"run_id": run.run_id, "error": str(e)},
            )
            logger.error(f"Workflow failed: {run.run_id}: {e}", exc_info=True)

    async def _execute_step_with_retry(
        self,
        step_config,
        run: WorkflowRun,
        workflow: Workflow,
    ) -> StepResult:
        """Execute a step with retry logic.

        Args:
            step_config: Step configuration
            run: Execution instance
            workflow: Workflow definition

        Returns:
            Step result
        """
        start_time = datetime.now(timezone.utc)
        retry_count = 0

        while retry_count <= step_config.max_retries:
            try:
                result = await self.executor.execute(
                    step_config,
                    run,
                    workflow,
                )
                result.retry_count = retry_count
                result.started_at = start_time.isoformat()
                result.finished_at = datetime.now(timezone.utc).isoformat()
                result.duration_ms = int(
                    (datetime.fromisoformat(result.finished_at) - start_time).total_seconds() * 1000
                )
                return result

            except Exception as e:
                if retry_count < step_config.max_retries:
                    retry_count += 1
                    logger.warning(f"Step failed, retrying ({retry_count}/{step_config.max_retries}): {e}")
                    await asyncio.sleep(min(2**retry_count, 30))
                else:
                    return StepResult(
                        step_id=step_config.step_id,
                        status=StepStatus.FAILED,
                        error=str(e),
                        error_action_taken=step_config.error_action.value,
                        retry_count=retry_count,
                        started_at=start_time.isoformat(),
                        finished_at=datetime.now(timezone.utc).isoformat(),
                    )

        return StepResult(
            step_id=step_config.step_id,
            status=StepStatus.FAILED,
            error="Max retries exceeded",
            retry_count=step_config.max_retries,
            started_at=start_time.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

    async def _cleanup_run(self, run_id: str) -> None:
        """Cleanup after run completion.

        Args:
            run_id: Run ID to cleanup
        """
        async with self._lock:
            self._running_runs.pop(run_id, None)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        """Emit an event.

        Args:
            event_type: Type of event
            payload: Event payload
        """
        if self.event_publisher:
            try:
                self.event_publisher(event_type, payload)
            except Exception as e:
                logger.warning(f"Failed to publish event: {e}")
