"""Tools for LLM Chain module.

Provides tools for creating, executing, and managing chains.
"""

from typing import Any

from thomas.chain import core
from thomas.tools.base import Tool, ToolResult


class ChainManagementTool(Tool):
    """Manage chains and chain templates."""

    name = "chain_management"
    category = "chain"
    description = "Create and manage LLM chains"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_chain", "list_chains", "get_chain"],
                "description": "Chain management action",
            },
            "chain_name": {"type": "string", "description": "Name of the chain"},
            "chain_type": {
                "type": "string",
                "enum": ["sequential", "parallel", "conditional"],
                "description": "Type of chain",
            },
            "chain_id": {"type": "string", "description": "Chain identifier"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.registry = core.ChainRegistry()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_chain":
                chain_name = args.get("chain_name", "chain")
                chain_type_str = args.get("chain_type", "sequential")
                chain_type = core.ChainType(chain_type_str)

                chain = core.LLMChain(chain_name, chain_type)
                self.registry.register_chain(chain)

                return ToolResult(
                    ok=True, data={"chain_id": chain.id, "chain_name": chain_name, "chain_type": chain_type_str}
                )

            elif action == "list_chains":
                chains = self.registry.list_chains()
                return ToolResult(ok=True, data={"chains": chains})

            elif action == "get_chain":
                chain_id = args.get("chain_id", "")
                if not chain_id:
                    return ToolResult(ok=False, error="chain_id required")

                chain = self.registry.get_chain(chain_id)
                if not chain:
                    return ToolResult(ok=False, error=f"Chain not found: {chain_id}")

                return ToolResult(ok=True, data=chain.get_chain_structure())

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ChainExecutionTool(Tool):
    """Execute chains and manage execution."""

    name = "chain_execute"
    category = "chain"
    description = "Execute chains and get results"
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["execute_chain", "get_history"], "description": "Execution action"},
            "chain_id": {"type": "string", "description": "Chain to execute"},
        },
        "required": ["action", "chain_id"],
    }

    def __init__(self):
        self.registry = core.ChainRegistry()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")
            chain_id = args.get("chain_id", "")

            if not chain_id:
                return ToolResult(ok=False, error="chain_id required")

            chain = self.registry.get_chain(chain_id)
            if not chain:
                return ToolResult(ok=False, error=f"Chain not found: {chain_id}")

            if action == "execute_chain":
                result = await chain.execute()
                return ToolResult(ok=True, data=result)

            elif action == "get_history":
                history = chain.get_execution_history()
                return ToolResult(ok=True, data={"executions": history})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class PromptTemplateTool(Tool):
    """Manage prompt templates."""

    name = "chain_templates"
    category = "chain"
    description = "Create and manage prompt templates"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["create_template", "list_templates", "render_template"],
                "description": "Template action",
            },
            "template_name": {"type": "string", "description": "Template name"},
            "template_text": {"type": "string", "description": "Template text with {variables}"},
        },
        "required": ["action"],
    }

    def __init__(self):
        self.registry = core.ChainRegistry()

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "create_template":
                name = args.get("template_name", "template")
                text = args.get("template_text", "")

                # Extract variables from template
                import re

                variables = re.findall(r"\{(\w+)\}", text)

                template = core.PromptTemplate(name=name, template=text, variables=variables)
                self.registry.register_template(template)

                return ToolResult(ok=True, data={"template_id": template.id, "name": name, "variables": variables})

            elif action == "list_templates":
                templates = self.registry.list_templates()
                return ToolResult(ok=True, data={"templates": templates})

            elif action == "render_template":
                return ToolResult(ok=True, data={"message": "Render requires template_id"})

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_chain_tools(registry):
    """Register all chain tools."""
    registry.register(ChainManagementTool())
    registry.register(ChainExecutionTool())
    registry.register(PromptTemplateTool())
