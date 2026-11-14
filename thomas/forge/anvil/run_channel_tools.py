"""Build tools for server-owned Praxis read/review/verification agents."""

from __future__ import annotations

from typing import Any

from thomas.tools.base import Tool, ToolResult

from .run_channel_client import RunChannelClient


class SpawnAgentsTool(Tool):
    name = "task.spawn_agents"
    category = "agents"
    description = (
        "Submit a cited parallel plan of independent research, review, or verification agents and return handles. "
        "Every unit needs a reason and acceptance check grounded in the user's request. "
        "A unit may select a configured connected model with model_choice.profile and model_choice.model_id. "
        "Use task.wait_agents to collect results; dependencies wait for their predecessors."
    )
    parameters = {
        "type": "object",
        "properties": {
            "why_parallel": {
                "type": "string",
                "enum": ["independent_reads", "disjoint_writes", "independent_verification"],
            },
            "units": {
                "type": "array",
                "minItems": 1,
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string", "enum": ["research", "review", "verify"]},
                        "id": {"type": "string"},
                        "title": {"type": "string"},
                        "brief": {"type": "string"},
                        "reason": {"type": "string"},
                        "model_choice": {
                            "type": "object",
                            "properties": {
                                "profile": {"type": "string"},
                                "model_id": {"type": "string"},
                            },
                            "additionalProperties": False,
                        },
                        "depends_on": {"type": "array", "items": {"type": "string"}},
                        "acceptance": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {"text": {"type": "string"}, "cites": {"type": "string"}},
                                "required": ["text", "cites"],
                            },
                        },
                    },
                    "required": ["id", "kind", "title", "brief", "reason", "acceptance"],
                },
            },
        },
        "required": ["why_parallel", "units"],
    }

    def __init__(self, client: RunChannelClient, emit: Any) -> None:
        self.client, self.emit = client, emit

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            result = await self.client.call(
                "spawn", {"units": args.get("units"), "why_parallel": args.get("why_parallel")}
            )
            for row in result["agents"]:
                self.emit(
                    {
                        "fc": "agent_spawned",
                        **row,
                        "parent_agent_id": self.client.run_id,
                        "agent_title": row["title"],
                        "agent_state": row["state"],
                        "text": f"{row['title']} started",
                    }
                )
            return ToolResult(ok=True, data=result)
        except (RuntimeError, ValueError, KeyError) as exc:
            return ToolResult(ok=False, error=str(exc))


class WaitAgentsTool(Tool):
    name = "task.wait_agents"
    category = "agents"
    description = "Wait up to 300 seconds for server-owned agents and return their new events and current states."
    parameters = {
        "type": "object",
        "properties": {
            "agent_ids": {"type": "array", "items": {"type": "string"}},
            "after": {"type": "object", "additionalProperties": {"type": "integer"}},
            "timeout": {"type": "number", "minimum": 0, "maximum": 300},
        },
        "required": ["agent_ids"],
    }

    def __init__(self, client: RunChannelClient, emit: Any) -> None:
        self.client, self.emit = client, emit

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            result = await self.client.call(
                "wait",
                {"agent_ids": args.get("agent_ids"), "after": args.get("after"), "timeout": args.get("timeout", 30)},
            )
            for row in result["agents"]:
                self.emit(
                    {
                        "fc": "agent_status",
                        "agent_id": row["agent_id"],
                        "agent_title": row["title"],
                        "agent_mode": row["kind"],
                        "agent_state": row["state"],
                        "model": row.get("model_used"),
                        "model_source": row.get("model_source"),
                        "text": f"{row['title']}: resuming"
                        if row["state"] == "quota_wait"
                        else f"{row['title']}: {row['state']}",
                    }
                )
                for event in row["events"]:
                    if event.get("type") == "model_runtime":
                        continue
                    content = str(
                        event.get("text") or event.get("error") or event.get("name") or event.get("type") or ""
                    )
                    self.emit(
                        {
                            "fc": "agent_event",
                            "agent_id": row["agent_id"],
                            "agent_title": row["title"],
                            "agent_mode": row["kind"],
                            "model": row.get("model_used"),
                            "model_source": row.get("model_source"),
                            "text": content[:4000],
                            "is_error": event.get("type") == "error",
                        }
                    )
            return ToolResult(ok=True, data=result)
        except (RuntimeError, ValueError, KeyError) as exc:
            return ToolResult(ok=False, error=str(exc))


class AgentStatusTool(Tool):
    name = "task.agent_status"
    category = "agents"
    description = "Read current Praxis agent states without waiting."
    parameters = {"type": "object", "properties": {"agent_ids": {"type": "array", "items": {"type": "string"}}}}

    def __init__(self, client: RunChannelClient) -> None:
        self.client = client

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            return ToolResult(ok=True, data=await self.client.call("status", {"agent_ids": args.get("agent_ids")}))
        except (RuntimeError, ValueError) as exc:
            return ToolResult(ok=False, error=str(exc))


class StopAgentTool(Tool):
    name = "task.stop_agent"
    category = "agents"
    description = "Stop one child agent in this Build run, leaving its recorded work available for review."
    parameters = {
        "type": "object",
        "properties": {"agent_id": {"type": "string"}},
        "required": ["agent_id"],
    }

    def __init__(self, client: RunChannelClient, emit: Any) -> None:
        self.client, self.emit = client, emit

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            result = await self.client.call("stop_child", {"agent_id": args.get("agent_id")})
            self.emit(
                {
                    "fc": "agent_status",
                    "agent_id": result["agent_id"],
                    "agent_state": result["state"],
                    "text": f"Agent {result['agent_id']}: {result['state']}",
                }
            )
            return ToolResult(ok=True, data=result)
        except (RuntimeError, ValueError, KeyError) as exc:
            return ToolResult(ok=False, error=str(exc))


def register_run_channel_tools(registry: Any, emit: Any) -> None:
    client = RunChannelClient.from_environment()
    if client is None:
        return
    registry.register(SpawnAgentsTool(client, emit))
    registry.register(WaitAgentsTool(client, emit))
    registry.register(AgentStatusTool(client))
    registry.register(StopAgentTool(client, emit))
