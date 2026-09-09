"""
Workflow Automation Engine - Data Models

Defines the core data structures for workflows, steps, executions, and results.
All models are designed for persistence and state resumption across restarts.

Features:
- Immutable workflow definitions with versioning
- Execution instances tracking state and history
- Step-level granularity for pause/resume capability
- Comprehensive error tracking and retry metadata
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

# ============================================================
# Enums
# ============================================================


class StepType(str, Enum):
    """Types of workflow steps."""

    TOOL_CALL = "tool_call"
    LLM_PROMPT = "llm_prompt"
    CONDITION = "condition"
    LOOP = "loop"
    PARALLEL = "parallel"
    WAIT = "wait"
    APPROVAL = "approval"
    WEBHOOK = "webhook"


class WorkflowStatus(str, Enum):
    """Workflow execution status."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    """Individual step execution status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    WAITING = "waiting"


class ErrorAction(str, Enum):
    """How to handle step errors."""

    RETRY = "retry"
    SKIP = "skip"
    ABORT = "abort"


# ============================================================
# Exceptions
# ============================================================


class WorkflowError(Exception):
    """Base workflow exception."""

    pass


class WorkflowNotFoundError(WorkflowError):
    """Workflow definition not found."""

    pass


class WorkflowExecutionError(WorkflowError):
    """Workflow execution failed."""

    pass


class StepExecutionError(WorkflowError):
    """Step execution failed."""

    pass


class WorkflowPersistenceError(WorkflowError):
    """Failed to persist workflow state."""

    pass


class WorkflowValidationError(WorkflowError):
    """Workflow definition is invalid."""

    pass


# ============================================================
# Core Models
# ============================================================


@dataclass
class StepConfig:
    """Configuration for a workflow step.

    Attributes:
        step_id: Unique identifier for this step
        step_type: Type of step (tool_call, llm_prompt, etc.)
        config: Step-specific configuration (tool name, prompt template, etc.)
        error_action: How to handle errors (retry, skip, abort)
        max_retries: Maximum number of retries on failure
        timeout_seconds: Execution timeout in seconds (None = no limit)
        skip_condition: Optional condition to skip step
        next_steps: Map of outcome -> next step IDs (for branching)
        all_next: Default next step if none in next_steps match
    """

    step_id: str
    step_type: StepType
    config: dict[str, Any]
    error_action: ErrorAction = ErrorAction.ABORT
    max_retries: int = 0
    timeout_seconds: int | None = None
    skip_condition: str | None = None
    next_steps: dict[str, str] = field(default_factory=dict)
    all_next: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "step_id": self.step_id,
            "step_type": self.step_type.value,
            "config": self.config,
            "error_action": self.error_action.value,
            "max_retries": self.max_retries,
            "timeout_seconds": self.timeout_seconds,
            "skip_condition": self.skip_condition,
            "next_steps": self.next_steps,
            "all_next": self.all_next,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> StepConfig:
        """Create from dictionary."""
        return StepConfig(
            step_id=data["step_id"],
            step_type=StepType(data["step_type"]),
            config=data["config"],
            error_action=ErrorAction(data.get("error_action", "abort")),
            max_retries=data.get("max_retries", 0),
            timeout_seconds=data.get("timeout_seconds"),
            skip_condition=data.get("skip_condition"),
            next_steps=data.get("next_steps", {}),
            all_next=data.get("all_next"),
        )


@dataclass
class Workflow:
    """Workflow definition.

    Immutable definition of a workflow. Versioned and includes metadata.

    Attributes:
        workflow_id: Unique identifier
        name: Human-readable name
        description: Long description
        version: Version number
        steps: Map of step_id -> StepConfig
        entry_step: First step to execute
        metadata: Custom metadata (tags, labels, etc.)
        created_at: Creation timestamp
        updated_at: Last update timestamp
    """

    workflow_id: str
    name: str
    description: str
    steps: dict[str, StepConfig]
    entry_step: str
    version: int = 1
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "workflow_id": self.workflow_id,
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "steps": {sid: sc.to_dict() for sid, sc in self.steps.items()},
            "entry_step": self.entry_step,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Workflow:
        """Create from dictionary."""
        return Workflow(
            workflow_id=data["workflow_id"],
            name=data["name"],
            description=data["description"],
            steps={sid: StepConfig.from_dict(sc) for sid, sc in data["steps"].items()},
            entry_step=data["entry_step"],
            version=data.get("version", 1),
            metadata=data.get("metadata", {}),
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
        )

    def validate(self) -> None:
        """Validate workflow definition.

        Raises:
            WorkflowValidationError: If workflow is invalid
        """
        if not self.workflow_id or not self.workflow_id.strip():
            raise WorkflowValidationError("workflow_id cannot be empty")
        if not self.name or not self.name.strip():
            raise WorkflowValidationError("name cannot be empty")
        if not self.steps:
            raise WorkflowValidationError("workflow must have at least one step")
        if self.entry_step not in self.steps:
            raise WorkflowValidationError(f"entry_step '{self.entry_step}' not in steps")

        # Validate all step references
        for step_id, step in self.steps.items():
            for next_id in step.next_steps.values():
                if next_id not in self.steps:
                    raise WorkflowValidationError(f"Step '{step_id}' references unknown next step '{next_id}'")
            if step.all_next and step.all_next not in self.steps:
                raise WorkflowValidationError(f"Step '{step_id}' has unknown all_next '{step.all_next}'")


@dataclass
class StepResult:
    """Result of executing a single step.

    Attributes:
        step_id: ID of the executed step
        status: Execution status
        output: Step output (tool result, LLM response, etc.)
        error: Error message if failed
        error_action_taken: What action was taken on error
        retry_count: Number of retries performed
        duration_ms: Execution duration in milliseconds
        started_at: Start timestamp
        finished_at: End timestamp
        metadata: Additional execution metadata
    """

    step_id: str
    status: StepStatus
    output: dict[str, Any] | None = None
    error: str | None = None
    error_action_taken: str | None = None
    retry_count: int = 0
    duration_ms: int = 0
    started_at: str | None = None
    finished_at: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "step_id": self.step_id,
            "status": self.status.value,
            "output": self.output,
            "error": self.error,
            "error_action_taken": self.error_action_taken,
            "retry_count": self.retry_count,
            "duration_ms": self.duration_ms,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> StepResult:
        """Create from dictionary."""
        return StepResult(
            step_id=data["step_id"],
            status=StepStatus(data["status"]),
            output=data.get("output"),
            error=data.get("error"),
            error_action_taken=data.get("error_action_taken"),
            retry_count=data.get("retry_count", 0),
            duration_ms=data.get("duration_ms", 0),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class WorkflowRun:
    """Execution instance of a workflow.

    Tracks a single execution of a workflow from start to finish.
    State is persisted for resumption across restarts.

    Attributes:
        run_id: Unique run identifier
        workflow_id: ID of the workflow being executed
        status: Current execution status
        inputs: Input parameters to the workflow
        variables: Workflow variables (mutable state)
        current_step: ID of current step (when paused)
        executed_steps: History of executed steps
        step_results: Results of each step
        started_at: Start timestamp
        finished_at: End timestamp
        paused_at: Pause timestamp (when paused)
        error: Error message if failed
        metadata: Execution metadata
    """

    run_id: str
    workflow_id: str
    status: WorkflowStatus
    inputs: dict[str, Any]
    variables: dict[str, Any] = field(default_factory=dict)
    current_step: str | None = None
    executed_steps: list[str] = field(default_factory=list)
    step_results: dict[str, StepResult] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: str | None = None
    paused_at: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for persistence."""
        return {
            "run_id": self.run_id,
            "workflow_id": self.workflow_id,
            "status": self.status.value,
            "inputs": self.inputs,
            "variables": self.variables,
            "current_step": self.current_step,
            "executed_steps": self.executed_steps,
            "step_results": {sid: sr.to_dict() for sid, sr in self.step_results.items()},
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "paused_at": self.paused_at,
            "error": self.error,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> WorkflowRun:
        """Create from dictionary."""
        return WorkflowRun(
            run_id=data["run_id"],
            workflow_id=data["workflow_id"],
            status=WorkflowStatus(data["status"]),
            inputs=data["inputs"],
            variables=data.get("variables", {}),
            current_step=data.get("current_step"),
            executed_steps=data.get("executed_steps", []),
            step_results={sid: StepResult.from_dict(sr) for sid, sr in data.get("step_results", {}).items()},
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            paused_at=data.get("paused_at"),
            error=data.get("error"),
            metadata=data.get("metadata", {}),
        )


@dataclass
class TriggerConfig:
    """Configuration for workflow trigger.

    Attributes:
        trigger_type: Type of trigger (cron, event, webhook, file, manual)
        config: Trigger-specific configuration
        enabled: Whether trigger is active
        created_at: Creation timestamp
    """

    trigger_type: str
    config: dict[str, Any]
    enabled: bool = True
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "trigger_type": self.trigger_type,
            "config": self.config,
            "enabled": self.enabled,
            "created_at": self.created_at,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> TriggerConfig:
        """Create from dictionary."""
        return TriggerConfig(
            trigger_type=data["trigger_type"],
            config=data["config"],
            enabled=data.get("enabled", True),
            created_at=data.get("created_at"),
        )
