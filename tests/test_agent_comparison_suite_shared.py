from __future__ import annotations

from pathlib import Path

from thomas.demo.agent_comparison_suite_shared import _count_python_syntax_errors


def test_count_python_syntax_errors_counts_invalid_files_without_raising(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "good.py").write_text("x = 1\n", encoding="utf-8")
    (src / "bad.py").write_text("def broken(\n", encoding="utf-8")

    assert _count_python_syntax_errors([src]) == 1


def test_count_python_syntax_errors_skips_monolith_part_fragments(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "loop_part02.py").write_text("    dangling_fragment = True\n", encoding="utf-8")

    assert _count_python_syntax_errors([src]) == 0
