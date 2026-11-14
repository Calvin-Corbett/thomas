"""The plugin a check pins is never a partial file, and a folder beside a named file never stands in for it.

Review of the folder-shard work (spec 2026-10-12 Part 1 item 7): a kill while the pinned copy was being written left a
truncated ``fast_tests_plugin.py`` that every later run in that data folder trusted (the selection was silently ignored
and the whole tests folder ran); ``tests/test_pkg/test_inner.py`` satisfied a named, empty ``tests/test_pkg.py`` because
its dotted module starts with the file's; and a selection file handed to a command with no plugin to read it was
dropped without a word.
"""

from __future__ import annotations

import hashlib
import logging
import sys
from pathlib import Path

import pytest

from thomas.server.proof import junit, runner


def _pinned(data: Path) -> Path:
    return data / "plugin" / hashlib.sha256(runner._PLUGIN).hexdigest()[:16] / "fast_tests_plugin.py"


def _seed(data: Path, content: bytes) -> Path:
    target = _pinned(data)
    target.parent.mkdir(parents=True)
    target.write_bytes(content)
    return target


def _write(work: Path, files: dict[str, str]) -> list[str]:
    for rel, text in files.items():
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text(text, encoding="utf-8")
    return list(files)


def test_a_pinned_plugin_cut_off_before_its_ignore_hook_cannot_silently_widen_the_run(tmp_path: Path) -> None:
    work = tmp_path / "work"
    files = _write(work, {"tests/test_a.py": "def test_a():\n    assert True\n",
                          "tests/test_other.py": "def test_other():\n    assert False\n"})  # fmt: skip
    target = _seed(tmp_path / "d", runner._PLUGIN[: runner._PLUGIN.index(b"def pytest_ignore_collect")])

    result = runner.run_tests(work, files[:1], python=sys.executable, data_dir=tmp_path / "d", timeout_s=300.0,
                              folder=True)  # fmt: skip

    assert result.ran and result.seen == 1 and result.failed == (), "tests/test_other.py was not collected"
    assert target.read_bytes() == runner._PLUGIN
    assert list(target.parent.iterdir()) == [target], "no temporary copy is left beside it"


@pytest.mark.parametrize("seeded", ["empty", "half", "one byte short", "other bytes"])
def test_any_pinned_copy_that_is_not_the_servers_bytes_is_replaced(tmp_path: Path, seeded: str) -> None:
    content = {"empty": b"", "half": runner._PLUGIN[: len(runner._PLUGIN) // 2], "one byte short": runner._PLUGIN[:-1],
               "other bytes": b"raise ImportError('not the plugin')\n"}[seeded]  # fmt: skip
    target = _seed(tmp_path / "d", content)

    assert runner.collect_plugin(tmp_path / "work", tmp_path / "d") == target

    assert target.read_bytes() == runner._PLUGIN
    assert list(target.parent.iterdir()) == [target]


def test_a_whole_pinned_copy_is_reused_and_not_rewritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    first = runner.collect_plugin(tmp_path / "work", tmp_path / "d")
    monkeypatch.setattr(runner.os, "replace", lambda *_a: pytest.fail("a whole copy was written over"))

    assert runner.collect_plugin(tmp_path / "work", tmp_path / "d") == first == _pinned(tmp_path / "d")


def test_a_plugin_that_cannot_be_written_means_files_by_name_and_a_log_line(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    data, calls = tmp_path / "d", []
    data.mkdir()
    (data / "plugin").write_text("a file where the plugin folder should go", encoding="utf-8")
    files = _write(tmp_path / "work", {"tests/test_0.py": "def test_ok():\n    pass\n"})

    def by_name(command: list[str], **_kwargs: object) -> tuple[int, str]:
        calls.append(command)
        report = next(arg for arg in command if arg.startswith("--junit-xml=")).split("=", 1)[1]
        case = '<testcase classname="tests.test_0" name="test_ok" file="tests/test_0.py"/>'
        Path(report).write_text(f"<testsuite>{case}</testsuite>", encoding="utf-8")
        return 0, ""

    with caplog.at_level(logging.WARNING):
        result = runner.run_tests(tmp_path / "work", files, python=sys.executable, data_dir=data, folder=True,
                                  run=by_name)  # fmt: skip

    assert result.ran and result.unrun == ()
    assert calls[0][1:3] == ["-m", "pytest"] and calls[0][-1] == files[0]
    assert any("plugin" in record.getMessage() for record in caplog.records)


def test_a_selection_without_a_plugin_to_read_it_is_refused_not_dropped(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        runner._pytest(sys.executable, tmp_path, tmp_path / "r.xml", ["tests"], select=tmp_path / "s.json")


def test_a_folder_beside_a_named_file_never_stands_in_for_it(tmp_path: Path) -> None:
    report = tmp_path / "r.xml"
    report.write_text(
        '<testsuite><testcase classname="tests.test_pkg.test_inner" name="test_ok" file="tests/test_pkg/test_inner.py"/>'
        '<testcase classname="tests.test_class.TestThing" name="test_x" file="tests/test_class.py"/></testsuite>',
        encoding="utf-8",
    )
    read = junit.read_report(report, tmp_path)
    assert read is not None

    named = ["tests/test_pkg.py", "tests/test_pkg/test_inner.py", "tests/test_class.py"]
    assert junit.without_cases(read, named) == ("tests/test_pkg.py",)
    assert junit.without_cases(read, named[1:]) == (), "a class path still counts for its own module"
    assert junit.without_cases(read, ["tests/test_pkg", "tests/other"]) == ("tests/other",), (
        "a named folder holds its cases"
    )


def test_an_empty_file_named_beside_a_same_stem_folder_fails_its_shard(tmp_path: Path) -> None:
    files = _write(tmp_path, {"tests/test_pkg.py": "def helper():\n    pass\n",
                              "tests/test_pkg/test_inner.py": "def test_ok():\n    assert True\n"})  # fmt: skip

    result = runner.run_tests(tmp_path, files, python=sys.executable, data_dir=tmp_path / "d", timeout_s=300.0,
                              folder=True)  # fmt: skip

    assert not result.ran and result.unrun == ("tests/test_pkg.py",) and result.seen == 1
