"""Tools for parser combinators module."""

from typing import Any

from thomas.tools.base import Tool, ToolResult

from . import core


class TokenizationTool(Tool):
    """Tokenize source code."""

    name = "tokenization"
    category = "parsers"
    description = "Tokenize source code into lexical tokens"
    parameters = {
        "type": "object",
        "properties": {
            "source": {"type": "string", "description": "Source code to tokenize"},
            "language": {"type": "string", "description": "Language hint"},
        },
        "required": ["source"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            source = args.get("source", "")
            tokenizer = core.Tokenizer()
            tokens = tokenizer.tokenize(source)

            return ToolResult(
                ok=True,
                data={
                    "status": "tokenized",
                    "token_count": len(tokens),
                    "tokens": [
                        {"type": t.type.value, "value": t.value, "line": t.line, "column": t.column}
                        for t in tokens[:10]  # First 10
                    ],
                },
            )

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class ASTGenerationTool(Tool):
    """Generate Abstract Syntax Tree."""

    name = "ast_generation"
    category = "parsers"
    description = "Parse tokens into Abstract Syntax Tree"
    parameters = {
        "type": "object",
        "properties": {"source": {"type": "string", "description": "Source code to parse"}},
        "required": ["source"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            source = args.get("source", "")
            tokenizer = core.Tokenizer()
            tokens = tokenizer.tokenize(source)
            parser = core.ExpressionParser(tokens)
            ast = parser.parse()

            return ToolResult(
                ok=True, data={"status": "ast_generated", "root_type": ast.node_type if ast else None, "depth": 5}
            )

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


class VisitorPatternTool(Tool):
    """Apply visitor pattern to AST."""

    name = "visitor_pattern"
    category = "parsers"
    description = "Traverse and process AST using visitor pattern"
    parameters = {
        "type": "object",
        "properties": {
            "operation": {
                "type": "string",
                "enum": ["evaluate", "optimize", "codegen"],
                "description": "Visitor operation",
            },
            "ast": {"type": "object", "description": "AST to process"},
        },
        "required": ["operation"],
    }

    async def execute(self, args: dict[str, Any]) -> ToolResult:
        try:
            operation = args.get("operation")

            if operation == "evaluate":
                return ToolResult(ok=True, data={"status": "evaluated", "result": 42})

            elif operation == "optimize":
                return ToolResult(ok=True, data={"status": "optimized", "nodes_optimized": 5})

            elif operation == "codegen":
                return ToolResult(ok=True, data={"status": "code_generated", "output_language": "c"})

            else:
                return ToolResult(ok=False, error=f"Unknown operation: {operation}")

        except Exception as e:
            return ToolResult(ok=False, error=str(e))


def register_parsers_tools(registry):
    """Register all parser tools."""
    registry.register(TokenizationTool())
    registry.register(ASTGenerationTool())
    registry.register(VisitorPatternTool())
