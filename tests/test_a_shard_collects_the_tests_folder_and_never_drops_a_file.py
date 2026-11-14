"""A check's shard collects the tests folder with a selection file, and a named file with no case fails it.

Spec 2026-10-12 Part 1 item 7: each named file costs about 1 s to collect, so a shard passes the tests folder and a
selection file that fast_tests_plugin reads, loaded from the bytes of the running server's own copy as it started,
never from the copy under test; and a shard fails when a file it named has no test case in its JUnit report
(scripts/fast_tests.py's never-drop rule, rebuilt on JUnit). Folder mode is opt-in, so the ratchet's commands are
unchanged.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from thomas.server.proof import junit, runner
from thomas.server.proof.environment import sandbox_env


def _value(command: list[str], prefix: str) -> str:
    return next((arg[len(prefix) :] for arg in command if arg.startswith(prefix)), "")


def _write(work: Path, files: list[str]) -> list[str]:
    for rel in files:
        (work / rel).parent.mkdir(parents=True, exist_ok=True)
        (work / rel).write_text("def test_ok():\n    pass\n", encoding="utf-8")
    return files


def _tree(work: Path, count: int) -> list[str]:
    return _write(work, [f"tests/test_{n}.py" for n in range(count)])


def _fake(*, skip: tuple[str, ...] = (), code: int = 0, write: bool = True, calls: list | None = None):
    """Stands in for pytest: one case per file it was asked for (by selection file or by name), less *skip*."""

    def run(command: list[str], *, cwd: Path, env: dict, timeout_s: float) -> tuple[int, str]:
        if calls is not None:
            calls.append((list(command), dict(env)))
        if not write:
            return code, "Timeout"
        chosen = _value(command, runner.SELECT_OPTION + "=")
        if chosen:
            listed = json.loads(Path(chosen).read_text(encoding="utf-8"))["files"]
            files = [Path(path).relative_to(cwd).as_posix() for path in listed]
        else:
            files = [arg for arg in command[3:] if arg.endswith(".py")]
        cases = "".join(
            f'<testcase classname="{rel[:-3].replace("/", ".")}" name="test_ok" file="{rel}"/>'
            for rel in files
            if rel not in skip
        )
        Path(_value(command, "--junit-xml=")).write_text(f"<testsuite>{cases}</testsuite>", encoding="utf-8")
        return code, ""

    return run


def test_a_folder_shard_names_the_tests_folder_and_selects_exactly_its_own_files(tmp_path: Path) -> None:
    files, calls = _tree(tmp_path, 5), []

    result = runner.run_tests(tmp_path, files, python=sys.executable, data_dir=tmp_path / "d", shard_files=2,
                              folder=True, run=_fake(calls=calls))  # fmt: skip

    assert len(calls) == 3 and all(command[-1] == "tests" for command, _env in calls)
    assert not any(arg in files for command, _env in calls for arg in command), "no file is passed by name"
    batches = [files[0:2], files[2:4], files[4:5]]
    for (command, _env), batch in zip(calls, batches):
        listed = json.loads(Path(_value(command, runner.SELECT_OPTION + "=")).read_text(encoding="utf-8"))
        assert listed == {"files": [str(tmp_path.absolute() / rel) for rel in batch], "dirs": []}
    assert result.ran and result.seen == 5 and result.unrun == ()


def test_the_plugin_is_the_running_servers_own_file_and_never_the_copys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files, calls = _tree(tmp_path, 1), []
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "fast_tests_plugin.py").write_text("MARK = 'copy'\n", encoding="utf-8")
    (tmp_path / "fast_tests_plugin.py").write_text("MARK = 'copy root'\n", encoding="utf-8")
    monkeypatch.setenv("FAST_TESTS_SELECT", str(tmp_path / "elsewhere.json"))

    runner.run_tests(
        tmp_path, files, python=sys.executable, data_dir=tmp_path / "d", folder=True, run=_fake(calls=calls)
    )

    [(command, env)] = calls
    server_file = Path(runner.__file__).resolve().parents[3] / "scripts" / "fast_tests_plugin.py"
    assert server_file == runner.PLUGIN_FILE and not runner.PLUGIN_FILE.is_relative_to(tmp_path)
    pinned = tmp_path / "d" / "plugin" / hashlib.sha256(runner.PLUGIN_FILE.read_bytes()).hexdigest()[:16]
    assert command[1:4] == ["-c", runner._BOOT, str(pinned)]
    assert (pinned / "fast_tests_plugin.py").read_bytes() == runner.PLUGIN_FILE.read_bytes()
    assert not any(a == "-p" and b == "fast_tests_plugin" for a, b in zip(command, command[1:]))
    assert env["PYTHONPATH"] == str(tmp_path)
    assert not [key for key in env if key.upper().startswith("FAST_TESTS_")], "a selection never rides the environment"


def test_the_plugin_is_the_one_this_server_started_with(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    started_with = runner.PLUGIN_FILE.read_bytes()
    edited = tmp_path / "server" / "scripts" / "fast_tests_plugin.py"
    edited.parent.mkdir(parents=True)
    edited.write_text("raise ImportError('a plugin that landed after this server started')\n", encoding="utf-8")
    monkeypatch.setattr(runner, "PLUGIN_FILE", edited)  # the server's file, changed on disk after the import
    work = tmp_path / "work"
    files, calls = _tree(work, 1), []

    runner.run_tests(work, files, python=sys.executable, data_dir=tmp_path / "d", folder=True, run=_fake(calls=calls))

    [(command, _env)] = calls
    folder = Path(command[3])
    assert folder.name == hashlib.sha256(started_with).hexdigest()[:16]
    assert (folder / "fast_tests_plugin.py").read_bytes() == started_with, "a check uses the plugin it started with"


def test_a_named_file_with_no_case_in_its_report_fails_its_shard(tmp_path: Path) -> None:
    files = _tree(tmp_path, 3)

    result = runner.run_tests(tmp_path, files, python=sys.executable, data_dir=tmp_path / "d", folder=True,
                              run=_fake(skip=("tests/test_1.py",)))  # fmt: skip

    assert not result.ran and result.unrun == ("tests/test_1.py",)
    assert "tests/test_1.py" in result.why and result.failed == ()


def test_a_folder_shard_that_left_no_report_fails_even_when_pytest_exits_1(tmp_path: Path) -> None:
    files = _tree(tmp_path, 5)

    result = runner.run_tests(tmp_path, files, python=sys.executable, data_dir=tmp_path / "d", folder=True,
                              run=_fake(code=1, write=False))  # fmt: skip

    assert not result.ran and result.unrun == tuple(files), "pytest-timeout's os._exit(1) leaves no report"


def test_a_batch_the_folder_cannot_hold_still_names_its_files(tmp_path: Path) -> None:
    files, calls = _write(tmp_path, ["tests/helper_check.py", "other/test_x.py"]), []

    runner.run_tests(tmp_path, files, python=sys.executable, data_dir=tmp_path / "d", shard_files=1, folder=True,
                     run=_fake(calls=calls))  # fmt: skip

    assert calls, "the shards ran"
    assert len(calls) == len(files), "one shard per file, so the zip below pairs every command with its file"
    for (command, _env), rel in zip(calls, files):
        assert command[1:3] == ["-m", "pytest"] and command[-1] == rel
        assert not _value(command, runner.SELECT_OPTION + "=")


def test_without_the_servers_plugin_file_a_shard_names_its_files_and_still_never_drops_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(runner, "_PLUGIN", None)  # the server's own file could not be read when it started
    files, calls = _tree(tmp_path, 2), []

    result = runner.run_tests(tmp_path, files, python=sys.executable, data_dir=tmp_path / "d", folder=True,
                              run=_fake(skip=("tests/test_0.py",), calls=calls))  # fmt: skip

    assert calls[0][0][1:3] == ["-m", "pytest"] and calls[0][0][-2:] == files
    assert not result.ran and result.unrun == ("tests/test_0.py",)


def test_folder_mode_is_off_by_default_so_the_ratchets_command_is_unchanged(tmp_path: Path) -> None:
    files, calls = _tree(tmp_path, 2), []

    result = runner.run_tests(tmp_path, files, python=sys.executable, data_dir=tmp_path / "d",
                              run=_fake(calls=calls))  # fmt: skip

    report = tmp_path / "d" / "reports" / "shard-1.xml"
    assert len(calls) == 1
    assert calls[0][0] == [
        sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "-q", "--no-header", f"--rootdir={tmp_path}",
        "-o", "addopts=", "-o", "junit_family=xunit1", "--continue-on-collection-errors", f"--junit-xml={report}",
        *files,
    ]  # fmt: skip
    assert result.ran and result.seen == len(files) and not result.unrun


def test_a_case_counts_for_the_file_that_collected_it_not_the_file_that_defined_it(tmp_path: Path) -> None:
    report = tmp_path / "r.xml"
    report.write_text(
        "<testsuite>"
        '<testcase classname="tests.test_inherits.TestX" name="test_a" file="tests/_base.py"/>'
        '<testcase classname="" name="tests.test_skipped"><skipped/></testcase>'
        '<testcase classname="tests.test_x_more" name="test_b" file="tests/test_x_more.py"/>'
        "</testsuite>",
        encoding="utf-8",
    )
    read = junit.read_report(report, tmp_path)
    assert read is not None
    named = ["tests/test_inherits.py", "tests/test_skipped.py", "tests/test_x.py", "tests/test_x_more.py"]

    assert junit.without_cases(read, named) == ("tests/test_x.py",)


def _real_tree(work: Path) -> list[str]:
    tests = work / "tests"
    (tests / "sub").mkdir(parents=True)
    files = {
        "__init__.py": "",
        "conftest.py": "import pytest\n\n\n@pytest.fixture\ndef one():\n    return 1\n",
        "test_plain.py": "import pytest\n\n\ndef test_a(one):\n    assert one == 1\n\n\n"
        "@pytest.mark.parametrize('n', [1, 2])\ndef test_b(n):\n    assert n\n",
        "test_class.py": "class TestThing:\n    def test_x(self):\n        assert True\n\n    def test_y(self):\n"
        "        assert True\n",
        "sub/__init__.py": "",
        "sub/conftest.py": "",
        "sub/test_deep.py": "def test_deep():\n    assert True\n",
        "test_skipped_module.py": "import pytest\n\npytest.skip('not here', allow_module_level=True)\n",
        "test_broken.py": "import a_module_that_is_not_there\n",
        "test_not_selected.py": "def test_never():\n    assert False\n",
    }
    for rel, text in files.items():
        (tests / rel).write_text(text, encoding="utf-8")
    return ["tests/test_plain.py", "tests/test_class.py", "tests/sub/test_deep.py", "tests/test_skipped_module.py",
            "tests/test_broken.py"]  # fmt: skip


def test_folder_collection_finds_the_same_test_ids_as_file_by_file_collection(tmp_path: Path) -> None:
    files = _real_tree(tmp_path)
    seen = {}
    for folder in (False, True):
        data = tmp_path / f"data-{folder}"
        result = runner.run_tests(tmp_path, files, python=sys.executable, data_dir=data, timeout_s=300.0, folder=folder)
        assert result.ran, result.why
        assert result.failed == ("tests/test_broken.py",)
        read = junit.read_report(data / "reports" / "shard-1.xml", tmp_path)
        assert read is not None
        seen[folder] = set(read.seen)
    assert seen[False] == seen[True] and len(seen[True]) == 8
    assert not any(test.startswith("tests/test_not_selected.py") for test in seen[True])


def test_a_selected_file_the_folder_run_ignores_fails_its_shard_and_file_arguments_still_run_it(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "conftest.py").write_text('collect_ignore = ["test_hidden.py"]\n', encoding="utf-8")
    for name in ("test_hidden.py", "test_seen.py"):
        (tmp_path / "tests" / name).write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    files = ["tests/test_hidden.py", "tests/test_seen.py"]

    folder = runner.run_tests(tmp_path, files, python=sys.executable, data_dir=tmp_path / "f", timeout_s=300.0,
                              folder=True)  # fmt: skip
    named = runner.run_tests(tmp_path, files, python=sys.executable, data_dir=tmp_path / "n", timeout_s=300.0)

    assert not folder.ran and folder.unrun == ("tests/test_hidden.py",)
    assert named.ran and named.seen == 2


def test_the_copys_own_tests_import_the_copys_plugin_and_the_servers_is_the_one_registered(tmp_path: Path) -> None:
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "scripts" / "fast_tests_plugin.py").write_text(
        "MARK = 'copy'\n\n\ndef pytest_ignore_collect(collection_path, config):\n    return True\n", encoding="utf-8"
    )
    (tmp_path / "fast_tests_plugin.py").write_text("raise ImportError('never the plugin')\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_which.py").write_text(
        "import os\nimport sys\nfrom pathlib import Path\n\n\n"
        "def test_which(request):\n"
        "    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))\n"
        "    try:\n        import fast_tests_plugin\n    finally:\n        sys.path.pop(0)\n"
        "    assert fast_tests_plugin.MARK == 'copy'\n"
        "    names = [str(getattr(p, '__file__', '')) for p in request.config.pluginmanager.get_plugins()]\n"
        "    Path(os.environ['THOMAS_DATA_DIR'], 'plugins.txt').write_text('\\n'.join(names), encoding='utf-8')\n",
        encoding="utf-8",
    )
    data = tmp_path / "data"

    result = runner.run_tests(tmp_path, ["tests/test_which.py"], python=sys.executable, data_dir=data,
                              timeout_s=300.0, folder=True)  # fmt: skip

    assert result.ran and result.failed == () and result.seen == 1, result.why
    pinned = data / "plugin" / hashlib.sha256(runner.PLUGIN_FILE.read_bytes()).hexdigest()[:16] / "fast_tests_plugin.py"
    test_data = Path(sandbox_env(tmp_path, data)["THOMAS_DATA_DIR"])
    assert str(pinned) in (test_data / "plugins.txt").read_text(encoding="utf-8").splitlines()
