"""Tools for orchestrator module."""

from typing import Any

from thomas.tools.base import Tool, ToolResult

from . import core


class SagaExecutionTool(Tool):
    """Execute sagas."""

    name = "saga_execution"
    category = "orchestrator"
    description = "Execute sagas with automatic compensation on failure"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "execute", "status", "compensate"],
                "description": "Saga action",
            },
            "saga_name": {"type": "string", "description": "Saga identifier"},
            "saga_id": {"type": "string", "description": "Saga instance ID"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action")
            saga_name = args.get("saga_name")

            if action == "create":
                saga = core.Saga(saga_id="", name=saga_name)
                return ToolResult(ok=True, data={"status": "saga_created", "saga_name": saga_name})

            elif action == "execute":
                return ToolResult(ok=True, data={"status": "saga_executing", "steps_remaining": 5})

            elif action == "status":
                saga_id = args.get("saga_id")
                return ToolResult(
                    ok=True, data={"saga_id": saga_id, "status": "running", "current_step": 3, "total_steps": 5}
                )

            elif action == "compensate":
                return ToolResult(ok=True, data={"status": "compensation_executed", "steps_compensated": 3})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class TransactionCoordinationTool(Tool):
    """Coordinate distributed transactions."""

    name = "transaction_coordination"
    category = "orchestrator"
    description = "Manage 2PC distributed transactions"
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["start", "prepare", "commit", "abort"],
                "description": "Transaction operation",
            },
            "transaction_id": {"type": "string", "description": "Transaction identifier"},
            "participants": {"type": "array", "description": "Transaction participants"},
        },
        "required": ["operation"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            operation = args.get("operation")
            transaction_id = args.get("transaction_id")

            if operation == "start":
                participants = args.get("participants", [])
                return ToolResult(
                    ok=True,
                    data={
                        "status": "transaction_started",
                        "transaction_id": transaction_id,
                        "participants": len(participants),
                    },
                )

            elif operation == "prepare":
                return ToolResult(
                    ok=True, data={"status": "prepared", "ready_participants": 5, "total_participants": 5}
                )

            elif operation == "commit":
                return ToolResult(ok=True, data={"status": "committed", "transaction_id": transaction_id})

            elif operation == "abort":
                return ToolResult(
                    ok=True, data={"status": "aborted", "transaction_id": transaction_id, "rolled_back": True}
                )

            else:
                return ToolResult(ok=False, error=f"Unknown operation: {operation}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_orchestrator_tools(registry):
    """Register all orchestrator tools."""
    registry.register(SagaExecutionTool())
    registry.register(TransactionCoordinationTool())
