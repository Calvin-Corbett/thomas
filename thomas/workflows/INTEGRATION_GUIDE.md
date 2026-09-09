# Workflow Engine Integration Guide

This guide explains how to integrate the Workflow Automation Engine with Thomas's existing systems.

## Quick Start

### 1. Initialize in Application Startup

```python
# In thomas/server/app.py or similar
from thomas.workflows import WorkflowEngine
from thomas.workflows.persistence import WorkflowStore

# Create store (uses Thomas's database)
workflow_store = WorkflowStore()

# Create engine
workflow_engine = WorkflowEngine(
    store=workflow_store,
    max_concurrent_runs=10,
    event_publisher=event_bus.publish,  # Optional: integrate with event bus
)

# Make available globally
app.workflow_engine = workflow_engine
```

### 2. Register Workflow Tools

Connect to Thomas tool registry:

```python
# In thomas/workflows/steps.py ToolCallExecutor.execute()
from thomas.tools import get_tool_registry

registry = get_tool_registry()
tool = registry.get(tool_name)
result = await tool.execute(**params)
```

### 3. Integrate with Event Bus

Listen for events and trigger workflows:

```python
# In event bus setup
from thomas.event_bus import EventBus
from thomas.workflows import EventTrigger

bus = EventBus()

# When you want to start workflow on event
trigger = EventTrigger(
    trigger_id="event_trigger_1",
    workflow_id="my_workflow",
    event_type="my.event.type",
    input_mapping={"field": "event_field"},
)

# Subscribe trigger to event bus
async def on_event(event):
    await trigger.start(engine.start_workflow)

bus.subscribe(on_event, event_types={"my.event.type"})
```

### 4. Expose via API

```python
# In thomas/server/routes/workflows.py
from fastapi import APIRouter, HTTPException
from thomas.workflows import WorkflowEngine

router = APIRouter(prefix="/workflows", tags=["workflows"])

@router.post("/{workflow_id}/start")
async def start_workflow(workflow_id: str, inputs: dict = None):
    try:
        run_id = await engine.start_workflow(workflow_id, inputs)
        return {"run_id": run_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{run_id}/status")
async def get_status(run_id: str):
    status = await engine.get_status(run_id)
    return status

@router.post("/{run_id}/pause")
async def pause(run_id: str):
    await engine.pause_workflow(run_id)
    return {"status": "paused"}

@router.post("/{run_id}/resume")
async def resume(run_id: str):
    await engine.resume_workflow(run_id)
    return {"status": "resumed"}

@router.post("/{run_id}/cancel")
async def cancel(run_id: str):
    await engine.cancel_workflow(run_id)
    return {"status": "cancelled"}

@router.get("/")
async def list_workflows():
    return await engine.list_workflows()

@router.get("/runs")
async def list_runs(workflow_id: str = None, status: str = None):
    return await engine.list_runs(workflow_id, status)
```

### 5. Create Cron Triggers

Integrate with existing scheduler:

```python
# In thomas/core/scheduler.py integration
from thomas.workflows import CronTrigger

scheduler = get_scheduler()

# Define cron job that triggers workflow
def trigger_workflow(goal_text, channel):
    # goal_text contains workflow_id and inputs
    workflow_id, inputs = parse_goal_text(goal_text)
    asyncio.run(engine.start_workflow(workflow_id, inputs))

# Add scheduled tasks
scheduler.add_task(
    id="daily_standup",
    cron_expr="0 9 * * *",
    goal_text="daily_standup:{}",
    channel="workflows",
)
```

## Migration Setup

The Workflow Engine uses SQLite tables. If you want Alembic migration support:

```python
# In thomas/migrations/versions/001_workflow_init.py
"""Add workflow tables

Revision ID: 001
Revises:
Create Date: 2026-02-26

"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    op.create_table(
        'workflows',
        sa.Column('workflow_id', sa.String, primary_key=True),
        sa.Column('name', sa.String, nullable=False),
        sa.Column('description', sa.String),
        sa.Column('version', sa.Integer, default=1),
        sa.Column('definition', sa.String, nullable=False),
        sa.Column('metadata', sa.String),
        sa.Column('created_at', sa.String, nullable=False),
        sa.Column('updated_at', sa.String, nullable=False),
    )

    op.create_table(
        'workflow_runs',
        sa.Column('run_id', sa.String, primary_key=True),
        sa.Column('workflow_id', sa.String, sa.ForeignKey('workflows.workflow_id')),
        sa.Column('status', sa.String, nullable=False),
        sa.Column('inputs', sa.String, nullable=False),
        sa.Column('variables', sa.String),
        sa.Column('current_step', sa.String),
        sa.Column('executed_steps', sa.String),
        sa.Column('step_results', sa.String),
        sa.Column('started_at', sa.String, nullable=False),
        sa.Column('finished_at', sa.String),
        sa.Column('paused_at', sa.String),
        sa.Column('error', sa.String),
        sa.Column('metadata', sa.String),
        sa.Column('created_at', sa.String, default=sa.func.current_timestamp()),
    )

    op.create_index('idx_runs_workflow', 'workflow_runs', ['workflow_id'])
    op.create_index('idx_runs_status', 'workflow_runs', ['status'])

def downgrade():
    op.drop_index('idx_runs_status')
    op.drop_index('idx_runs_workflow')
    op.drop_table('workflow_runs')
    op.drop_table('workflows')
```

## Event Integration

Emit events for monitoring:

```python
# In thomas/core/events.py or event_bus

class WorkflowStarted(Event):
    def __init__(self, workflow_id: str, run_id: str):
        super().__init__('WorkflowStarted', f'workflow-{workflow_id}')
        self.workflow_id = workflow_id
        self.run_id = run_id

class WorkflowCompleted(Event):
    def __init__(self, workflow_id: str, run_id: str):
        super().__init__('WorkflowCompleted', f'workflow-{workflow_id}')
        self.workflow_id = workflow_id
        self.run_id = run_id

# In WorkflowEngine._emit()
event_types = {
    "workflow_started": WorkflowStarted,
    "workflow_completed": WorkflowCompleted,
    # ... etc
}
```

## Tool Registry Integration

Make Thomas tools available in workflows:

```python
# In thomas/tools/__init__.py
class ToolRegistry:
    def register_for_workflows(self):
        """Register tools for workflow execution"""
        # Tools are automatically available via tool_name in TOOL_CALL steps
        pass

# In ToolCallExecutor.execute()
from thomas.tools import get_registry
registry = get_registry()
tool = registry.get(tool_name)
result = await tool.execute(**params)
```

## Approval System Integration

Connect human approvals to Thomas approval system:

```python
# In ApprovalExecutor.execute()
from thomas.approvals import create_approval_request

approval = await create_approval_request(
    title=step_config.config.get("message"),
    context={"run_id": run.run_id, "step_id": step_config.step_id},
    timeout_seconds=step_config.config.get("timeout_seconds", 3600),
)

# Wait for approval
result = await approval.wait_for_decision(timeout=...)

return StepResult(
    step_id=step_config.step_id,
    status=StepStatus.COMPLETED if result.approved else StepStatus.FAILED,
    output={"approved": result.approved},
)
```

## Logging Integration

Integration with Thomas logging:

```python
# All modules use standard logging
import logging
logger = logging.getLogger(__name__)

# Configure in app startup
logging.getLogger("thomas.workflows").setLevel(logging.INFO)
```

## Testing

Example test setup:

```python
import pytest
from thomas.workflows import (
    WorkflowEngine,
    Workflow,
    StepConfig,
    StepType,
)
from thomas.workflows.persistence import WorkflowStore

@pytest.fixture
async def workflow_engine(tmp_path):
    store = WorkflowStore(db_path=tmp_path / "test.db")
    engine = WorkflowEngine(store)
    yield engine

@pytest.mark.asyncio
async def test_workflow_execution(workflow_engine):
    workflow = Workflow(
        workflow_id="test",
        name="Test",
        description="Test workflow",
        steps={
            "step1": StepConfig(
                step_id="step1",
                step_type=StepType.TOOL_CALL,
                config={"tool_name": "mock_tool"},
            ),
        },
        entry_step="step1",
    )

    await workflow_engine.register_workflow(workflow)
    run_id = await workflow_engine.start_workflow("test")

    # Wait for completion
    import asyncio
    await asyncio.sleep(1)

    status = await workflow_engine.get_status(run_id)
    assert status["status"] == "completed"
```

## Cleanup

Periodic cleanup of old runs:

```python
# In background task
async def cleanup_old_runs():
    from thomas.workflows.persistence import WorkflowStore

    store = WorkflowStore()
    deleted = await store.cleanup_old_runs(days=30)
    logger.info(f"Cleaned up {deleted} old workflow runs")

# Schedule with existing task scheduler
scheduler.add_task(
    id="workflow_cleanup",
    cron_expr="0 2 * * *",  # Daily at 2am
    goal_text="workflow_cleanup",
)
```

## Troubleshooting

### Workflow Won't Start
- Check workflow definition validity: `workflow.validate()`
- Verify workflow_id exists in database
- Check event_publisher callback for errors

### Steps Not Executing
- Verify step_type is supported
- Check tool/LLM availability
- Enable debug logging: `logging.getLogger("thomas.workflows").setLevel(logging.DEBUG)`

### State Not Persisting
- Verify SQLite database is writable
- Check migrations have run
- Ensure WorkflowStore is using correct database path

### Triggers Not Firing
- For CronTrigger: validate cron expression
- For EventTrigger: verify event_bus integration
- For FileTrigger: check watch_path permissions
- Enable trigger logging

## Performance Tuning

- **Concurrency**: Adjust `max_concurrent_runs` based on system capacity
- **Database**: Consider connection pooling for high volume
- **Cleanup**: Run cleanup task during low traffic periods
- **Event Publishing**: Async event publishing to avoid blocking
