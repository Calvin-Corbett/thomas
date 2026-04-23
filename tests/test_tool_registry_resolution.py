import asyncio

from thomas.tools.base import Tool, ToolResult
from thomas.tools.registry import ToolRegistry


class _EchoTool(Tool):
    name = "fs.read_file"
    category = "test"
    description = "echo"
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args):  # noqa: ANN001
        return ToolResult(ok=True, data={"args": args})


def test_tool_registry_resolves_case_and_delimiter_aliases() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())

    async def run():
        out1 = await reg.execute("FS.READ_FILE", {})
        out2 = await reg.execute("fs_read_file", {})
        out3 = await reg.execute("functions.fs.read_file", {})
        return out1, out2, out3

    out1, out2, out3 = asyncio.run(run())
    assert out1.ok is True
    assert out2.ok is True
    assert out3.ok is True


def test_tool_registry_unknown_tool_still_fails() -> None:
    reg = ToolRegistry()
    reg.register(_EchoTool())

    async def run():
        return await reg.execute("definitely.unknown", {})

    out = asyncio.run(run())
    assert out.ok is False
    assert "Unknown tool" in (out.error or "")
