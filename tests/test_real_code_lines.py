"""What the soft line counts as a real code line, and what it leaves out.

Proves the dotted module ``scripts.forge.code_size``. The rule is written in that module's docstring; each test here is
one sentence of it, so a change to the rule fails the sentence it changes.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

from scripts.forge import code_size as cs


def count(source: str) -> int:
    return cs.real_code_lines(textwrap.dedent(source))


def test_blank_lines_and_comment_only_lines_do_not_count() -> None:
    assert count("# header\n\nx = 1\n\n    # note\ny = 2\n") == 2


def test_a_line_with_code_and_a_trailing_comment_counts() -> None:
    assert count("x = 1  # why\n") == 1


def test_a_docstring_does_not_count_on_any_line_it_spans() -> None:
    source = '''\
    """Module docs.

    More docs.
    """

    class A:
        """Class docs."""

        def f(self):
            """Function
            docs."""
            return 1
    '''
    assert count(source) == 3  # class A, def f, return 1


def test_a_string_in_a_body_that_is_not_a_docstring_counts_on_every_line() -> None:
    source = 'def f():\n    return """a\nb\nc"""\n'
    assert count(source) == 4


def test_a_multi_line_data_table_does_not_count_but_a_one_line_table_does() -> None:
    source = 'ROUTES = {\n    "a": 1,\n    "b": [1, 2],\n    "c": NAME,\n}\nONE = {"a": 1}\n'
    assert count(source) == 1


def test_a_multi_line_table_in_a_class_does_not_count() -> None:
    assert count("class A:\n    X = (\n        1,\n        2,\n    )\n") == 1


def test_a_multi_line_call_is_code_and_counts_on_every_line_that_holds_a_token() -> None:
    source = "value = compute(\n    1,\n    # between\n    2,\n)\n"
    assert count(source) == 4


def test_a_table_that_calls_a_function_is_code() -> None:
    assert count("X = {\n    'a': make(),\n}\n") == 3


def test_a_file_that_does_not_parse_counts_non_blank_lines_that_do_not_start_with_a_hash() -> None:
    assert count("def (:\n\n# note\n    x\n") == 2


def test_measure_lists_only_py_files_over_the_soft_line_and_under_the_hard_cap(tmp_path: Path) -> None:
    (tmp_path / "over.py").write_text("x = 1\n" * (cs.SOFT_REAL_CODE_LINES + 1), encoding="utf-8")
    (tmp_path / "exact.py").write_text("x = 1\n" * cs.SOFT_REAL_CODE_LINES, encoding="utf-8")
    (tmp_path / "hard.py").write_text("x = 1\n" * 900, encoding="utf-8")
    (tmp_path / "notes.js").write_text("x = 1;\n" * 900, encoding="utf-8")
    (tmp_path / "folder.py").mkdir()
    names = ["over.py", "exact.py", "hard.py", "notes.js", "folder.py", "missing.py"]
    assert cs.measure(tmp_path, names, cap=800) == {"over.py": cs.SOFT_REAL_CODE_LINES + 1}


def test_padding_with_blank_lines_does_not_hide_a_file_that_is_real_code() -> None:
    padded = "x = 1\n\n" * 400
    assert cs.real_code_lines(padded) == 400


def test_judge_names_a_new_crossing_with_its_count_the_cap_and_the_remedy() -> None:
    (message,) = cs.judge({"a.py": 705}, {}, 800)
    assert "a.py" in message and "705" in message and "800" in message and "by responsibility" in message


def test_judge_fails_on_growth_shrinkage_and_a_stale_line_and_passes_when_exact() -> None:
    assert cs.judge({"a.py": 710}, {"a.py": 710}, 800) == []
    assert "grew" in cs.judge({"a.py": 720}, {"a.py": 710}, 800)[0]
    assert "shrank" in cs.judge({"a.py": 705}, {"a.py": 710}, 800)[0]
    assert "no longer over" in cs.judge({}, {"a.py": 710}, 800)[0]


def test_lowering_never_adds_or_raises() -> None:
    assert cs.lowered({"a.py": 705, "b.py": 800, "new.py": 750}, {"a.py": 710, "b.py": 790, "gone.py": 720}) == {
        "a.py": 705,
        "b.py": 790,
    }
