"""Tools for prompts module - prompt template building and management."""

from __future__ import annotations

import logging
from typing import Any

from thomas.tools.base import Tool, ToolResult

from .chat_template import ChatPromptTemplate
from .few_shot import FewShotPromptTemplate
from .optimizer import TokenCounter
from .string_template import StringPromptTemplate
from .version import PromptStore

log = logging.getLogger(__name__)


class PromptsCreateStringTemplateTool(Tool):
    """Create a string prompt template."""

    name = "prompts_create_string_template"
    category = "prompts"
    description = "Create a simple string template using {variable} syntax."
    parameters = {
        "type": "object",
        "properties": {
            "template": {
                "type": "string",
                "description": "Template string with {variable} placeholders",
            },
            "input_variables": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of variable names",
            },
        },
        "required": ["template"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            template = StringPromptTemplate(
                template=args["template"],
                input_variables=args.get("input_variables", []),
            )

            formatted = template.format()
            messages = template.format_messages()

            return ToolResult(
                ok=True,
                data={
                    "template": args["template"],
                    "input_variables": template.input_variables,
                    "sample_output": formatted[:200],
                    "message_count": len(messages),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PromptsCreateChatTemplateTool(Tool):
    """Create a multi-turn chat template."""

    name = "prompts_create_chat_template"
    category = "prompts"
    description = "Create a multi-turn chat prompt template with system/user/assistant messages."
    parameters = {
        "type": "object",
        "properties": {
            "messages": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "role": {"type": "string"},
                        "content": {"type": "string"},
                    },
                },
                "description": "List of message dicts with role and content",
            },
            "input_variables": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of variable names",
            },
        },
        "required": ["messages"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            template = ChatPromptTemplate(
                messages=args.get("messages", []),
                input_variables=args.get("input_variables", []),
            )

            formatted = template.format()
            messages = template.format_messages()

            return ToolResult(
                ok=True,
                data={
                    "message_count": len(template.messages),
                    "input_variables": template.input_variables,
                    "sample_output": formatted[:200],
                    "formatted_messages": len(messages),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PromptsCountTokensTool(Tool):
    """Count tokens in text or messages."""

    name = "prompts_count_tokens"
    category = "prompts"
    description = "Estimate token count for text or messages."
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "Text to count (use for single text)",
            },
            "model": {
                "type": "string",
                "description": "Model name for token counting (default: gpt-3.5-turbo)",
            },
        },
        "required": ["text"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            counter = TokenCounter(model=args.get("model", "gpt-3.5-turbo"))
            text = args.get("text", "")

            token_count = counter.count_tokens(text)

            return ToolResult(
                ok=True,
                data={
                    "text": text[:100] + ("..." if len(text) > 100 else ""),
                    "token_count": token_count,
                    "model": counter.model,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PromptsCreateFewShotTemplateTool(Tool):
    """Create a few-shot prompt template."""

    name = "prompts_create_few_shot_template"
    category = "prompts"
    description = "Create a few-shot prompt with examples prepended to the query."
    parameters = {
        "type": "object",
        "properties": {
            "examples": {
                "type": "array",
                "items": {},
                "description": "List of example dicts",
            },
            "template": {
                "type": "string",
                "description": "Query template string",
            },
            "input_variables": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Template variable names",
            },
        },
        "required": ["examples", "template"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            template = FewShotPromptTemplate(
                examples=args.get("examples", []),
                template=args["template"],
                input_variables=args.get("input_variables", []),
            )

            return ToolResult(
                ok=True,
                data={
                    "example_count": len(template.examples),
                    "template": args["template"][:100],
                    "input_variables": template.input_variables,
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PromptsCreatePromptStoreTool(Tool):
    """Create a prompt store."""

    name = "prompts_create_prompt_store"
    category = "prompts"
    description = "Create an in-memory prompt template registry."
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Optional filesystem path for metadata",
            },
        },
        "required": [],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            store = PromptStore(path=args.get("path"))

            return ToolResult(
                ok=True,
                data={
                    "store_path": store.path,
                    "prompt_count": len(store.prompts),
                    "prompts": store.list_prompts(),
                },
            )
        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_prompts_tools(registry):
    """Register prompts tools with the tool registry."""
    tools = [
        PromptsCreateStringTemplateTool(),
        PromptsCreateChatTemplateTool(),
        PromptsCountTokensTool(),
        PromptsCreateFewShotTemplateTool(),
        PromptsCreatePromptStoreTool(),
    ]
    for tool in tools:
        registry.register(tool)
