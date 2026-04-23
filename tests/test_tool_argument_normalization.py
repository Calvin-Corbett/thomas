import asyncio

from thomas.tools.base import Tool, ToolResult


class _IntArgTool(Tool):
    name = "test.int_arg"
    category = "test"
    description = "returns integer arg"
    parameters = {
        "type": "object",
        "properties": {
            "n": {
                "type": "integer",
            },
        },
        "required": ["n"],
    }

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data={"n": args.get("n"), "kind": type(args.get("n")).__name__})


def test_safe_execute_coerces_integer_string() -> None:
    tool = _IntArgTool()
    result = asyncio.run(tool.safe_execute({"n": "42"}))
    assert result.ok is True
    assert result.data["n"] == 42
    assert result.data["kind"] == "int"


def test_safe_execute_rejects_non_numeric_integer_string() -> None:
    tool = _IntArgTool()
    result = asyncio.run(tool.safe_execute({"n": "forty two"}))
    assert result.ok is False
    assert "invalid tool arguments" in str(result.error or "").lower()
    assert "expected integer" in str(result.error or "").lower()


def test_safe_execute_reports_missing_required_field() -> None:
    tool = _IntArgTool()
    result = asyncio.run(tool.safe_execute({}))
    assert result.ok is False
    assert "missing required field" in str(result.error or "").lower()
