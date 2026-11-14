"""A long tool result keeps its end (where a test run's error is) and saves the rest."""

from __future__ import annotations

from pathlib import Path

from thomas.agent.loop_tool_protocol import _MAX_TOOL_RESULT_CHARS
from thomas.agent.tool_result_cap import cap_tool_result


def _pytest_output() -> str:
    body = "".join(f"tests/test_x.py::test_{n} PASSED\n" for n in range(2_000))
    return (
        "collected 2001 items\n"
        + body
        + "E   AssertionError: score was 0\nFAILED tests/test_x.py::test_score - 1 failed\n"
    )


def _cap(text: str, root: Path, tool: str = "shell.exec") -> str:
    return cap_tool_result(
        text, _MAX_TOOL_RESULT_CHARS, tool_name=tool, sandbox_root=root, run_id="run:abc", call_id="call_1"
    )


def test_the_end_of_a_long_result_survives_within_the_same_budget(tmp_path: Path) -> None:
    out = _cap(_pytest_output(), tmp_path)
    assert len(out) <= _MAX_TOOL_RESULT_CHARS
    assert out.startswith("collected 2001 items")
    assert "AssertionError: score was 0" in out and out.rstrip().endswith("1 failed")
    assert "chars omitted" in out


def test_the_full_output_is_saved_where_the_marker_says_and_the_line_range_is_right(tmp_path: Path) -> None:
    text = _pytest_output()
    out = _cap(text, tmp_path)
    rel = ".thomas/tool-output/run_abc/call_1.txt"
    assert f"path={rel}" in out
    assert (tmp_path / rel).read_text(encoding="utf-8") == text
    assert (tmp_path / ".thomas" / "tool-output" / ".gitignore").read_text(encoding="utf-8") == "*\n"
    first = int(out.split("start_line=")[1].split()[0])
    last = int(out.split("end_line=")[1].split(".")[0])
    lines = text.split("\n")
    head, _, rest = out.partition("\n\n[...")
    tail = rest.split("...]\n\n", 1)[1]
    # The lines cut at each edge are the first and last lines of the named range.
    assert head.split("\n")[-1] in lines[first - 1]
    assert tail.split("\n")[0] in lines[last - 1]


def test_short_results_are_unchanged_and_file_reads_point_back_at_the_file(tmp_path: Path) -> None:
    assert _cap("ok", tmp_path) == "ok"
    big = "".join(f"{n:>6}\tline {n}\n" for n in range(1, 3_000))
    out = _cap(big, tmp_path, tool="fs.read_file")
    assert "fs.read_file on the same path with start_line/end_line" in out
    assert "line 2999" in out
    assert not (tmp_path / ".thomas").exists()
