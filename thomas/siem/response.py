"""Automated incident response engine.

Implements SOAR-like playbooks, automated response actions, approval workflows,
and integration points for automated remediation.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from thomas.siem._exceptions import (
    PlaybookException,
    ResponseException,
)
from thomas.siem._types import (
    EventSeverity,
    Incident,
)


class ActionType(Enum):
    """Types of automated response actions."""

    BLOCK_IP = "block_ip"
    UNBLOCK_IP = "unblock_ip"
    DISABLE_USER = "disable_user"
    ENABLE_USER = "enable_user"
    ISOLATE_HOST = "isolate_host"
    QUARANTINE_FILE = "quarantine_file"
    RESET_PASSWORD = "reset_password"
    SEND_ALERT = "send_alert"
    CREATE_TICKET = "create_ticket"
    TERMINATE_SESSION = "terminate_session"


class ApprovalStatus(Enum):
    """Approval status for response actions."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


@dataclass
class ResponseAction:
    """Single response action to execute."""

    action_id: str = field(default_factory=lambda: str(uuid4()))
    action_type: ActionType = ActionType.BLOCK_IP
    target: str = ""
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=datetime.utcnow)
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approved_by: str | None = None
    executed: bool = False
    execution_result: dict[str, Any] | None = None
    required_approval: bool = False
    auto_approve: bool = False


@dataclass
class PlaybookCondition:
    """Condition that triggers playbook execution."""

    condition_type: str  # severity, category, event_count
    operator: str  # >=, >, ==, <=, <, in
    value: Any
    description: str = ""

    def evaluate(self, incident: Incident) -> bool:
        """Evaluate condition against incident.

        Args:
            incident: Incident to evaluate.

        Returns:
            True if condition is met.
        """
        if self.condition_type == "severity":
            severity_value = incident.severity.value
            if self.operator == ">=":
                return severity_value >= self.value
            elif self.operator == ">":
                return severity_value > self.value
            elif self.operator == "==":
                return severity_value == self.value
        elif self.condition_type == "status":
            if self.operator == "==":
                return incident.status == self.value
        return False


@dataclass
class Playbook:
    """Incident response playbook."""

    playbook_id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    enabled: bool = True
    conditions: list[PlaybookCondition] = field(default_factory=list)
    actions: list[ResponseAction] = field(default_factory=list)
    approval_required: bool = False
    execution_count: int = 0
    last_executed: datetime | None = None


class ActionExecutor:
    """Executes response actions."""

    def __init__(self):
        """Initialize action executor."""
        self.execution_history: list[dict[str, Any]] = []
        self.integrations: dict[str, Callable] = {}

    def register_integration(self, action_type: ActionType, handler: Callable) -> None:
        """Register integration handler for action type.

        Args:
            action_type: Action type to handle.
            handler: Callable handler function.
        """
        self.integrations[action_type.value] = handler

    def execute_action(self, action: ResponseAction, dry_run: bool = False) -> dict[str, Any]:
        """Execute response action.

        Args:
            action: Action to execute.
            dry_run: If True, simulate without actual execution.

        Returns:
            Execution result.

        Raises:
            ResponseException: If execution fails.
        """
        if not action.approved_by and action.required_approval:
            return {
                "success": False,
                "error": "Action requires approval",
                "action_id": action.action_id,
            }

        try:
            handler = self.integrations.get(action.action_type.value)

            if handler and not dry_run:
                result = handler(action.target, action.parameters)
            else:
                # Simulate execution
                result = self._simulate_action(action)

            action.executed = True
            action.execution_result = result

            self.execution_history.append(
                {
                    "action_id": action.action_id,
                    "action_type": action.action_type.value,
                    "target": action.target,
                    "timestamp": datetime.utcnow(),
                    "result": result,
                    "dry_run": dry_run,
                }
            )

            return result

        except Exception as e:
            raise ResponseException(f"Action execution failed: {e}")

    def _simulate_action(self, action: ResponseAction) -> dict[str, Any]:
        """Simulate action execution.

        Args:
            action: Action to simulate.

        Returns:
            Simulated result.
        """
        return {
            "success": True,
            "action_type": action.action_type.value,
            "target": action.target,
            "message": f"Simulated execution of {action.action_type.value}",
            "timestamp": datetime.utcnow().isoformat(),
        }

    def get_execution_history(self, action_type: ActionType | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Get action execution history.

        Args:
            action_type: Filter by action type.
            limit: Maximum results.

        Returns:
            Execution history.
        """
        history = self.execution_history

        if action_type:
            history = [h for h in history if h["action_type"] == action_type.value]

        return history[-limit:]


class ApprovalWorkflow:
    """Manages approval workflows for sensitive actions."""

    def __init__(self, auto_approve_threshold: EventSeverity = EventSeverity.LOW):
        """Initialize approval workflow.

        Args:
            auto_approve_threshold: Severity level for auto-approval.
        """
        self.auto_approve_threshold = auto_approve_threshold
        self.pending_approvals: dict[str, ResponseAction] = {}
        self.approval_history: list[dict[str, Any]] = []

    def submit_for_approval(self, action: ResponseAction) -> str:
        """Submit action for approval.

        Args:
            action: Action to approve.

        Returns:
            Approval request ID.
        """
        action.approval_status = ApprovalStatus.PENDING
        self.pending_approvals[action.action_id] = action
        return action.action_id

    def approve_action(self, action_id: str, approved_by: str) -> bool:
        """Approve action.

        Args:
            action_id: Action to approve.
            approved_by: Approver name.

        Returns:
            True if approved.
        """
        if action_id not in self.pending_approvals:
            return False

        action = self.pending_approvals[action_id]
        action.approval_status = ApprovalStatus.APPROVED
        action.approved_by = approved_by
        del self.pending_approvals[action_id]

        self.approval_history.append(
            {
                "action_id": action_id,
                "approved_by": approved_by,
                "timestamp": datetime.utcnow(),
                "action_type": action.action_type.value,
            }
        )

        return True

    def reject_action(self, action_id: str, rejected_by: str, reason: str) -> bool:
        """Reject action.

        Args:
            action_id: Action to reject.
            rejected_by: Rejector name.
            reason: Rejection reason.

        Returns:
            True if rejected.
        """
        if action_id not in self.pending_approvals:
            return False

        action = self.pending_approvals[action_id]
        action.approval_status = ApprovalStatus.REJECTED
        del self.pending_approvals[action_id]

        self.approval_history.append(
            {
                "action_id": action_id,
                "rejected_by": rejected_by,
                "reason": reason,
                "timestamp": datetime.utcnow(),
            }
        )

        return True

    def get_pending_approvals(self) -> list[ResponseAction]:
        """Get actions pending approval.

        Returns:
            List of pending actions.
        """
        return list(self.pending_approvals.values())

    def get_approval_status(self, action_id: str) -> dict[str, Any] | None:
        """Get approval status for action.

        Args:
            action_id: Action identifier.

        Returns:
            Status information or None.
        """
        for record in self.approval_history:
            if record["action_id"] == action_id:
                return record

        if action_id in self.pending_approvals:
            return {
                "action_id": action_id,
                "status": "pending",
                "timestamp": datetime.utcnow(),
            }

        return None


class PlaybookEngine:
    """Executes incident response playbooks."""

    def __init__(self):
        """Initialize playbook engine."""
        self.playbooks: dict[str, Playbook] = {}
        self.executor = ActionExecutor()
        self.approval_workflow = ApprovalWorkflow()

    def add_playbook(self, playbook: Playbook) -> None:
        """Add playbook.

        Args:
            playbook: Playbook to add.
        """
        self.playbooks[playbook.playbook_id] = playbook

    def execute_playbook(self, playbook_id: str, incident: Incident, dry_run: bool = False) -> list[dict[str, Any]]:
        """Execute playbook for incident.

        Args:
            playbook_id: Playbook to execute.
            incident: Incident to respond to.
            dry_run: If True, simulate without actual execution.

        Returns:
            List of action execution results.

        Raises:
            PlaybookException: If execution fails.
        """
        if playbook_id not in self.playbooks:
            raise PlaybookException(f"Playbook not found: {playbook_id}")

        playbook = self.playbooks[playbook_id]

        if not playbook.enabled:
            raise PlaybookException(f"Playbook disabled: {playbook_id}")

        try:
            # Check conditions
            for condition in playbook.conditions:
                if not condition.evaluate(incident):
                    return []

            # Execute actions
            results = []
            for action in playbook.actions:
                # Check approval
                if action.required_approval and not action.auto_approve:
                    self.approval_workflow.submit_for_approval(action)
                    results.append(
                        {
                            "action_id": action.action_id,
                            "status": "pending_approval",
                        }
                    )
                else:
                    result = self.executor.execute_action(action, dry_run)
                    results.append(result)

            playbook.execution_count += 1
            playbook.last_executed = datetime.utcnow()

            return results

        except Exception as e:
            raise PlaybookException(f"Playbook execution failed: {e}")

    def find_applicable_playbooks(self, incident: Incident) -> list[Playbook]:
        """Find playbooks applicable to incident.

        Args:
            incident: Incident to match.

        Returns:
            List of applicable playbooks.
        """
        applicable = []

        for playbook in self.playbooks.values():
            if not playbook.enabled:
                continue

            for condition in playbook.conditions:
                if condition.evaluate(incident):
                    applicable.append(playbook)
                    break

        return applicable

    def get_playbook_statistics(self) -> dict[str, Any]:
        """Get playbook execution statistics.

        Returns:
            Statistics dictionary.
        """
        total_executions = sum(p.execution_count for p in self.playbooks.values())

        return {
            "total_playbooks": len(self.playbooks),
            "enabled_playbooks": len([p for p in self.playbooks.values() if p.enabled]),
            "total_executions": total_executions,
            "execution_history": self.executor.get_execution_history(),
        }


class IncidentResponseManager:
    """Main automated incident response engine.

    Orchestrates playbook execution, action approval, and response tracking.
    """

    def __init__(self):
        """Initialize incident response manager."""
        self.playbook_engine = PlaybookEngine()
        self.executor = self.playbook_engine.executor
        self.approval_workflow = self.playbook_engine.approval_workflow
        self.response_tracking: dict[str, dict[str, Any]] = {}

    def respond_to_incident(self, incident: Incident, dry_run: bool = False) -> dict[str, Any]:
        """Generate and execute response to incident.

        Args:
            incident: Incident to respond to.
            dry_run: If True, simulate response.

        Returns:
            Response execution details.
        """
        incident_id = str(incident.incident_id)

        # Find applicable playbooks
        playbooks = self.playbook_engine.find_applicable_playbooks(incident)

        if not playbooks:
            return {
                "incident_id": incident_id,
                "status": "no_playbooks_found",
            }

        # Execute playbooks
        all_results = []
        for playbook in playbooks:
            results = self.playbook_engine.execute_playbook(playbook.playbook_id, incident, dry_run)
            all_results.extend(results)

        # Track response
        self.response_tracking[incident_id] = {
            "incident_id": incident_id,
            "timestamp": datetime.utcnow(),
            "playbooks_executed": len(playbooks),
            "actions_taken": len(all_results),
            "results": all_results,
            "dry_run": dry_run,
        }

        return self.response_tracking[incident_id]

    def get_response_status(self, incident_id: str) -> dict[str, Any] | None:
        """Get response status for incident.

        Args:
            incident_id: Incident identifier.

        Returns:
            Response status or None.
        """
        return self.response_tracking.get(incident_id)

    def get_pending_approvals(self) -> list[ResponseAction]:
        """Get actions pending approval.

        Returns:
            List of pending actions.
        """
        return self.approval_workflow.get_pending_approvals()

    def approve_action(self, action_id: str, approved_by: str) -> bool:
        """Approve response action.

        Args:
            action_id: Action to approve.
            approved_by: Approver name.

        Returns:
            True if approved.
        """
        approved = self.approval_workflow.approve_action(action_id, approved_by)

        if approved:
            # Try to execute approved action
            for pending_action in self.approval_workflow.approval_history:
                if pending_action.get("action_id") == action_id:
                    # Execute the action
                    pass

        return approved

    def register_integration(self, action_type: ActionType, handler: Callable) -> None:
        """Register integration handler.

        Args:
            action_type: Action type.
            handler: Handler function.
        """
        self.executor.register_integration(action_type, handler)

    def create_standard_playbooks(self) -> None:
        """Create standard incident response playbooks."""
        # High severity incident playbook
        high_severity_pb = Playbook(
            name="High Severity Response",
            description="Automatic response for high/critical severity incidents",
            conditions=[
                PlaybookCondition(
                    condition_type="severity",
                    operator=">=",
                    value=EventSeverity.HIGH.value,
                )
            ],
            actions=[
                ResponseAction(
                    action_type=ActionType.CREATE_TICKET,
                    target="incident",
                    required_approval=False,
                ),
                ResponseAction(
                    action_type=ActionType.SEND_ALERT,
                    target="security_team",
                    required_approval=False,
                ),
            ],
        )

        self.playbook_engine.add_playbook(high_severity_pb)

        # Credential compromise playbook
        cred_compromise_pb = Playbook(
            name="Credential Compromise Response",
            description="Response to suspected credential compromise",
            conditions=[
                PlaybookCondition(
                    condition_type="category",
                    operator="==",
                    value="AUTHENTICATION",
                )
            ],
            actions=[
                ResponseAction(
                    action_type=ActionType.RESET_PASSWORD,
                    target="affected_user",
                    required_approval=True,
                ),
                ResponseAction(
                    action_type=ActionType.CREATE_TICKET,
                    target="incident",
                ),
            ],
        )

        self.playbook_engine.add_playbook(cred_compromise_pb)
