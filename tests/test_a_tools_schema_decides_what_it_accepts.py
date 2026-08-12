"""A word in a tool's name must not overrule the tool's own contract.

Whether a tool writes was decided by searching its NAME for words like "write",
"create" and "patch". `diff.preview_patch` contains one, so previewing a patch
-- which explicitly does not apply it -- was treated as a write and rejected for
not supplying a path. It has no path parameter: its only argument is the diff
text, and the paths live inside that.

So the tool could never be called successfully, by any model, ever. Found by
watching Thomas build a page and print this into his own run:

    Technical check failed
    Invalid file path argument for write tool diff.preview_patch:
    missing path argument (expected path, file, or filename)
"""

from __future__ import annotations

from thomas.agent.loop_tool_exec import _declares_a_path_parameter
from thomas.tools.diff import PreviewPatchTool


class _Registry:
    def __init__(self, *tools) -> None:
        self._tools = {tool.name: tool for tool in tools}

    def get(self, name):
        return self._tools.get(name)


class _WritesToAPath:
    name = "fs.write_file"
    parameters = {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}}


class _NoSchemaAtAll:
    name = "mystery.tool"
    parameters = None


def test_previewing_a_patch_does_not_demand_a_path(tmp_path) -> None:
    """The case that made the tool unusable."""
    registry = _Registry(PreviewPatchTool(tmp_path))

    assert _declares_a_path_parameter(registry, "diff.preview_patch") is False


def test_a_tool_that_takes_a_path_still_has_it_required() -> None:
    registry = _Registry(_WritesToAPath())

    assert _declares_a_path_parameter(registry, "fs.write_file") is True


def test_a_tool_with_no_schema_stays_guarded() -> None:
    """Unknown means closed. A tool that publishes no contract does not get to
    skip the check by saying nothing."""
    registry = _Registry(_NoSchemaAtAll())

    assert _declares_a_path_parameter(registry, "mystery.tool") is True


def test_an_unregistered_tool_stays_guarded() -> None:
    assert _declares_a_path_parameter(_Registry(), "never.heard.of.it") is True


def test_a_missing_registry_stays_guarded() -> None:
    assert _declares_a_path_parameter(None, "anything") is True


def test_the_real_tool_declares_only_the_patch_text(tmp_path) -> None:
    """Pinning the fact the fix rests on, so a later schema change is visible
    here rather than as a tool that silently stops working again."""
    properties = PreviewPatchTool(tmp_path).parameters["properties"]

    assert set(properties) == {"patch"}
