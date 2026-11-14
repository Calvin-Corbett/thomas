"""Repeated stale edits ask for a fresh read and show current, numbered context."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from thomas.core.session_scope import active_session_id, bind_session
from thomas.tools.diff import CreateDiffTool


def _edit(tool: CreateDiffTool, file: str, old: str, new: str = "replacement\n"):
    return asyncio.run(tool.execute({"file": file, "old_str": old, "new_str": new}))


def _assert_reread(result) -> str:
    assert not result.ok
    error = str(result.error)
    assert "This text is not in the file now" in error
    assert "must read it again with fs.read_file before the next edit" in error
    return error


@pytest.mark.parametrize("replacement", ["replacement\n", "another replacement\n"])
def test_second_miss_requires_reread_even_if_new_str_changes(tmp_path: Path, replacement: str) -> None:
    path = tmp_path / "app.py"
    current = "import os\n\ndef start(port):\n    serve(port=port)\n"
    path.write_text(current, encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = "def start(port):\n    serve(port)\n"
    first = _edit(tool, "app.py", old)
    assert not first.ok and "old_str not found" in str(first.error)
    assert "must read it again" not in str(first.error)
    for _ in range(2):
        error = _assert_reread(_edit(tool, "./app.py", old, replacement))
        assert "     3\tdef start(port):" in error
        assert "     4\t    serve(port=port)" in error
    assert path.read_text(encoding="utf-8") == current


@pytest.mark.parametrize("prefix", ["    21\t", "21\t"])
@pytest.mark.parametrize("duplicate", [False, True])
@pytest.mark.parametrize("target", ["x", "renamed"])
def test_numbered_stale_snippet_keeps_its_source_anchor(
    tmp_path: Path, prefix: str, duplicate: bool, target: str
) -> None:
    path = tmp_path / "app.py"
    current = ("x\nunrelated\n" if duplicate else "# gap\n" * 2) + "# gap\n" * 18 + target + "\ncurrent\n"
    path.write_text(current, encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = prefix + "x\n    22\tstale\n"
    first = _edit(tool, "app.py", old)
    assert not first.ok and "must read it again" not in str(first.error)
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "was last found (line 21)" in error
    assert f"    21\t{target}" in error and "    22\tcurrent" in error
    assert path.read_text(encoding="utf-8") == current


@pytest.mark.parametrize("successful_edit", [False, True])
def test_numbered_anchor_tracks_a_previously_observed_first_line_when_it_moves(
    tmp_path: Path, successful_edit: bool
) -> None:
    path = tmp_path / "app.py"
    old = "    21\tdef target():\n    22\t    stale()\n"
    initial_body = "stale()" if successful_edit else "current()"
    path.write_text("# gap\n" * 20 + f"def target():\n    {initial_body}\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    assert _edit(tool, "app.py", old, "def target():\n    current()\n").ok == successful_edit
    path.write_text("# moved\n" * 25 + "def target():\n    current()\n", encoding="utf-8")
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "was last found (line 26)" in error
    assert "    26\tdef target():" in error
    assert "    27\t    current()" in error


@pytest.mark.parametrize("blank_lines", [1, 45])
def test_successful_numbered_snippet_anchors_after_leading_blanks(tmp_path: Path, blank_lines: int) -> None:
    path = tmp_path / "app.py"
    source = "\n" * blank_lines + "def target():\n    stale()\n"
    path.write_text("# gap\n" * 20 + source + "footer\n", encoding="utf-8")
    old = "".join(f"{i:6d}\t{line}\n" for i, line in enumerate(source.splitlines(), start=21))
    replacement = "\n" * blank_lines + "renamed completely\n    fresh()\n"
    tool = CreateDiffTool(tmp_path)
    assert _edit(tool, "app.py", old, replacement).ok
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    anchor = 21 + blank_lines
    assert f"was last found (line {anchor})" in error
    assert f"{anchor:6d}\trenamed completely" in error
    assert f"{anchor + 1:6d}\t    fresh()" in error
    assert path.read_text(encoding="utf-8") == "# gap\n" * 20 + replacement + "footer\n"


def test_misses_are_per_resolved_file_and_search_string_not_consecutive(tmp_path: Path) -> None:
    for name in ("a.py", "b.py"):
        (tmp_path / name).write_text("current = True\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = "stale = True\n"
    assert "must read it again" not in str(_edit(tool, "a.py", old).error)
    assert "must read it again" not in str(_edit(tool, "b.py", old).error)
    assert "must read it again" not in str(_edit(tool, "a.py", "different = True\n").error)
    _assert_reread(_edit(tool, str(tmp_path / "a.py"), old))
    _assert_reread(_edit(tool, "b.py", old))
    fresh_run = CreateDiffTool(tmp_path)
    assert "must read it again" not in str(_edit(fresh_run, "a.py", old).error)


def test_second_miss_uses_current_lines_at_remembered_anchor(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("header\n\ndef target():\n    current()\nfooter\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = "def target():\n    stale()\n"
    assert not _edit(tool, "app.py", old).ok
    path.write_text("header\n\nrenamed completely\n    fresh()\nfooter\n", encoding="utf-8")
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "last found" in error
    assert "     3\trenamed completely" in error
    assert "     4\t    fresh()" in error
    assert "current()" not in error


def test_anchor_is_remembered_from_a_successful_edit(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("header\n\ndef target():\n    stale()\nfooter\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = "def target():\n    stale()\n"
    assert _edit(tool, "app.py", old, "renamed completely\n    fresh()\n").ok
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "last found" in error
    assert "     3\trenamed completely" in error
    assert "     4\t    fresh()" in error


def test_successful_multiline_match_anchors_to_its_actual_occurrence(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("if enabled:\n    unrelated()\n" + "# gap\n" * 10 + "if enabled:\n    stale()\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = "if enabled:\n    stale()\n"
    assert _edit(tool, "app.py", old, "renamed completely\n    fresh()\n").ok
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "    13\trenamed completely" in error
    assert "    14\t    fresh()" in error
    assert "unrelated()" not in error


@pytest.mark.parametrize("moved", [False, True])
@pytest.mark.parametrize("through_tool", [False, True])
def test_changed_unrelated_block_does_not_replace_a_known_anchor(
    tmp_path: Path, through_tool: bool, moved: bool
) -> None:
    path = tmp_path / "app.py"
    old = "if enabled:\n    stale()\n"
    path.write_text("if enabled:\n    unrelated()\n" + "# gap\n" * 10 + old, encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    assert _edit(tool, "app.py", old, "renamed completely\n    fresh()\n").ok
    current = ("# moved\n" if moved else "") + "if enabled:\n    updated()\n" + "# gap\n" * (9 if moved else 10)
    if through_tool:
        assert _edit(tool, "app.py", "if enabled:\n    unrelated()\n" + "# gap\n" * 10, current).ok
    else:
        path.write_text(current + "renamed completely\n    fresh()\n", encoding="utf-8")
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "was last found (line 13)" in error
    assert "    13\trenamed completely" in error
    assert "    14\t    fresh()" in error
    assert "updated()" not in error


def test_duplicate_full_matches_do_not_overwrite_a_known_anchor(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    old = "def target():\n    stale()\n"
    path.write_text("# gap\n" * 12 + old + "footer\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    assert _edit(tool, "app.py", old, "renamed\n    fresh()\n").ok
    path.write_text(old + "# gap\n" * 10 + old + "footer\n", encoding="utf-8")
    assert _edit(tool, "app.py", "footer", "changed footer").ok
    path.write_text("unrelated\n" + "# gap\n" * 11 + "renamed\n    fresh()\n", encoding="utf-8")
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "was last found (line 13)" in error
    assert "    13\trenamed" in error
    assert "unrelated" not in error


@pytest.mark.parametrize(
    "footer, current_footer", [("", ""), ("footer\n", "footer\n"), ("footer\n", "changed footer\n")]
)
@pytest.mark.parametrize("through_tool", [False, True])
def test_full_deletion_keeps_its_anchor_when_an_unrelated_first_line_appears(
    tmp_path: Path, through_tool: bool, footer: str, current_footer: str
) -> None:
    path = tmp_path / "app.py"
    old = "def target():\n    stale()\n"
    prefix = "# gap\n" * 20
    path.write_text(prefix + old + footer, encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    assert _edit(tool, "app.py", old, "").ok
    current_prefix = "def target():\n    unrelated()\n" + "# gap\n" * 18
    if through_tool:
        assert _edit(tool, "app.py", prefix + footer, current_prefix + current_footer).ok
    else:
        path.write_text(current_prefix + current_footer, encoding="utf-8")
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "was last found (line 21)" in error
    if current_footer:
        assert f"    21\t{current_footer.strip()}" in error
    assert "unrelated()" not in error


def test_new_unrelated_first_line_cannot_steal_a_replaced_anchor(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    old = "def target():\n    stale()\n"
    replacement = "def renamed():\n    fresh()\n"
    path.write_text("# gap\n" * 20 + old, encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    assert _edit(tool, "app.py", old, replacement).ok
    path.write_text(
        "def target():\n    unrelated()\n" + "# gap\n" * 18 + replacement,
        encoding="utf-8",
    )
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "was last found (line 21)" in error
    assert "    21\tdef renamed():" in error
    assert "unrelated()" not in error


@pytest.mark.parametrize("through_tool", [False, True])
def test_changed_replacement_keeps_its_anchor_when_an_unrelated_first_line_appears(
    tmp_path: Path, through_tool: bool
) -> None:
    path = tmp_path / "app.py"
    old = "def target():\n    stale()\n"
    path.write_text("# gap\n" * 20 + old, encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    assert _edit(tool, "app.py", old, "def renamed():\n    fresh()\n").ok
    current = "def target():\n    unrelated()\n" + "# gap\n" * 18 + "def renamed():\n    newer()\n"
    if through_tool:
        assert _edit(tool, "app.py", path.read_text(encoding="utf-8"), current).ok
    else:
        path.write_text(current, encoding="utf-8")
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "was last found (line 21)" in error
    assert "    21\tdef renamed():" in error
    assert "    22\t    newer()" in error
    assert "unrelated()" not in error


def test_unique_first_line_recovers_after_duplicate_full_matches(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    old = "def target():\n    stale()\n"
    path.write_text("# gap\n" * 12 + old + "footer\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    assert _edit(tool, "app.py", old, "renamed\n    fresh()\n").ok
    path.write_text(old + "# gap\n" * 10 + old + "footer\n", encoding="utf-8")
    assert _edit(tool, "app.py", "footer", "changed footer").ok
    path.write_text("# moved\n" * 25 + "def target():\n    current()\n", encoding="utf-8")
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "was last found (line 26)" in error
    assert "    26\tdef target():" in error
    assert "    27\t    current()" in error


def test_successful_whitespace_fallback_remembers_original_search_location(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    old = "def target():\n    stale()\n"
    path.write_text("# gap\n" * 12 + "def target():  \n    stale()\t\nfooter\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    assert _edit(tool, "app.py", old, "renamed\n    fresh()\n").ok
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "was last found (line 13)" in error
    assert "    13\trenamed" in error
    assert "    14\t    fresh()" in error


@pytest.mark.parametrize("prefix_lines", [0, 25])
@pytest.mark.parametrize("replacement", ["if enabled:\n    current()\n", "renamed\n    fresh()\n"])
def test_unique_first_line_can_move_after_a_successful_ambiguous_match(
    tmp_path: Path, replacement: str, prefix_lines: int
) -> None:
    path = tmp_path / "app.py"
    old = "if enabled:\n    stale()\n"
    path.write_text("if enabled:\n    unrelated()\n" + "# gap\n" * 10 + old, encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    assert _edit(tool, "app.py", old, replacement).ok
    path.write_text("# moved\n" * prefix_lines + "if enabled:\n    fresh()\n" + "# padding\n" * 40, encoding="utf-8")
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    anchor = prefix_lines + 1
    assert f"was last found (line {anchor})" in error
    assert f"{anchor:6d}\tif enabled:" in error
    assert f"{anchor + 1:6d}\t    fresh()" in error


def test_initial_duplicate_first_lines_are_only_a_hint(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text(
        "if enabled:\n    unrelated()\n" + "# gap\n" * 10 + "if enabled:\n    current()\n", encoding="utf-8"
    )
    tool = CreateDiffTool(tmp_path)
    old = "if enabled:\n    stale()\n"
    _edit(tool, "app.py", old)
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "had its closest match" in error
    assert "was last found" not in error


def test_duplicate_first_lines_do_not_replace_a_known_anchor(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("# gap\n" * 10 + "if enabled:\n    current()\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = "if enabled:\n    stale()\n"
    assert not _edit(tool, "app.py", old).ok
    path.write_text(
        "if enabled:\n    unrelated()\n" + "# gap\n" * 8 + "if enabled:\n    fresh()\n",
        encoding="utf-8",
    )
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "last found (line 11)" in error
    assert "    12\t    fresh()" in error
    assert "unrelated()" not in error


def test_unique_first_line_after_ambiguity_refreshes_the_anchor(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    old = "if enabled:\n    stale()\n"
    tool = CreateDiffTool(tmp_path)
    path.write_text("# gap\n" * 10 + "if enabled:\n    current()\n", encoding="utf-8")
    _edit(tool, "app.py", old)
    path.write_text("if enabled:\n    a()\nif enabled:\n    b()\n", encoding="utf-8")
    _edit(tool, "app.py", old)
    path.write_text("# moved\n" * 25 + "if enabled:\n    fresh()\n", encoding="utf-8")
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "last found (line 26)" in error
    assert "    27\t    fresh()" in error


def test_duplicate_first_lines_without_history_are_only_a_closest_match(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("if enabled:\n    unrelated()\nif enabled:\n    current()\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = "if enabled:\n    stale()\n"
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "had its closest match" in error
    assert "was last found" not in error


@pytest.mark.parametrize("current", ["short\n", ""])
def test_remembered_context_handles_a_shrunk_or_empty_file(tmp_path: Path, current: str) -> None:
    path = tmp_path / "app.py"
    path.write_text("header\n" * 20 + "def target():\n    current()\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = "def target():\n    stale()\n"
    assert not _edit(tool, "app.py", old).ok
    path.write_text(current, encoding="utf-8")
    error = _assert_reread(_edit(tool, "app.py", old))
    if current:
        assert "     1\tshort" in error
    else:
        assert "file is empty" in error


def test_no_known_anchor_still_requires_a_read_and_shows_current_content(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("x = 1\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = "completely different\n"
    assert not _edit(tool, "app.py", old).ok
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "     1\tx = 1" in error
    assert "No previous location" in error


def test_fuzzy_anchor_survives_when_the_similar_line_is_removed(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("header\n\ndef target(port):\n    current()\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = "def target():\n    stale()\n"
    assert not _edit(tool, "app.py", old).ok
    path.write_text("header\n\nrenamed completely\n    fresh()\n", encoding="utf-8")
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "     3\trenamed completely" in error


def test_a_restored_string_can_still_be_edited_after_repeat_misses(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("current\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = "stale\n"
    assert not _edit(tool, "app.py", old).ok
    _assert_reread(_edit(tool, "app.py", old))
    path.write_text(old, encoding="utf-8")
    assert _edit(tool, "app.py", old, "fresh\n").ok
    assert path.read_text(encoding="utf-8") == "fresh\n"


def test_location_updates_when_first_line_moves_then_disappears(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("header\ndef target():\n    current()\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = "def target():\n    stale()\n"
    _edit(tool, "app.py", old)
    path.write_text("prefix\n" * 8 + "def target():\n    moved()\n", encoding="utf-8")
    _assert_reread(_edit(tool, "app.py", old))
    path.write_text("prefix\n" * 8 + "def renamed():\n    latest()\n", encoding="utf-8")
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "was last found (line 9)" in error and "def renamed():" in error


def test_other_edit_remembers_location_before_removing_first_line(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("header\n" * 8 + "def target():\n    current()\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    stale = "def target():\n    stale()\n"
    _edit(tool, "app.py", stale)
    moved = "prefix\n" * 20 + "def target():\n    current()\n"
    path.write_text(moved, encoding="utf-8")
    assert _edit(tool, "app.py", "def target():", "def renamed():").ok
    error = _assert_reread(_edit(tool, "app.py", stale))
    assert "was last found (line 21)" in error and "def renamed():" in error


def test_reused_registry_scopes_misses_to_runner_run(tmp_path: Path) -> None:
    from tests.test_agent_loop_tool_exec import _LoopStub, _run_execute_tools
    from thomas.tools.registry import ToolRegistry

    path = tmp_path / "app.py"
    path.write_text("current\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(CreateDiffTool(tmp_path))
    loops = {run: _LoopStub(autonomy_level=4, runner=None) for run in ("run-a", "run-b")}
    for run, loop in loops.items():
        loop.tools = registry
        loop._run_id = run
    call = [
        {
            "id": "edit",
            "name": "diff.create",
            "arguments": {
                "file": "app.py",
                "old_str": "stale\n",
                "new_str": "fresh\n",
            },
        }
    ]

    def miss(run: str) -> str:
        events = asyncio.run(_run_execute_tools(loops[run], call))
        return str(events[-1].data["result_text"])

    assert "must read it again" not in miss("run-a")
    assert "must read it again" not in miss("run-b")
    assert "must read it again" in miss("run-a")
    assert "must read it again" in miss("run-b")
    assert active_session_id() == ""


def test_top_level_runs_reset_history_but_quality_retries_keep_it(tmp_path: Path, monkeypatch) -> None:
    import thomas.agent.loop as loop_module
    from tests.test_agent_loop_tool_exec import _LoopStub, _run_execute_tools
    from thomas.tools.registry import ToolRegistry

    (tmp_path / "app.py").write_text("current\n", encoding="utf-8")
    registry = ToolRegistry()
    registry.register(CreateDiffTool(tmp_path))
    loop = _LoopStub(autonomy_level=4, runner=None)
    loop.tools = registry
    call = [
        {
            "id": "edit",
            "name": "diff.create",
            "arguments": {
                "file": "app.py",
                "old_str": "stale\n",
                "new_str": "fresh\n",
            },
        }
    ]

    async def run_one_edit(owner, prompt, **kwargs):
        for event in await _run_execute_tools(owner, call):
            yield event
        if prompt == "retry":
            async for event in loop_module.AgentLoop.run(owner, "nested", _quality_retry_count=1):
                yield event

    monkeypatch.setattr(loop_module, "_agent_loop_run", run_one_edit)

    async def scenario():
        first = [event async for event in loop_module.AgentLoop.run(loop, "first")]
        second = [event async for event in loop_module.AgentLoop.run(loop, "retry")]
        return first, second

    first, second = asyncio.run(scenario())
    assert "must read it again" not in str(first[-1].data["result_text"])
    assert "must read it again" not in str(second[0].data["result_text"])
    assert "must read it again" in str(second[-1].data["result_text"])


def test_ambiguous_anchor_stays_approximate_when_first_line_disappears(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("if enabled:\n    one()\nif enabled:\n    two()\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    old = "if enabled:\n    stale()\n"
    _edit(tool, "app.py", old)
    path.write_text("# changed\n    one()\n# changed\n    two()\n", encoding="utf-8")
    error = _assert_reread(_edit(tool, "app.py", old))
    assert "had its closest match" in error
    assert "around line 1 (last found" not in error


def test_runner_owns_history_and_releases_it_with_the_run(tmp_path: Path) -> None:
    import gc
    import weakref
    from types import SimpleNamespace

    from thomas.core.session_scope import active_tool_state

    path = tmp_path / "app.py"
    path.write_text("current\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    owner = SimpleNamespace()
    with bind_session("chat", run_id="run-a", run_owner=owner):
        _edit(tool, "app.py", "stale\n")
        history = weakref.ref(active_tool_state()[tool])
    with bind_session("chat", run_id="run-a", run_owner=owner):
        _assert_reread(_edit(tool, "app.py", "stale\n"))
    assert active_tool_state() is None
    assert not tool._direct_history.misses
    with bind_session("chat", run_id="run-b", run_owner=owner):
        assert "must read it again" not in str(_edit(tool, "app.py", "stale\n").error)
    gc.collect()
    assert history() is None
    with bind_session("chat", run_id="run-b", run_owner=owner):
        second_history = weakref.ref(active_tool_state()[tool])
    del owner
    gc.collect()
    assert second_history() is None


def test_unowned_run_scope_preserves_misses_then_releases_history(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("current\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    with bind_session("chat", run_id="outer"):
        _edit(tool, "app.py", "stale\n")
        for run in range(30):
            with bind_session("chat", run_id=f"run-{run}"):
                assert "must read it again" not in str(_edit(tool, "app.py", "stale\n").error)
                _assert_reread(_edit(tool, "app.py", "stale\n"))
        _assert_reread(_edit(tool, "app.py", "stale\n"))
    assert not tool._direct_history.misses


def test_nested_run_binding_restores_history(tmp_path: Path) -> None:
    path = tmp_path / "app.py"
    path.write_text("current\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    with bind_session("chat-a", run_id="run-a"):
        _edit(tool, "app.py", "stale\n")
        with bind_session("chat-a", run_id="run-a"):
            _assert_reread(_edit(tool, "app.py", "stale\n"))
        with bind_session("chat-b", run_id="run-b"):
            assert "must read it again" not in str(_edit(tool, "app.py", "stale\n").error)
        _assert_reread(_edit(tool, "app.py", "stale\n"))


def test_nested_owned_run_preserves_history_on_later_calls(tmp_path: Path) -> None:
    from types import SimpleNamespace

    (tmp_path / "app.py").write_text("current\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    owner = SimpleNamespace()
    with bind_session("chat", run_id="outer", run_owner=owner):
        assert "must read it again" not in str(_edit(tool, "app.py", "stale\n").error)
        with bind_session("chat", run_id="inner", run_owner=owner):
            assert "must read it again" not in str(_edit(tool, "app.py", "stale\n").error)
            _assert_reread(_edit(tool, "app.py", "stale\n"))
    with bind_session("chat", run_id="outer", run_owner=owner):
        _assert_reread(_edit(tool, "app.py", "stale\n"))
    with bind_session("chat", run_id="next", run_owner=owner):
        assert "must read it again" not in str(_edit(tool, "app.py", "stale\n").error)


@pytest.mark.parametrize("owned", [False, True])
def test_session_only_binding_keeps_the_enclosing_run_history(tmp_path: Path, owned: bool) -> None:
    from types import SimpleNamespace

    (tmp_path / "app.py").write_text("current\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    owner = SimpleNamespace() if owned else None
    with bind_session("chat", run_id="outer", run_owner=owner):
        _edit(tool, "app.py", "stale\n")
        with bind_session("nested-chat"):
            assert active_session_id() == "nested-chat"
            _assert_reread(_edit(tool, "app.py", "stale\n"))
        assert active_session_id() == "chat"
    assert not tool._direct_history.misses


@pytest.mark.parametrize("owned", [False, True])
def test_reentering_an_outer_run_keeps_its_history(tmp_path: Path, owned: bool) -> None:
    from types import SimpleNamespace

    (tmp_path / "app.py").write_text("current\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    owner = SimpleNamespace() if owned else None
    with bind_session("chat", run_id="outer", run_owner=owner):
        _edit(tool, "app.py", "stale\n")
        with bind_session("chat", run_id="inner", run_owner=owner):
            assert "must read it again" not in str(_edit(tool, "app.py", "stale\n").error)
            with bind_session("chat", run_id="outer", run_owner=owner):
                _assert_reread(_edit(tool, "app.py", "stale\n"))
            _assert_reread(_edit(tool, "app.py", "stale\n"))
        _assert_reread(_edit(tool, "app.py", "stale\n"))
    if owned:
        with bind_session("chat", run_id="outer", run_owner=owner):
            _assert_reread(_edit(tool, "app.py", "stale\n"))


@pytest.mark.parametrize("replacement", ["value = 2\n    fresh()\n", ""])
def test_partial_line_replacement_preserves_the_anchor(tmp_path: Path, replacement: str) -> None:
    path = tmp_path / "app.py"
    old = "value = 1\n    stale()\n"
    path.write_text("# gap\n" * 20 + "    " + old + "footer\n", encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    assert _edit(tool, "app.py", old, replacement).ok
    content = path.read_text(encoding="utf-8")
    path.write_text(content.replace("# gap\n" * 2, "value = 1\nunrelated()\n", 1), encoding="utf-8")

    _edit(tool, "app.py", old)
    error = _assert_reread(_edit(tool, "app.py", old))

    assert "first nonblank line was last found (line 21)" in error
    assert "unrelated()" not in error


@pytest.mark.parametrize("via_tool", [False, True])
@pytest.mark.parametrize("footer", ["", "footer\n"])
def test_moved_replacement_keeps_unrelated_match_from_stealing_anchor(
    tmp_path: Path, via_tool: bool, footer: str
) -> None:
    path = tmp_path / "app.py"
    prefix = "# gap\n" * 20
    old = "def target():\n    stale()\n"
    path.write_text(prefix + old + footer, encoding="utf-8")
    tool = CreateDiffTool(tmp_path)
    assert _edit(tool, "app.py", old, "def renamed():\n    fresh()\n").ok
    unrelated = "def target():\n    unrelated()\n"
    if via_tool:
        assert _edit(tool, "app.py", prefix, unrelated + prefix).ok
    else:
        path.write_text(unrelated + path.read_text(encoding="utf-8"), encoding="utf-8")
    if footer:
        path.write_text(path.read_text(encoding="utf-8").replace(footer, "changed footer\n"), encoding="utf-8")

    _edit(tool, "app.py", old)
    error = _assert_reread(_edit(tool, "app.py", old))

    assert "first nonblank line was last found (line 23)" in error
    assert "def renamed():" in error
    assert "unrelated()" not in error


def test_missing_file_and_ambiguous_matches_do_not_count_as_absent_text(tmp_path: Path) -> None:
    tool = CreateDiffTool(tmp_path)
    old = "stale\n"
    assert "File not found" in str(_edit(tool, "app.py", old).error)
    path = tmp_path / "app.py"
    path.write_text(old * 2, encoding="utf-8")
    assert "2 times" in str(_edit(tool, "app.py", old).error)
    path.write_text("current\n", encoding="utf-8")
    assert "must read it again" not in str(_edit(tool, "app.py", old).error)
    _assert_reread(_edit(tool, "app.py", old))
