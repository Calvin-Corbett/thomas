"""
Workflow automation engine for the CRM.
"""

import uuid
from collections.abc import Callable
from datetime import datetime
from enum import Enum
from typing import Any

from thomas.marketplace.crm._exceptions import WorkflowError


class TriggerType(str, Enum):
    """Types of workflow triggers."""

    DEAL_STAGE_CHANGED = "deal_stage_changed"
    ACTIVITY_LOGGED = "activity_logged"
    SCORE_THRESHOLD_CROSSED = "score_threshold_crossed"
    TIME_BASED = "time_based"
    CONTACT_CREATED = "contact_created"
    DEAL_CREATED = "deal_created"


class ActionType(str, Enum):
    """Types of workflow actions."""

    CREATE_TASK = "create_task"
    SEND_NOTIFICATION = "send_notification"
    UPDATE_FIELD = "update_field"
    MOVE_STAGE = "move_stage"
    ADD_TAG = "add_tag"
    SEND_EMAIL = "send_email"


class WorkflowEngine:
    """Manages CRM workflow automation.

    Handles workflow rule creation, trigger evaluation, action execution,
    and workflow history tracking.
    """

    def __init__(self) -> None:
        """Initialize the workflow engine."""
        self._workflows: dict[str, dict[str, Any]] = {}
        self._workflow_history: list[dict[str, Any]] = []
        self._action_handlers: dict[ActionType, Callable] = {}

    def register_action_handler(
        self,
        action_type: ActionType,
        handler: Callable,
    ) -> None:
        """Register a handler for an action type.

        Args:
            action_type: Type of action
            handler: Callable that executes the action
        """
        self._action_handlers[action_type] = handler

    def create_workflow(
        self,
        name: str,
        trigger_type: TriggerType,
        trigger_config: dict[str, Any],
        conditions: list[dict[str, Any]] | None = None,
        actions: list[dict[str, Any]] | None = None,
    ) -> str:
        """Create a new workflow rule.

        Args:
            name: Workflow name
            trigger_type: Type of trigger
            trigger_config: Trigger configuration
            conditions: Optional list of conditions
            actions: List of actions to execute

        Returns:
            Workflow ID
        """
        workflow_id = str(uuid.uuid4())

        workflow = {
            "id": workflow_id,
            "name": name,
            "trigger_type": trigger_type.value,
            "trigger_config": trigger_config,
            "conditions": conditions or [],
            "actions": actions or [],
            "created_at": datetime.utcnow().isoformat(),
            "enabled": True,
        }

        self._workflows[workflow_id] = workflow
        return workflow_id

    def get_workflow(self, workflow_id: str) -> dict[str, Any] | None:
        """Get a workflow by ID.

        Args:
            workflow_id: Workflow ID

        Returns:
            Workflow dictionary or None
        """
        return self._workflows.get(workflow_id)

    def list_workflows(self) -> list[dict[str, Any]]:
        """Get all workflows.

        Returns:
            List of workflow dictionaries
        """
        return list(self._workflows.values())

    def update_workflow(
        self,
        workflow_id: str,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Update a workflow.

        Args:
            workflow_id: Workflow ID
            **kwargs: Fields to update

        Returns:
            Updated workflow or None
        """
        workflow = self.get_workflow(workflow_id)

        if not workflow:
            return None

        for key, value in kwargs.items():
            if key in workflow:
                workflow[key] = value

        return workflow

    def delete_workflow(self, workflow_id: str) -> None:
        """Delete a workflow.

        Args:
            workflow_id: Workflow ID
        """
        if workflow_id in self._workflows:
            del self._workflows[workflow_id]

    def evaluate_trigger(
        self,
        trigger_type: TriggerType,
        trigger_data: dict[str, Any],
    ) -> list[str]:
        """Find workflows matching a trigger.

        Args:
            trigger_type: Type of trigger
            trigger_data: Trigger data

        Returns:
            List of matching workflow IDs
        """
        matching_workflows = []

        for workflow_id, workflow in self._workflows.items():
            if not workflow["enabled"]:
                continue

            if TriggerType(workflow["trigger_type"]) != trigger_type:
                continue

            # Check trigger configuration match
            config = workflow["trigger_config"]

            if trigger_type == TriggerType.DEAL_STAGE_CHANGED:
                if "from_stage" in config and "to_stage" in config:
                    if (
                        trigger_data.get("from_stage") == config["from_stage"]
                        and trigger_data.get("to_stage") == config["to_stage"]
                    ):
                        matching_workflows.append(workflow_id)

            elif trigger_type == TriggerType.ACTIVITY_LOGGED:
                if "activity_type" in config:
                    if trigger_data.get("activity_type") == config["activity_type"]:
                        matching_workflows.append(workflow_id)

            elif trigger_type == TriggerType.SCORE_THRESHOLD_CROSSED:
                score = trigger_data.get("score", 0)
                threshold = config.get("threshold", 0)

                if config.get("direction") == "above":
                    if score >= threshold:
                        matching_workflows.append(workflow_id)
                elif config.get("direction") == "below":
                    if score < threshold:
                        matching_workflows.append(workflow_id)

            elif trigger_type in (
                TriggerType.CONTACT_CREATED,
                TriggerType.DEAL_CREATED,
            ):
                # These triggers always match
                matching_workflows.append(workflow_id)

        return matching_workflows

    def evaluate_conditions(
        self,
        conditions: list[dict[str, Any]],
        context: dict[str, Any],
    ) -> bool:
        """Evaluate workflow conditions.

        Args:
            conditions: List of condition dictionaries
            context: Context data for evaluation

        Returns:
            True if all conditions are met
        """
        if not conditions:
            return True

        for condition in conditions:
            field = condition.get("field")
            operator = condition.get("operator")
            value = condition.get("value")

            context_value = context.get(field)

            if operator == "equals":
                if context_value != value:
                    return False
            elif operator == "not_equals":
                if context_value == value:
                    return False
            elif operator == "greater_than":
                if not (context_value > value):
                    return False
            elif operator == "less_than":
                if not (context_value < value):
                    return False
            elif operator == "contains":
                if value not in str(context_value):
                    return False
            elif operator == "not_contains":
                if value in str(context_value):
                    return False

        return True

    def execute_workflow(
        self,
        workflow_id: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a workflow.

        Args:
            workflow_id: Workflow ID
            context: Execution context

        Returns:
            Execution result dictionary

        Raises:
            WorkflowError: If workflow execution fails
        """
        workflow = self.get_workflow(workflow_id)

        if not workflow:
            raise WorkflowError(f"Workflow {workflow_id} not found")

        if not workflow["enabled"]:
            raise WorkflowError(f"Workflow {workflow_id} is disabled")

        # Evaluate conditions
        if not self.evaluate_conditions(workflow["conditions"], context):
            return {
                "workflow_id": workflow_id,
                "status": "skipped",
                "reason": "Conditions not met",
            }

        # Execute actions
        execution_result = {
            "workflow_id": workflow_id,
            "status": "executed",
            "actions_executed": [],
            "errors": [],
        }

        for action in workflow["actions"]:
            try:
                result = self._execute_action(action, context)
                execution_result["actions_executed"].append(
                    {
                        "type": action.get("type"),
                        "result": result,
                    }
                )
            except Exception as e:
                execution_result["errors"].append(
                    {
                        "action_type": action.get("type"),
                        "error": str(e),
                    }
                )

        # Record in history
        self._record_execution(workflow_id, execution_result, context)

        return execution_result

    def _execute_action(
        self,
        action: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a single action.

        Args:
            action: Action configuration
            context: Execution context

        Returns:
            Action result dictionary

        Raises:
            WorkflowError: If action execution fails
        """
        action_type_str = action.get("type")

        try:
            action_type = ActionType(action_type_str)
        except ValueError:
            raise WorkflowError(f"Unknown action type: {action_type_str}")

        # Use registered handler if available
        if action_type in self._action_handlers:
            return self._action_handlers[action_type](action, context)

        # Default action implementations
        if action_type == ActionType.CREATE_TASK:
            return {
                "type": "create_task",
                "task_name": action.get("task_name"),
                "assigned_to": action.get("assigned_to"),
                "due_date": action.get("due_date"),
            }

        elif action_type == ActionType.SEND_NOTIFICATION:
            return {
                "type": "send_notification",
                "recipient": action.get("recipient"),
                "message": action.get("message"),
            }

        elif action_type == ActionType.UPDATE_FIELD:
            return {
                "type": "update_field",
                "field": action.get("field"),
                "value": action.get("value"),
            }

        elif action_type == ActionType.MOVE_STAGE:
            return {
                "type": "move_stage",
                "stage_id": action.get("stage_id"),
                "deal_id": context.get("deal_id"),
            }

        elif action_type == ActionType.ADD_TAG:
            return {
                "type": "add_tag",
                "tag": action.get("tag"),
                "contact_id": context.get("contact_id"),
            }

        elif action_type == ActionType.SEND_EMAIL:
            return {
                "type": "send_email",
                "to": action.get("to"),
                "subject": action.get("subject"),
                "template": action.get("template"),
            }

        else:
            raise WorkflowError(f"Unsupported action type: {action_type}")

    def _record_execution(
        self,
        workflow_id: str,
        result: dict[str, Any],
        context: dict[str, Any],
    ) -> None:
        """Record a workflow execution in history.

        Args:
            workflow_id: Workflow ID
            result: Execution result
            context: Execution context
        """
        history_entry = {
            "workflow_id": workflow_id,
            "executed_at": datetime.utcnow().isoformat(),
            "status": result.get("status"),
            "actions_executed": len(result.get("actions_executed", [])),
            "errors": len(result.get("errors", [])),
            "context_keys": list(context.keys()),
        }

        self._workflow_history.append(history_entry)

        # Keep history size manageable
        if len(self._workflow_history) > 10000:
            self._workflow_history = self._workflow_history[-10000:]

    def get_workflow_history(
        self,
        workflow_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get workflow execution history.

        Args:
            workflow_id: Optional workflow ID to filter by
            limit: Maximum number of entries to return

        Returns:
            List of history entries
        """
        history = self._workflow_history

        if workflow_id:
            history = [h for h in history if h["workflow_id"] == workflow_id]

        return sorted(history, key=lambda h: h["executed_at"], reverse=True)[:limit]

    def create_template_workflow(
        self,
        template_name: str,
    ) -> str:
        """Create a workflow from a template.

        Templates are pre-configured common workflows.

        Args:
            template_name: Name of the template

        Returns:
            Workflow ID
        """
        templates = {
            "lead_qualified": {
                "name": "Lead Qualified - Create Task",
                "trigger_type": TriggerType.SCORE_THRESHOLD_CROSSED,
                "trigger_config": {
                    "threshold": 80,
                    "direction": "above",
                },
                "conditions": [],
                "actions": [
                    {
                        "type": ActionType.CREATE_TASK.value,
                        "task_name": "Follow up with qualified lead",
                        "assigned_to": "{{ sales_rep }}",
                        "due_date": "{{ today + 1 }}",
                    }
                ],
            },
            "deal_won": {
                "name": "Deal Won - Send Notification",
                "trigger_type": TriggerType.DEAL_STAGE_CHANGED,
                "trigger_config": {
                    "to_stage": "won",
                },
                "conditions": [],
                "actions": [
                    {
                        "type": ActionType.SEND_NOTIFICATION.value,
                        "recipient": "{{ deal.owner }}",
                        "message": "Congratulations! Deal {{ deal.name }} has been won.",
                    }
                ],
            },
        }

        if template_name not in templates:
            raise WorkflowError(f"Unknown template: {template_name}")

        template = templates[template_name]

        return self.create_workflow(
            name=template["name"],
            trigger_type=TriggerType(template["trigger_type"]),
            trigger_config=template["trigger_config"],
            conditions=template["conditions"],
            actions=template["actions"],
        )

    def get_workflow_performance(self) -> dict[str, Any]:
        """Get workflow engine performance statistics.

        Returns:
            Performance statistics
        """
        history = self._workflow_history

        total_executions = len(history)
        successful = len([h for h in history if h["status"] == "executed"])
        skipped = len([h for h in history if h["status"] == "skipped"])
        with_errors = len([h for h in history if h["errors"] > 0])

        return {
            "total_executions": total_executions,
            "successful": successful,
            "skipped": skipped,
            "with_errors": with_errors,
            "total_actions_executed": sum(h["actions_executed"] for h in history),
            "success_rate": (successful / total_executions * 100 if total_executions > 0 else 0),
        }
