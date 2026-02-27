"""
Thomas Workflow Automation Engine

A comprehensive workflow automation system for Thomas with support for:
- Workflow definition and registration
- Sequential and parallel execution
- Conditional branching and loops
- State persistence and resumption
- Multiple trigger types (cron, event, webhook, file, manual)
- Human approval gates and async steps
- Comprehensive error handling with retry logic

Basic Usage:

    from thomas.workflows import WorkflowEngine, Workflow, StepConfig, StepType
    from thomas.workflows.persistence import WorkflowStore
    from thomas.workflows.triggers import CronTrigger

    # Create engine
    store = WorkflowStore()
    engine = WorkflowEngine(store)

    # Define workflow
    workflow = Workflow(
        workflow_id="my_workflow",
        name="My Workflow",
        description="My first workflow",
        steps={
            "step1": StepConfig(
                step_id="step1",
                step_type=StepType.TOOL_CALL,
                config={"tool_name": "my_tool"},
                all_next="step2",
            ),
            "step2": StepConfig(
                step_id="step2",
                step_type=StepType.TOOL_CALL,
                config={"tool_name": "my_tool2"},
            ),
        },
        entry_step="step1",
    )

    # Register and start
    await engine.register_workflow(workflow)
    run_id = await engine.start_workflow("my_workflow", {"input": "value"})

    # Monitor
    status = await engine.get_status(run_id)

    # Control execution
    await engine.pause_workflow(run_id)
    await engine.resume_workflow(run_id)
    await engine.cancel_workflow(run_id)

Components:

- WorkflowEngine: Main execution orchestrator
- Workflow: Immutable workflow definition
- StepConfig: Individual step configuration
- WorkflowRun: Execution instance with state
- WorkflowStore: Persistent storage
- StepExecutor: Executes different step types
- Triggers: Automatic workflow activation

Step Types:

- TOOL_CALL: Execute Thomas tools
- LLM_PROMPT: Send prompt to language model
- CONDITION: Conditional branching
- LOOP: Iteration over items
- PARALLEL: Concurrent step execution
- WAIT: Delay or condition wait
- APPROVAL: Human approval gate
- WEBHOOK: External HTTP call

Triggers:

- CronTrigger: Schedule-based (cron expressions)
- EventTrigger: Event bus integration
- WebhookTrigger: HTTP endpoints
- FileTrigger: File system changes
- ManualTrigger: User-initiated

Error Handling:

- RETRY: Retry step with exponential backoff
- SKIP: Skip to next step
- ABORT: Cancel workflow execution

State Persistence:

All workflow state is persisted to SQLite for:
- Resumption after server restart
- Audit and compliance
- Historical analysis
"""

from .engine import WorkflowEngine
from .models import (
    ErrorAction,
    StepConfig,
    StepResult,
    StepStatus,
    StepType,
    TriggerConfig,
    Workflow,
    WorkflowError,
    WorkflowExecutionError,
    WorkflowNotFoundError,
    WorkflowPersistenceError,
    WorkflowRun,
    WorkflowStatus,
    WorkflowValidationError,
)
from .persistence import WorkflowStore
from .steps import StepExecutor
from .templates import (
    create_daily_standup_workflow,
    create_data_pipeline_workflow,
    create_file_processor_workflow,
    create_incident_response_workflow,
    create_pr_review_workflow,
)
from .triggers import (
    CronTrigger,
    EventTrigger,
    FileTrigger,
    ManualTrigger,
    WebhookTrigger,
    WorkflowTrigger,
)

__all__ = [
    # Engine
    "WorkflowEngine",
    # Models
    "Workflow",
    "StepConfig",
    "WorkflowRun",
    "StepResult",
    "TriggerConfig",
    "StepType",
    "StepStatus",
    "WorkflowStatus",
    "ErrorAction",
    # Exceptions
    "WorkflowError",
    "WorkflowNotFoundError",
    "WorkflowExecutionError",
    "WorkflowPersistenceError",
    "WorkflowValidationError",
    # Storage
    "WorkflowStore",
    # Execution
    "StepExecutor",
    # Triggers
    "WorkflowTrigger",
    "CronTrigger",
    "EventTrigger",
    "WebhookTrigger",
    "FileTrigger",
    "ManualTrigger",
    # Templates
    "create_daily_standup_workflow",
    "create_file_processor_workflow",
    "create_pr_review_workflow",
    "create_incident_response_workflow",
    "create_data_pipeline_workflow",
]

__version__ = "1.0.0"
