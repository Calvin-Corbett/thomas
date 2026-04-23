"""Tools for data loading operations."""

from typing import Any

from thomas.loaders import core
from thomas.tools.base import Tool, ToolResult


class DataLoadingTool(Tool):
    """Load data from various formats."""

    name = "data_load"
    category = "loaders"
    description = "Load data from CSV, JSON, XML, Parquet formats"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["load", "stream", "validate"], "description": "Loading action"},
            "format": {"type": "string", "enum": ["csv", "json", "xml", "parquet"], "description": "Data format"},
            "source": {"type": "string", "description": "Data source content"},
            "batch_size": {"type": "integer", "description": "Batch size for streaming"},
            "schema": {"type": "object", "description": "Schema for validation"},
        },
        "required": ["action", "format"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            format_type = args.get("format", "")
            source = args.get("source", "")

            loader = core.DataLoaderFactory.create_loader(format_type)
            if not loader:
                return ToolResult(ok=False, error=f"Unsupported format: {format_type}")

            if action == "load":
                if not source:
                    return ToolResult(ok=False, error="source required")

                result = loader.load(source)
                return ToolResult(
                    ok=True,
                    data={
                        "rows_loaded": result.rows_loaded,
                        "rows_failed": result.rows_failed,
                        "errors": result.errors,
                        "sample": result.sample_data,
                    },
                )

            elif action == "stream":
                if not source:
                    return ToolResult(ok=False, error="source required")

                batch_size = args.get("batch_size", 100)
                batches = []

                for batch in loader.stream(source, batch_size):
                    batches.append({"batch_size": len(batch), "rows": batch})

                return ToolResult(
                    ok=True,
                    data={
                        "batches": len(batches),
                        "total_rows": sum(b["batch_size"] for b in batches),
                        "samples": [b["rows"][:2] for b in batches[:3]],
                    },
                )

            elif action == "validate":
                if not source:
                    return ToolResult(ok=False, error="source required")

                result = loader.load(source)
                schema = args.get("schema", {})

                if schema and result.sample_data:
                    validator = core.DataValidator(schema)
                    validation = validator.validate(result.sample_data)
                    return ToolResult(ok=True, data=validation)

                return ToolResult(
                    ok=True,
                    data={"rows_loaded": result.rows_loaded, "valid_rows": result.rows_loaded - result.rows_failed},
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class FormatInfoTool(Tool):
    """Get information about supported formats."""

    name = "data_format_info"
    category = "loaders"
    description = "Get information about supported data formats"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["list_formats", "format_details"], "description": "Info action"},
            "format": {"type": "string", "description": "Format to get details for"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "list_formats":
                formats = core.DataLoaderFactory.get_supported_formats()
                return ToolResult(ok=True, data={"formats": formats, "count": len(formats)})

            elif action == "format_details":
                format_type = args.get("format", "")
                if not format_type:
                    return ToolResult(ok=False, error="format required")

                details = {
                    "csv": {"description": "Comma-separated values", "supports_streaming": True},
                    "json": {"description": "JavaScript Object Notation", "supports_streaming": True},
                    "xml": {"description": "Extensible Markup Language", "supports_streaming": True},
                    "parquet": {"description": "Apache Parquet columnar format", "supports_streaming": True},
                }

                if format_type not in details:
                    return ToolResult(ok=False, error=f"Unknown format: {format_type}")

                return ToolResult(ok=True, data=details[format_type])

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_loaders_tools(registry):
    """Register all data loader tools."""
    registry.register(DataLoadingTool())
    registry.register(FormatInfoTool())
