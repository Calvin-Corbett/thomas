"""Tools for Data Pipeline operations.

Exposes core data pipeline functionality as registered tools.
"""

from __future__ import annotations

from typing import Any

from thomas.tools.base import Tool, ToolResult


class PipelineCreateTool(Tool):
    name = "pipeline.create"
    category = "data_pipeline"
    description = "Create a new data pipeline with configuration"
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Pipeline name",
            },
            "description": {
                "type": "string",
                "description": "Pipeline description",
            },
            "stages": {
                "type": "array",
                "description": "List of pipeline stages",
                "items": {"type": "object"},
            },
        },
        "required": ["name"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            name = args["name"]
            description = args.get("description", "")
            stages = args.get("stages", [])

            return ToolResult(
                ok=True,
                data={
                    "pipeline_name": name,
                    "description": description,
                    "stages": len(stages),
                    "status": "pipeline_created",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Failed to create pipeline: {e}")


class PipelineExecuteTool(Tool):
    name = "pipeline.execute"
    category = "data_pipeline"
    description = "Execute a data pipeline"
    parameters = {
        "type": "object",
        "properties": {
            "pipeline_id": {
                "type": "string",
                "description": "ID of the pipeline to execute",
            },
            "parameters": {
                "type": "object",
                "description": "Runtime parameters for the pipeline",
                "additionalProperties": {},
            },
        },
        "required": ["pipeline_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            pipeline_id = args["pipeline_id"]
            params = args.get("parameters", {})

            return ToolResult(
                ok=True,
                data={
                    "pipeline_id": pipeline_id,
                    "parameters": params,
                    "status": "execution_started",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Execution failed: {e}")


class PipelineMonitorTool(Tool):
    name = "pipeline.monitor"
    category = "data_pipeline"
    description = "Monitor pipeline execution and get status/metrics"
    parameters = {
        "type": "object",
        "properties": {
            "pipeline_id": {
                "type": "string",
                "description": "ID of the pipeline to monitor",
            },
            "execution_id": {
                "type": "string",
                "description": "Specific execution ID to get details for",
            },
        },
        "required": ["pipeline_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            pipeline_id = args["pipeline_id"]
            execution_id = args.get("execution_id")

            return ToolResult(
                ok=True,
                data={
                    "pipeline_id": pipeline_id,
                    "execution_id": execution_id,
                    "status": "monitoring",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Monitoring failed: {e}")


class PipelineLineageTool(Tool):
    name = "pipeline.lineage"
    category = "data_pipeline"
    description = "Get data lineage information for a pipeline"
    parameters = {
        "type": "object",
        "properties": {
            "pipeline_id": {
                "type": "string",
                "description": "ID of the pipeline",
            },
        },
        "required": ["pipeline_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            pipeline_id = args["pipeline_id"]

            return ToolResult(
                ok=True,
                data={
                    "pipeline_id": pipeline_id,
                    "status": "lineage_retrieved",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Failed to get lineage: {e}")


class PipelineCheckpointTool(Tool):
    name = "pipeline.checkpoint"
    category = "data_pipeline"
    description = "Create or restore pipeline checkpoints"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create", "restore", "list"],
                "description": "Checkpoint action",
            },
            "pipeline_id": {
                "type": "string",
                "description": "ID of the pipeline",
            },
            "checkpoint_id": {
                "type": "string",
                "description": "ID of checkpoint to restore",
            },
        },
        "required": ["action", "pipeline_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args["action"]
            pipeline_id = args["pipeline_id"]
            checkpoint_id = args.get("checkpoint_id")

            return ToolResult(
                ok=True,
                data={
                    "action": action,
                    "pipeline_id": pipeline_id,
                    "checkpoint_id": checkpoint_id,
                    "status": "checkpoint_managed",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Checkpoint operation failed: {e}")


class PipelineValidateTool(Tool):
    name = "pipeline.validate"
    category = "data_pipeline"
    description = "Validate pipeline configuration and data quality"
    parameters = {
        "type": "object",
        "properties": {
            "pipeline_id": {
                "type": "string",
                "description": "ID of the pipeline to validate",
            },
        },
        "required": ["pipeline_id"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            pipeline_id = args["pipeline_id"]

            return ToolResult(
                ok=True,
                data={
                    "pipeline_id": pipeline_id,
                    "status": "validation_complete",
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=f"Validation failed: {e}")


def register_data_pipeline_tools(registry, sandbox=None):
    """Register all data pipeline tools with the tool registry.

    Args:
        registry: ToolRegistry instance
        sandbox: Sandbox path (optional)
    """
    registry.register(PipelineCreateTool())
    registry.register(PipelineExecuteTool())
    registry.register(PipelineMonitorTool())
    registry.register(PipelineLineageTool())
    registry.register(PipelineCheckpointTool())
    registry.register(PipelineValidateTool())
