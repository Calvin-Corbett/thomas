"""scripts/fast_tests.py: the opt-in fast runner keeps the same tests, picks workers from the machine, and says so."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import fast_tests  # noqa: E402
import fast_tests_capacity as capacity  # noqa: E402
import fast_tests_plugin as plugin  # noqa: E402

GB = capacity.GB


def _selection(tmp: Path, *, files: list[str], dirs: list[str] | None = None) -> dict:
    (tmp / "tests").mkdir(exist_ok=True)
    raw = {"files": [str(tmp / f) for f in files], "dirs": [str(tmp / d) for d in dirs or []]}
    path = tmp / "select.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    old, plugin._loaded, plugin._selection = os.environ.get(plugin.SELECT_ENV), False, None
    os.environ[plugin.SELECT_ENV] = str(path)
    try:
        return plugin._load_selection() or {}
    finally:
        os.environ.pop(plugin.SELECT_ENV, None)
        if old is not None:
            os.environ[plugin.SELECT_ENV] = old
        plugin._loaded, plugin._selection = False, None


def test_the_ignore_hook_keeps_listed_files_listed_folders_and_the_way_to_them(tmp_path: Path) -> None:
    sel = _selection(tmp_path, files=["tests/a/test_one.py", "tests/b/test_two.py"], dirs=["tests/whole"])
    keep = [
        tmp_path / "tests",
        tmp_path / "tests" / "a",
        tmp_path / "tests" / "a" / "test_one.py",
        tmp_path / "tests" / "whole" / "deep" / "test_any.py",
    ]
    drop = [
        tmp_path / "tests" / "a" / "test_other.py",
        tmp_path / "tests" / "c",
        tmp_path / "tests" / "web_node" / "page.html",
        tmp_path / "tests" / "web_node" / "probe.mjs",
    ]
    assert all(plugin.is_selected(p, sel, is_dir=p.suffix == "") for p in keep)
    assert not any(plugin.is_selected(p, sel, is_dir=p.suffix == "") for p in drop)


def test_a_named_harness_file_is_kept(tmp_path: Path) -> None:
    sel = _selection(tmp_path, files=["tests/web_node/page.html"])
    assert plugin.is_selected(tmp_path / "tests" / "web_node" / "page.html", sel, is_dir=False)


def test_the_selection_can_be_named_on_the_command_line_and_not_the_environment(tmp_path, monkeypatch) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_in.py").write_text("def test_in():\n    assert True\n", encoding="utf-8")
    (tmp_path / "tests" / "test_out.py").write_text("def test_out():\n    raise SystemExit(9)\n", encoding="utf-8")
    chosen = tmp_path / "select.json"
    chosen.write_text(json.dumps({"files": [str(tmp_path / "tests" / "test_in.py")], "dirs": []}), encoding="utf-8")
    monkeypatch.delenv(plugin.SELECT_ENV, raising=False)
    old = plugin._loaded, plugin._selection
    plugin._loaded, plugin._selection = False, None
    try:
        assert plugin._load_selection(str(chosen))["files"] == {plugin._norm(tmp_path / "tests" / "test_in.py")}
    finally:
        plugin._loaded, plugin._selection = old
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith(("FAST_TESTS_", "PYTEST_"))}
    env["PYTHONPATH"] = str(SCRIPTS)
    command = [sys.executable, "-m", "pytest", "-p", "fast_tests_plugin", f"{plugin.SELECT_OPTION}={chosen}",
               "-p", "no:cacheprovider", "-q", "tests"]  # fmt: skip
    done = subprocess.run(command, cwd=tmp_path, env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "1 passed" in done.stdout


@pytest.mark.parametrize(
    ("requested", "cpus", "total", "available", "files", "want"),
    [
        (None, 16, 32 * GB, 20 * GB, None, 8),
        (None, 16, 32 * GB, 10 * GB, None, None),
        (None, 16, 32 * GB, 5 * GB, None, 1),
        (None, 4, 32 * GB, 30 * GB, None, 2),
        (3, 16, 32 * GB, 30 * GB, None, 3),
        (None, 16, 32 * GB, 30 * GB, 2, 2),
        (None, 16, None, None, None, 8),
        (99, 16, 32 * GB, 30 * GB, None, 8),
    ],
)
def test_workers_never_exceed_ram_cpus_the_ask_or_the_work(requested, cpus, total, available, files, want) -> None:
    got, reason = capacity.pick_workers(requested, cpus=cpus, total=total, available=available, files=files)
    if want is None:  # the RAM-bound row: derive the expectation from the budget, not a magic number
        usable = available - max(capacity.RESERVE_FLOOR_BYTES, int(total * capacity.RESERVE_FRACTION))
        want = min(8, max(1, usable // capacity.PER_WORKER_BYTES))
    assert got == want
    assert reason


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args], cwd=repo, check=True, capture_output=True
    )


def test_the_tree_key_changes_with_any_edit_even_a_same_size_one(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "m.py").write_text("x = 1\n", encoding="utf-8")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "commit", "-q", "-m", "one")
    clean = capacity.tree_key(tmp_path)
    assert clean == capacity.tree_key(tmp_path)
    (tmp_path / "m.py").write_text("x = 2\n", encoding="utf-8")  # same size, same second
    edited = capacity.tree_key(tmp_path)
    (tmp_path / "new.py").write_text("y = 1\n", encoding="utf-8")
    with_new = capacity.tree_key(tmp_path)
    assert len({clean, edited, with_new}) == 3


def test_old_bytecode_folders_are_pruned_but_the_current_one_stays(tmp_path: Path) -> None:
    for index in range(capacity.KEEP_PREFIXES + 3):
        folder = tmp_path / "pyc" / f"k{index}"
        folder.mkdir(parents=True)
        os.utime(folder, (1000 + index, 1000 + index))
    gone = capacity.prune_prefixes(tmp_path, keep_name="k0")
    left = {p.name for p in (tmp_path / "pyc").iterdir()}
    assert "k0" in left and len(left) == capacity.KEEP_PREFIXES + 1 and "k0" not in gone


def _args(**kw) -> argparse.Namespace:
    base = {"targets": [], "n": None, "serial": False, "dir_threshold": 5, "no_pyc": False, "python": sys.executable}
    return argparse.Namespace(**{**base, **kw})


def test_a_handful_of_files_stay_file_arguments_and_many_become_a_directory(tmp_path: Path) -> None:
    mem = (32 * GB, 20 * GB)
    names = []
    for i in range(7):
        p = tmp_path / "tests" / f"test_{i}.py"
        p.parent.mkdir(exist_ok=True)
        p.write_text("def test_x():\n    pass\n", encoding="utf-8")
        names.append(str(p))
    few = fast_tests.build_plan(_args(targets=names[:3]), xdist=True, memory=mem)
    many = fast_tests.build_plan(_args(targets=names), xdist=True, memory=mem)
    assert few["mode"] == "args" and few["selection"] is None and len(few["argv"]) == 3
    assert many["mode"] == "dir+ignore" and many["argv"] == [str((tmp_path / "tests").resolve())]
    assert len(many["selection"]["files"]) == 7


def test_without_xdist_the_run_is_serial_and_says_why(tmp_path: Path) -> None:
    plan = fast_tests.build_plan(_args(targets=[str(tmp_path)]), xdist=False, memory=(32 * GB, 30 * GB))
    assert plan["workers"] == 1 and "xdist" in plan["workers_why"]
    cmd = fast_tests.pytest_command(_args(pytest_args=[]), plan)
    assert "-n" not in cmd and "fast_tests_plugin" in cmd and "no:cacheprovider" in cmd


def test_xdist_is_asked_for_only_when_it_is_there(tmp_path: Path) -> None:
    plan = fast_tests.build_plan(_args(targets=[str(tmp_path)], n=4), xdist=True, memory=(32 * GB, 30 * GB))
    cmd = fast_tests.pytest_command(_args(pytest_args=["-x"]), {**plan, "workers": 4})
    assert cmd[cmd.index("-n") + 1] == "4" and "worksteal" in cmd and cmd[-1] == "-x"


def test_a_deep_checkout_path_is_warned_about() -> None:
    assert capacity.short_root_warning(Path("C:/r/a")) is None
    warning = capacity.short_root_warning(Path("C:/" + "deep/" * 20))
    assert "short folder" in warning and "Filename too long" in warning
    # The advice must not send a caged Build team to a folder it cannot write.
    assert "C:\\r" not in warning


def _mini_project(root: Path) -> list[str]:
    tests = root / "tests"
    (tests / "sub").mkdir(parents=True)
    (tests / "sub" / "helper.py").write_text("VALUE = 41\n", encoding="utf-8")
    names = []
    for i in range(3):
        body = f"def test_pass_{i}():\n    assert 1 + {i} == {i} + 1\n"
        if i == 2:
            body += "\n\ndef test_fails_the_same_way_in_both_runs():\n    assert False\n"
        (tests / f"test_m{i}.py").write_text(body, encoding="utf-8")
        names.append(str(tests / f"test_m{i}.py"))
    (tests / "sub" / "test_h.py").write_text(
        "import os, sys\nsys.path.insert(0, os.path.dirname(__file__))\nimport helper\n\n"
        "def test_helper():\n    assert helper.VALUE == 41\n",
        encoding="utf-8",
    )
    (tests / "test_unselected.py").write_text("def test_never_runs():\n    raise SystemExit(9)\n", encoding="utf-8")
    (tests / "page.html").write_text("<html></html>", encoding="utf-8")
    names.append(str(tests / "sub" / "test_h.py"))
    return names


def test_a_directory_run_runs_the_named_files_and_nothing_else_and_matches_serial(
    tmp_path, monkeypatch, capsys
) -> None:
    project = tmp_path / "p"
    names = _mini_project(project)
    _git(project, "init", "-q")  # a nameable tree: without one the runner (rightly) caches no bytecode
    _git(project, "add", ".")
    _git(project, "commit", "-q", "-m", "one")
    monkeypatch.setattr(fast_tests, "ROOT", project)
    monkeypatch.setenv("FAST_TESTS_CACHE", str(tmp_path / "cache"))
    assert fast_tests.main(["--parity", "--dir-threshold", "0", "-n", "1", *names]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "dir+ignore" and report["tests"] == 5 and report["differing"] == 0
    ledger_args = ["--dir-threshold", "0", "--serial", *names]
    assert fast_tests.main(ledger_args) == 1  # the one test that fails still fails: the runner hides nothing
    row = json.loads((tmp_path / "cache" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert row["mode"] == "dir+ignore" and row["counts"] == {"passed": 4, "failed": 1, "skipped": 0}
    assert row["slowest"] and not any("test_unselected" in name for name, _ in row["slowest"])
    assert list((tmp_path / "cache" / "pyc").rglob("*.pyc")), "bytecode was not cached under the tree folder"


# ---- review fixes: a runner never drops a target, never shares a cache key when git fails, never leaks THOMAS_* ----


def _review_case(root: Path) -> list[str]:
    """Six passing files, one failing node id, one failing file that is not named test_*.py."""
    (root / "tests").mkdir(parents=True)
    names = []
    for i in range(6):
        (root / "tests" / f"test_ok{i}.py").write_text(f"def test_ok{i}():\n    assert True\n", encoding="utf-8")
        names.append(str(root / "tests" / f"test_ok{i}.py"))
    (root / "tests" / "test_bad.py").write_text(
        "def test_bad():\n    assert False\n\n\ndef test_other_in_bad():\n    assert True\n", encoding="utf-8"
    )
    (root / "tests" / "check_named.py").write_text("def test_named_fails():\n    assert False\n", encoding="utf-8")
    return [*names, str(root / "tests" / "test_bad.py") + "::test_bad", str(root / "tests" / "check_named.py")]


def test_a_nodeid_and_a_named_non_test_file_are_never_dropped(tmp_path, monkeypatch) -> None:
    project = tmp_path / "p"
    targets = _review_case(project)
    monkeypatch.setattr(fast_tests, "ROOT", project)
    monkeypatch.setenv("FAST_TESTS_CACHE", str(tmp_path / "cache"))
    plan = fast_tests.build_plan(_args(targets=targets), xdist=False, memory=(32 * GB, 20 * GB))
    assert plan["mode"] == "args" and plan["argv"] == targets, "every target is passed through unchanged"
    assert fast_tests.main(["--serial", *targets]) != 0, "plain pytest fails here, so the runner must too"
    row = json.loads((tmp_path / "cache" / "ledger.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert row["counts"] == {"passed": 6, "failed": 2, "skipped": 0}, row["counts"]


def test_relative_targets_keep_their_node_ids_and_are_anchored_to_the_callers_folder(tmp_path, monkeypatch) -> None:
    project = tmp_path / "p"
    _review_case(project)
    monkeypatch.chdir(project)
    plan = fast_tests.build_plan(
        _args(targets=["tests/test_bad.py::test_bad", "tests/check_named.py"]), xdist=False, memory=(32 * GB, 20 * GB)
    )
    assert plan["argv"] == [
        str(project / "tests" / "test_bad.py") + "::test_bad",
        str(project / "tests" / "check_named.py"),
    ]
    assert fast_tests.absolute_target("a/b.py::TestX::test_y[1-2]").endswith("b.py::TestX::test_y[1-2]")


def test_parity_fails_on_an_id_only_one_run_executed_even_if_it_cannot_be_rerun_alone(tmp_path, monkeypatch) -> None:
    project = tmp_path / "p"
    targets = _review_case(project)
    monkeypatch.setattr(fast_tests, "ROOT", project)
    monkeypatch.setattr(fast_tests, "solo", lambda _args, _id: "missing")  # the re-run cannot explain the difference
    named = [*targets[:6], targets[7]]
    forced = {
        "argv": [str(project / "tests")],
        "selection": {"files": named, "dirs": []},
        "workers": 1,
        "mode": "dir+ignore",
    }
    assert fast_tests.parity(_args(targets=named, no_pyc=True, pytest_args=[]), forced, "k") == 1


def test_only_plain_test_files_and_folders_may_use_the_directory_form(tmp_path) -> None:
    project = tmp_path / "p"
    targets = _review_case(project)
    assert fast_tests.directory_mode_is_safe(targets[:6])
    assert fast_tests.directory_mode_is_safe([*targets[:6], str(project / "tests")])
    assert not fast_tests.directory_mode_is_safe([*targets[:6], targets[6]]), "a node id"
    assert not fast_tests.directory_mode_is_safe([*targets[:6], targets[7]]), "a named file that is not test_*.py"
    assert not fast_tests.directory_mode_is_safe([*targets[:6], str(project / "tests" / "missing.py")])


def test_if_a_directory_run_ever_loses_a_named_file_the_run_fails_and_parity_notices(tmp_path, monkeypatch) -> None:
    project = tmp_path / "p"
    targets = _review_case(project)
    monkeypatch.setattr(fast_tests, "ROOT", project)
    monkeypatch.setenv("FAST_TESTS_CACHE", str(tmp_path / "cache"))
    named = [*targets[:6], targets[7]]  # six passing files and the named failing one
    forced = {
        "argv": [str(project / "tests")],
        "selection": {"files": named, "dirs": []},
        "workers": 1,
        "mode": "dir+ignore",
    }
    args = _args(targets=named, no_pyc=True, pytest_args=[])
    result = fast_tests.run_once(args, forced, "k")
    assert result["exit"] == 2 and result["unrun"] == [targets[7]], "a pass that skipped a named file is refused"
    assert fast_tests.parity(_args(targets=named, no_pyc=True, pytest_args=[]), forced, "k") == 1


def test_the_tree_key_is_none_when_git_cannot_name_the_tree(tmp_path) -> None:
    assert capacity.tree_key(tmp_path) is None, "not a repository: no shared constant key"
    other = tmp_path / "other"
    other.mkdir()
    assert capacity.tree_key(other) is None


def test_a_run_without_a_nameable_tree_caches_no_bytecode_and_says_so(tmp_path, monkeypatch, capsys) -> None:
    project = tmp_path / "p"
    names = _mini_project(project)[:2]
    monkeypatch.setattr(fast_tests, "ROOT", project)
    monkeypatch.setenv("FAST_TESTS_CACHE", str(tmp_path / "cache"))
    assert fast_tests.main(["--serial", names[0], names[1]]) == 0
    assert "git cannot name this tree" in capsys.readouterr().err
    pyc = tmp_path / "cache" / "pyc"
    assert not pyc.exists() or not any(pyc.rglob("*.pyc"))


def test_no_thomas_variable_reaches_the_workers_and_their_state_is_scratch(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("THOMAS_MEMORY_ROOT", "C:/real/runtime")
    monkeypatch.setenv("thomas_lowercase", "x")
    monkeypatch.setenv("THOMAS_SOMETHING_ELSE", "1")
    env = fast_tests.scrubbed_environment(tmp_path)
    thomas = {k: v for k, v in env.items() if k.upper().startswith("THOMAS_")}
    assert "THOMAS_SOMETHING_ELSE" not in thomas and "thomas_lowercase" not in env
    assert thomas and all(str(tmp_path) in v for v in thomas.values()), thomas
    assert env["THOMAS_MEMORY_ROOT"] != "C:/real/runtime" and str(tmp_path) in env["HOME"]


def test_a_worker_really_sees_only_scratch_state(tmp_path, monkeypatch) -> None:
    project = tmp_path / "p"
    (project / "tests").mkdir(parents=True)
    probe = tmp_path / "seen.json"
    (project / "tests" / "test_env.py").write_text(
        "import json, os\n\n\ndef test_env():\n"
        f"    open({str(probe)!r}, 'w').write(json.dumps({{k: v for k, v in os.environ.items() if k.upper().startswith('THOMAS_')}}))\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(fast_tests, "ROOT", project)
    monkeypatch.setenv("FAST_TESTS_CACHE", str(tmp_path / "cache"))
    monkeypatch.setenv("THOMAS_MEMORY_ROOT", "C:/real/runtime")
    monkeypatch.setenv("THOMAS_LEAK", "yes")
    assert fast_tests.main(["--serial", "--no-pyc", str(project / "tests" / "test_env.py")]) == 0
    seen = json.loads(probe.read_text(encoding="utf-8"))
    assert "THOMAS_LEAK" not in seen and seen["THOMAS_MEMORY_ROOT"] != "C:/real/runtime"
