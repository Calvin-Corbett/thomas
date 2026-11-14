"""A change that only moves the version line runs the tests that read the version, not the whole suite.

Selection counts a changed package as reached through any submodule, so a change to thomas/__init__.py chose 1,992 of
2,085 test files, and teams change that file to bump the version. From 2026-10-21 to 10-29, 73% of the checks' test time
went to the 98 checks at the 360-file cap, and 10 of the 13 capped hand-ins with a file list carried that one line. One
fix to thomas/tools/shell.py chose 11 test files alone and 1,992 with its version bump, and selecting them took 75 times
as long. thomas/__init__.py also holds real code, so the file itself is never excused: only a diff that is nothing but
the version line.
"""

from __future__ import annotations

import contextlib

from tests.test_lazy_baseline_failures_are_held_and_cleaned import pipeline  # noqa: F401
from thomas.server.precard import check
from thomas.server.proof import Selection, selection

BUMP = """diff --git a/thomas/__init__.py b/thomas/__init__.py
index 1111111..2222222 100644
--- a/thomas/__init__.py
+++ b/thomas/__init__.py
@@ -3,7 +3,7 @@
 from __future__ import annotations

 # Release 0.19.0: security-reviewed local Chat, Code, and Work lifecycle checkpoint (2026-07-18).
-__version__ = "0.19.51"
+__version__ = "0.19.52"


 def _patch_typer_testing_for_click() -> None:
"""
PYPROJECT = """diff --git a/pyproject.toml b/pyproject.toml
index 1111111..2222222 100644
--- a/pyproject.toml
+++ b/pyproject.toml
@@ -1,6 +1,6 @@
 [project]
 name = "thomas"
-version = "0.19.51"
+version = "0.19.52"
 description = "x"
"""
CODE = """diff --git a/thomas/tools/shell.py b/thomas/tools/shell.py
index 1111111..2222222 100644
--- a/thomas/tools/shell.py
+++ b/thomas/tools/shell.py
@@ -1,2 +1,2 @@
-__version__ = "1"
+__version__ = "2"
"""
TESTS = {
    "tests/test_chat.py": "from thomas.server import app\n",
    "tests/test_shell.py": "from thomas.tools import shell\n",
    "tests/test_release.py": "import thomas\n\nassert thomas.__version__\n",
    "tests/test_packaging.py": 'import tomllib\n\nversion = tomllib.loads(open("pyproject.toml").read())["project"]["version"]\n',
    "tests/test_deps.py": 'text = open("pyproject.toml").read()\nassert "ruff" in text\n',
}


def test_a_diff_of_only_the_version_line_is_a_bump() -> None:
    assert selection.version_bumps(BUMP) == {"thomas/__init__.py"}
    assert selection.version_bumps(BUMP + PYPROJECT) == {"thomas/__init__.py", "pyproject.toml"}
    assert selection.version_bumps(BUMP.replace("\n", "\r\n")) == {"thomas/__init__.py"}


def test_anything_more_in_that_file_is_not_a_bump() -> None:
    more = BUMP.replace('+__version__ = "0.19.52"\n', '+__version__ = "0.19.52"\n+print("hello")\n')
    assert selection.version_bumps(more) == frozenset()
    shim = BUMP.replace('-__version__ = "0.19.51"\n+__version__ = "0.19.52"', "-import click\n+import typer")
    assert selection.version_bumps(shim) == frozenset()
    added = BUMP.replace('-__version__ = "0.19.51"\n', "")  # a second version line, not a move of the first
    assert selection.version_bumps(added) == frozenset()
    assert selection.version_bumps("") == frozenset()


def test_only_the_two_release_version_files_can_be_a_bump() -> None:
    assert selection.version_bumps(CODE) == frozenset()


def test_a_bump_chooses_the_tests_that_read_the_version_and_not_the_rest() -> None:
    bumps = {"thomas/__init__.py", "pyproject.toml"}
    changed = ["thomas/tools/shell.py", *sorted(bumps)]

    got = selection.select_from(TESTS, changed, bumps=bumps).files

    assert {"tests/test_shell.py", "tests/test_release.py", "tests/test_packaging.py"} <= set(got)
    assert "tests/test_chat.py" not in got  # only imports Thomas
    assert "tests/test_deps.py" not in got  # reads pyproject.toml, never its version


def test_without_a_proven_bump_a_change_to_the_package_still_reaches_everything() -> None:
    assert set(TESTS) - {"tests/test_deps.py", "tests/test_packaging.py"} <= set(
        selection.select_from(TESTS, ["thomas/__init__.py"]).files
    )


def test_the_check_selects_by_what_its_own_patch_proves_both_times(pipeline, monkeypatch) -> None:
    asked: list[object] = []

    def select(_work, _changed, **kwargs):
        asked.append(kwargs.get("bumps"))
        return Selection(("tests/test_value.py",), ())

    monkeypatch.setattr(check.proofs, "select", select)
    changed = ["thomas/tools/shell.py", "thomas/__init__.py"]

    check._against_dev(pipeline.green, "tip", BUMP + CODE, changed, "python", False)  # the tests it runs

    monkeypatch.setattr(check, "_against_dev", lambda *_a: check.Checked(check.PASSED, "checked"))
    monkeypatch.setattr(check.capacity_ledger, "admitted", lambda *_a, **_k: contextlib.nullcontext())
    monkeypatch.setattr(check.green_handoff, "dev_tip", lambda _eid: "tip")
    check._admitted(pipeline.green, "tip", BUMP + CODE, changed, "python")  # its size, for its place in line

    assert asked == [{"thomas/__init__.py"}, {"thomas/__init__.py"}]
