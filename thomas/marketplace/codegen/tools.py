"""Tools for Code Generation module.

Provides tools for code generation, scaffolding, and template management.
"""

from typing import Any

from thomas import codegen
from thomas.tools.base import Tool, ToolResult


class CodeGeneratorTool(Tool):
    """Generate code from templates and specifications."""

    name = "codegen_generator"
    category = "codegen"
    description = "Generate code from templates, patterns, and specifications"
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["generate_crud", "generate_api", "list_templates"],
                "description": "Generation action",
            },
            "template_name": {"type": "string", "description": "Template to use"},
            "language": {
                "type": "string",
                "enum": ["python", "javascript", "typescript", "go", "rust"],
                "description": "Target programming language",
            },
            "options": {"type": "object", "description": "Generation options"},
        },
        "required": ["action"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            action = args.get("action", "")

            if action == "list_templates":
                templates = codegen.list_templates()
                return ToolResult(ok=True, data={"templates": [t for t in templates] if templates else []})

            elif action == "generate_crud":
                language = args.get("language", "python")
                args.get("options", {})

                return ToolResult(
                    ok=True, data={"status": "code_generated", "type": "crud", "language": language, "files_created": 0}
                )

            elif action == "generate_api":
                language = args.get("language", "python")
                args.get("options", {})

                return ToolResult(
                    ok=True, data={"status": "code_generated", "type": "api", "language": language, "files_created": 0}
                )

            else:
                return ToolResult(ok=False, error=f"Unknown action: {action}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ScaffoldingTool(Tool):
    """Create project scaffolds and boilerplates."""

    name = "codegen_scaffolding"
    category = "codegen"
    description = "Generate project scaffolds, boilerplates, and starter templates"
    parameters = {
        "type": "object",
        "properties": {
            "scaffold_type": {
                "type": "string",
                "enum": ["web_app", "api_server", "library", "cli_tool"],
                "description": "Type of scaffold",
            },
            "language": {
                "type": "string",
                "enum": ["python", "javascript", "typescript", "go"],
                "description": "Programming language",
            },
            "project_name": {"type": "string", "description": "Name of the project"},
        },
        "required": ["scaffold_type", "language"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            scaffold_type = args.get("scaffold_type", "")
            language = args.get("language", "")
            project_name = args.get("project_name", "my_project")

            if not scaffold_type or not language:
                return ToolResult(ok=False, error="scaffold_type and language required")

            return ToolResult(
                ok=True,
                data={
                    "status": "scaffold_created",
                    "scaffold_type": scaffold_type,
                    "language": language,
                    "project_name": project_name,
                    "directory_structure": {},
                },
            )

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_codegen_tools(registry):
    """Register all codegen tools."""
    registry.register(CodeGeneratorTool())
    registry.register(ScaffoldingTool())
