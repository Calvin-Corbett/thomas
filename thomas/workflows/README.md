# Thomas Workflow Automation Engine

A comprehensive workflow automation system for Thomas that enables building, executing, and managing complex automation scenarios.

## Overview

The Workflow Engine provides:

- **Workflow Definition**: Declarative workflow definitions with version control
- **Execution Engine**: Async execution with pause/resume capability
- **State Persistence**: SQLite-based state management for resumption across restarts
- **Step Types**: Multiple step types (tools, LLM, conditions, loops, parallel, approval)
- **Trigger System**: Multiple activation mechanisms (cron, events, webhooks, files, manual)
- **Error Handling**: Retry logic, conditional branching, human approval gates
- **Event Integration**: Integration with Thomas event bus for async workflows

## Architecture

### Core Components

```
WorkflowEngine
├── WorkflowStore (SQLite persistence)
├── StepExecutor (executes step types)
└── Triggers (activation mechanisms)

Workflow
├── StepConfig[] (workflow steps)
└── TriggerConfig[] (activation triggers)

WorkflowRun
├── StepResult[] (execution history)
└── Variables (workflow state)
```

### Execution Flow

```
1. Start Workflow
   ├── Load workflow definition
   └── Create execution instance

2. Execute Steps
   ├── Load current step
   ├── Execute with retry
   ├── Persist state
   └── Determine next step

3. Handle Branching
   ├── Evaluate conditions
   ├── Determine outcome-based next step
   └── Continue execution

4. Completion
   ├── Mark as completed/failed
   └── Persist final state
```

## Usage Examples

### Basic Workflow

```python
from thomas.workflows import (
    WorkflowEngine,
    Workflow,
    StepConfig,
    StepType,
    ErrorAction,
)
from thomas.workflows.persistence import WorkflowStore

# Create engine
store = WorkflowStore()
engine = WorkflowEngine(store)

# Define workflow
workflow = Workflow(
    workflow_id="hello_world",
    name="Hello World",
    description="Simple hello world workflow",
    steps={
        "greet": StepConfig(
            step_id="greet",
            step_type=StepType.TOOL_CALL,
            config={
                "tool_name": "logging",
                "tool_params": {
                    "level": "info",
                    "message": "Hello, World!",
                },
            },
            error_action=ErrorAction.ABORT,
        ),
    },
    entry_step="greet",
)

# Register and execute
await engine.register_workflow(workflow)
run_id = await engine.start_workflow("hello_world")

# Monitor execution
status = await engine.get_status(run_id)
print(f"Status: {status['status']}")
```

### Workflow with Branching

```python
workflow = Workflow(
    workflow_id="conditional_workflow",
    name="Conditional Workflow",
    description="Workflow with conditional branching",
    steps={
        "check_time": StepConfig(
            step_id="check_time",
            step_type=StepType.CONDITION,
            config={
                "condition": "${hour} >= 9 and ${hour} < 17",
            },
            next_steps={
                "success": "work_hours_action",
                "failure": "off_hours_action",
            },
        ),
        "work_hours_action": StepConfig(
            step_id="work_hours_action",
            step_type=StepType.TOOL_CALL,
            config={"tool_name": "notify_team"},
        ),
        "off_hours_action": StepConfig(
            step_id="off_hours_action",
            step_type=StepType.TOOL_CALL,
            config={"tool_name": "schedule_tomorrow"},
        ),
    },
    entry_step="check_time",
)
```

### Workflow with Loop

```python
workflow = Workflow(
    workflow_id="batch_processor",
    name="Batch Processor",
    description="Process multiple items",
    steps={
        "process_items": StepConfig(
            step_id="process_items",
            step_type=StepType.LOOP,
            config={
                "items": "${input_items}",
                "item_var": "current_item",
            },
            all_next="notify_completion",
        ),
        "notify_completion": StepConfig(
            step_id="notify_completion",
            step_type=StepType.TOOL_CALL,
            config={"tool_name": "send_notification"},
        ),
    },
    entry_step="process_items",
)
```

### Using Pre-built Templates

```python
from thomas.workflows.templates import (
    create_daily_standup_workflow,
    create_file_processor_workflow,
    create_incident_response_workflow,
)

# Daily standup
standup = create_daily_standup_workflow()
await engine.register_workflow(standup)
await engine.start_workflow("daily_standup")

# File processor
file_proc = create_file_processor_workflow()
await engine.register_workflow(file_proc)

# Incident response
incident = create_incident_response_workflow()
await engine.register_workflow(incident)
```

### Using Triggers

```python
from thomas.workflows.triggers import (
    CronTrigger,
    EventTrigger,
    WebhookTrigger,
    FileTrigger,
    ManualTrigger,
)

# Cron trigger (daily at 9am)
cron_trigger = CronTrigger(
    trigger_id="daily_standup_trigger",
    workflow_id="daily_standup",
    cron_expr="0 9 * * *",
    inputs={"team": "engineering"},
)

# Event trigger
event_trigger = EventTrigger(
    trigger_id="pr_review_trigger",
    workflow_id="pr_review",
    event_type="github.pull_request.opened",
    input_mapping={
        "pr_number": "number",
        "repo": "repository",
    },
)

# Webhook trigger
webhook_trigger = WebhookTrigger(
    trigger_id="deployment_trigger",
    workflow_id="deployment",
    path="/webhooks/deploy",
    secret="my-secret-key",
)

# File trigger
file_trigger = FileTrigger(
    trigger_id="csv_processor",
    workflow_id="file_processor",
    watch_path="/data/inbox",
    pattern="*.csv",
    events=["created", "modified"],
)

# Manual trigger
manual = ManualTrigger(
    trigger_id="manual_sync",
    workflow_id="sync_data",
)
await manual.trigger({"sync_type": "full"})
```

## Step Types

### TOOL_CALL

Execute a Thomas tool with parameters.

```python
StepConfig(
    step_id="call_tool",
    step_type=StepType.TOOL_CALL,
    config={
        "tool_name": "my_tool",
        "tool_params": {
            "param1": "value1",
            "param2": "${variable_ref}",
        },
    },
)
```

### LLM_PROMPT

Send a prompt to a language model.

```python
StepConfig(
    step_id="analyze",
    step_type=StepType.LLM_PROMPT,
    config={
        "prompt": "Analyze this: ${data}",
        "model": "gpt-4",
        "temperature": 0.7,
    },
)
```

### CONDITION

Conditional branching based on expressions.

```python
StepConfig(
    step_id="check",
    step_type=StepType.CONDITION,
    config={
        "condition": "${status} == 'active'",
    },
    next_steps={
        "success": "active_path",
        "failure": "inactive_path",
    },
)
```

### LOOP

Iterate over items.

```python
StepConfig(
    step_id="iterate",
    step_type=StepType.LOOP,
    config={
        "items": "${list_var}",
        "item_var": "current_item",
    },
)
```

### PARALLEL

Execute multiple steps concurrently.

```python
StepConfig(
    step_id="parallel",
    step_type=StepType.PARALLEL,
    config={
        "steps": ["step_a", "step_b", "step_c"],
    },
)
```

### WAIT

Pause execution for duration or until condition.

```python
StepConfig(
    step_id="wait",
    step_type=StepType.WAIT,
    config={
        "duration_seconds": 300,
        "until_condition": "condition_met",
    },
)
```

### APPROVAL

Human approval gate.

```python
StepConfig(
    step_id="approval",
    step_type=StepType.APPROVAL,
    config={
        "message": "Approve deployment?",
        "timeout_seconds": 3600,
    },
)
```

### WEBHOOK

Call external HTTP endpoint.

```python
StepConfig(
    step_id="webhook",
    step_type=StepType.WEBHOOK,
    config={
        "url": "https://example.com/webhook",
        "method": "POST",
        "body": {"key": "${value}"},
        "headers": {"Authorization": "Bearer token"},
    },
)
```

## Error Handling

### Retry Logic

```python
StepConfig(
    step_id="flaky_step",
    step_type=StepType.TOOL_CALL,
    config={"tool_name": "my_tool"},
    error_action=ErrorAction.RETRY,
    max_retries=3,
)
```

Retries use exponential backoff: 2^n seconds (max 30 seconds).

### Error Actions

- **RETRY**: Retry step up to max_retries times
- **SKIP**: Skip to next step on error
- **ABORT**: Cancel workflow execution

```python
StepConfig(
    step_id="optional_step",
    error_action=ErrorAction.SKIP,
    all_next="next_step",
)
```

## Workflow Control

### Pause/Resume

```python
# Pause running workflow
await engine.pause_workflow(run_id)

# Resume paused workflow
await engine.resume_workflow(run_id)
```

Workflow pauses after current step completes.

### Cancel

```python
# Cancel workflow
await engine.cancel_workflow(run_id)
```

### Monitor Status

```python
status = await engine.get_status(run_id)
print(f"Status: {status['status']}")
print(f"Current step: {status['current_step']}")
print(f"Progress: {status['progress']}")
```

## Variable Substitution

Variables referenced as `${var_name}` are replaced with values from workflow variables:

```python
# In step config
config={
    "message": "Hello ${name}!",
    "count": "${item_count}",
}

# Variables are populated from:
# 1. Workflow inputs
# 2. Previous step outputs
# 3. Loop variables
# 4. System variables (e.g., ${__loop_index__})
```

## Database Schema

Tables automatically created in SQLite:

### workflows
- workflow_id (PK)
- name
- description
- version
- definition (JSON)
- metadata (JSON)
- created_at, updated_at

### workflow_runs
- run_id (PK)
- workflow_id (FK)
- status
- inputs (JSON)
- variables (JSON)
- current_step
- executed_steps (JSON)
- step_results (JSON)
- started_at, finished_at, paused_at
- error
- metadata (JSON)

Indexes on workflow_id and status for efficient queries.

## Pre-built Templates

### Daily Standup
Gathers team updates, summarizes with LLM, posts to Slack.

### File Processor
Watches directory, validates, processes, and stores file data.

### PR Review
Triggered on GitHub PR, analyzes code, posts review.

### Incident Response
On alert, gathers logs, analyzes, notifies team, requests approval.

### Data Pipeline
ETL workflow: extract, transform, load with error handling.

## Integration Points

### Event Bus

Workflows emit events for integration:

```python
engine = WorkflowEngine(
    store,
    event_publisher=async_event_bus.publish,
)

# Events emitted:
# - workflow_registered
# - workflow_started
# - workflow_paused
# - workflow_resumed
# - workflow_cancelled
# - workflow_completed
# - workflow_failed
# - step_skipped
```

### Tool Registry

Steps execute tools from Thomas tool registry:

```python
# In step executor
result = await tool_registry.call(
    tool_name,
    parameters=substituted_params,
)
```

## Best Practices

1. **Idempotency**: Design steps to be idempotent for safety on retry
2. **Timeouts**: Set timeouts on steps that could hang
3. **Error Action**: Use SKIP for non-critical steps, ABORT for critical ones
4. **Monitoring**: Listen to workflow events for monitoring/alerting
5. **Testing**: Test workflows with dry-run triggers before production
6. **Documentation**: Document complex workflows with step descriptions
7. **Versioning**: Increment workflow version when making breaking changes

## Limitations

- Maximum workflow definition size: 10MB
- Maximum concurrent runs: Configurable (default 10)
- Step execution timeout: None (set per-step)
- Maximum step history: Unlimited (consider cleanup periodically)
- Parallel steps: Use shared variables cautiously (no locking)

## Future Enhancements

- Distributed execution across multiple workers
- Built-in approval UI
- Workflow versioning and rollback
- Template marketplace
- Advanced scheduling (including complex recurrence)
- Dynamic step generation
- Workflow composition (sub-workflows)
- Comprehensive audit logging
