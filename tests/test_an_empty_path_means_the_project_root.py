"""An empty path argument means the project root, and a listing is not a write (2026-09-05).

Counted on one day's Build transcripts: 23 calls to ``code.project_structure``
and ``code.search`` refused with "Invalid file path argument ... path cannot be
empty". The model was asking for the project root, which is what an empty path
means for a tool whose path is optional, and nine of those refusals even called
the directory listing a "write tool". Every refusal cost a round.

An empty path validates to ``.`` and the tool decides what to do with it (a
write to ``.`` is a directory and fails on its own terms). A read-only
inspection tool is never a write tool.
"""

from __future__ import annotations

from thomas.agent.loop_tool_exec import _is_write_tool
from thomas.agent.loop_tool_paths import _validate_filesystem_path


def test_an_empty_path_validates_to_the_root() -> None:
    assert _validate_filesystem_path("") == (".", None)
    assert _validate_filesystem_path("   ") == (".", None)


def test_a_missing_value_is_still_an_error() -> None:
    path, error = _validate_filesystem_path(None)
    assert path is None and "missing" in str(error)


def test_inspection_tools_are_never_write_tools() -> None:
    for name in ("code.project_structure", "code.search", "code.find_definition", "fs.read_file", "fs.list_dir"):
        assert _is_write_tool(name, None) is False, name
    assert _is_write_tool("fs.write_file", None) is True
    assert _is_write_tool("diff.create", None) is True
