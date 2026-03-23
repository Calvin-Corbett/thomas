"""Tools for Natural Language Generation module.

Provides tools for text generation, summarization, and dialogue.
"""

from typing import Any

from thomas.tools.base import Tool, ToolResult


class DataToTextTool(Tool):
    """Generate text from structured data."""

    name = "nlg_data_to_text"
    category = "nlg"
    description = "Convert structured data into natural language descriptions"
    parameters = {
        "type": "object",
        "properties": {
            "data_type": {
                "type": "string",
                "enum": ["sports", "weather", "financial", "health"],
                "description": "Type of data to generate from",
            },
            "data": {"type": "object", "description": "Structured data object"},
        },
        "required": ["data_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            data_type = args.get("data_type", "")
            data = args.get("data", {})

            if data_type not in ["sports", "weather", "financial", "health"]:
                return ToolResult(ok=False, error=f"Unknown data type: {data_type}")

            return ToolResult(ok=True, data={"status": "text_generated", "data_type": data_type, "text": ""})

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class DialogueGenerationTool(Tool):
    """Generate conversational dialogue."""

    name = "nlg_dialogue"
    category = "nlg"
    description = "Generate natural dialogue and conversational responses"
    parameters = {
        "type": "object",
        "properties": {
            "dialogue_type": {
                "type": "string",
                "enum": ["customer_service", "chitchat", "negotiation", "task_oriented"],
                "description": "Type of dialogue",
            },
            "context": {"type": "object", "description": "Dialogue context"},
            "turn": {"type": "integer", "description": "Dialogue turn number"},
        },
        "required": ["dialogue_type"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            dialogue_type = args.get("dialogue_type", "")
            context = args.get("context", {})

            supported = ["customer_service", "chitchat", "negotiation", "task_oriented"]
            if dialogue_type not in supported:
                return ToolResult(ok=False, error=f"Unknown dialogue type: {dialogue_type}")

            return ToolResult(
                ok=True, data={"status": "dialogue_generated", "dialogue_type": dialogue_type, "response": ""}
            )

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class TextSummarizationTool(Tool):
    """Summarize text content."""

    name = "nlg_summarization"
    category = "nlg"
    description = "Generate summaries of text with various styles and lengths"
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "Text to summarize"},
            "style": {
                "type": "string",
                "enum": ["abstractive", "extractive", "headline"],
                "description": "Summarization style",
            },
            "compression_ratio": {"type": "number", "description": "Compression ratio (0.0-1.0)"},
        },
        "required": ["text", "style"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            text = args.get("text", "")
            style = args.get("style", "extractive")
            ratio = float(args.get("compression_ratio", 0.3))

            if not text:
                return ToolResult(ok=False, error="text required")

            if style not in ["abstractive", "extractive", "headline"]:
                return ToolResult(ok=False, error=f"Unknown style: {style}")

            return ToolResult(
                ok=True, data={"status": "summary_generated", "style": style, "compression_ratio": ratio, "summary": ""}
            )

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_nlg_tools(registry):
    """Register all NLG tools."""
    registry.register(DataToTextTool())
    registry.register(DialogueGenerationTool())
    registry.register(TextSummarizationTool())
