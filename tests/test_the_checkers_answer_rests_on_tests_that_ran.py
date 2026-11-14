"""The checker's PASSED means tests ran and passed, in copies nothing else wrote into (2026-10-14 review, B3-B5).

Part 4 of docs/superpowers/specs/2026-10-12-praxis-production-line-design.md, section 8.2 condition 2. These tests use
their own git repo and tmp folders and fake the test runner, except where a test says it runs pytest itself.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from scripts.cage import checker_completion as cc
from scripts.cage import checker_jobs as cj
from scripts.cage import checker_service as cs

from tests.green_support import git, make_blue
from thomas.server import proof
from thomas.server.proof.environment import NOT_STARTED, REFUSED, TIMED_OUT

FAILING = "tests/test_fix_me.py::test_value"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return make_blue(tmp_path)


def _job(repo: Path, files: dict[str, str] | None = None) -> cj.Job:
    base = git(repo, "rev-parse", "HEAD")
    files = files or {"thomas/fix_me.py": "VALUE = 2\n"}
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "change")
    commit, tree = git(repo, "rev-parse", "HEAD"), git(repo, "rev-parse", "HEAD^{tree}")
    return cj.Job("a" * 24, cj.CHECK, base, commit, tree, tuple(files), (), 1.0)


class Tools(cs.Tools):
    """The runner's answers, decided by which copy a test runs in, and every call it was given."""

    def __init__(self, *, failed: tuple[str, ...] = (), on_change: str = proof.FAILED, on_base: str = proof.PASSED,
                 seen: int = 3, selected: tuple[str, ...] = ("tests/test_fix_me.py",),
                 left_out: tuple[str, ...] = (), boot: tuple[int, str] = (0, "")) -> None:  # fmt: skip
        self.calls: list[tuple[str, dict[str, object]]] = []

        def select(work: Path, changed: list[str]) -> proof.Selection:
            self.calls.append(("select", {"work": work, "changed": list(changed)}))
            return proof.Selection(selected, left_out)

        def run_tests(work: Path, files: list[str], **kwargs: object) -> proof.ProofRun:
            self.calls.append(("run_tests", {"work": work, "files": list(files), **kwargs}))
            return proof.ProofRun(True, "", failed, seen, 1)

        def run_one(work: Path, test: str, **kwargs: object) -> str:
            self.calls.append(("run_one", {"work": work, "test": test, **kwargs}))
            return on_base if work.name == "base" else on_change

        def run(command: list[str], **kwargs: object) -> tuple[int, str]:
            self.calls.append(("run", {"command": list(command), **kwargs}))
            return boot

        super().__init__(select=select, run_tests=run_tests, run_one=run_one, confirm=proof.confirm, run=run)

    def given(self, name: str) -> list[dict[str, object]]:
        return [kwargs for called, kwargs in self.calls if called == name]


def _check(repo: Path, tmp_path: Path, tools: Tools, job: cj.Job | None = None) -> cj.Result:
    return cs.run_job(job or _job(repo), repo=repo, copies=tmp_path / "copies", python="python", tools=tools)


# -- B4: every run writes its data beside the copies, never inside one ------------------------------------------- #
def test_each_run_writes_its_data_beside_the_copies_never_inside_one(repo: Path, tmp_path: Path) -> None:
    # The base re-run once wrote its sandbox data into the base checkout itself: clutter there can only make the base
    # fail, and a failure on the base excuses a regression.
    tools = Tools(failed=(FAILING,), on_change=proof.FAILED, on_base=proof.FAILED)
    job = _job(repo)
    _check(repo, tmp_path, tools, job)
    place = tmp_path / "copies" / job.id
    data = {"run": Path(str(tools.given("run_tests")[0]["data_dir"]))}
    for call in tools.given("run_one"):
        data["base" if Path(str(call["work"])).name == "base" else "again"] = Path(str(call["data_dir"]))
    data["boot"] = Path(str(tools.given("run")[0]["env"]["THOMAS_DATA_DIR"]))  # type: ignore[index]
    assert set(data) == {"run", "again", "base", "boot"}
    for name, folder in data.items():
        for copy in (place / "work", place / "base"):
            assert not folder.is_relative_to(copy), f"the {name} data went inside {copy.name}"
    assert len(set(data.values())) == len(data), "each run has a data folder of its own"


# -- B5: a failure no re-run can settle is the checker's trouble, never the change's ----------------------------- #
@pytest.mark.parametrize("again", [proof.MISSING, proof.UNKNOWN, proof.TIMEOUT, proof.NO_PLACE])
def test_a_failure_no_rerun_can_settle_is_unavailable_never_failed(repo: Path, tmp_path: Path, again: str) -> None:
    # The re-run with the change neither reproduced the failure nor cleared it. That says nothing about the change:
    # it is UNAVAILABLE and tried again, never a FAILED that sends a good change back to its team (plan Task 36).
    result = _check(repo, tmp_path, Tools(failed=(FAILING,), on_change=again))
    assert result.verdict == cj.UNAVAILABLE and "settled" in result.why
    assert result.findings == (), "findings name only the tests the change broke"


@pytest.mark.parametrize("code", [TIMED_OUT, NOT_STARTED, REFUSED])
def test_a_boot_check_that_did_not_finish_is_unavailable_never_failed(repo: Path, tmp_path: Path, code: int) -> None:
    # A boot check that timed out, would not launch or got no place once answered "Thomas no longer starts".
    result = _check(repo, tmp_path, Tools(boot=(code, "the command did not finish")))
    assert result.verdict == cj.UNAVAILABLE and "boot check did not finish" in result.why and result.boot == ""


def test_a_boot_check_that_ran_and_failed_still_fails(repo: Path, tmp_path: Path) -> None:
    result = _check(repo, tmp_path, Tools(boot=(1, "ImportError: no module named thomas.gone")))
    assert result.verdict == cj.FAILED and "no longer starts" in result.why and "thomas.gone" in result.boot


def test_a_real_regression_beside_an_unsettled_failure_still_fails(repo: Path, tmp_path: Path) -> None:
    other = "tests/test_fix_me.py::test_other"

    class Mixed(Tools):
        def __init__(self) -> None:
            super().__init__(failed=(FAILING, other))
            plain = self.run_one
            self.run_one = lambda work, test, **kw: proof.TIMEOUT if test == other else plain(work, test, **kw)

    result = _check(repo, tmp_path, Mixed())
    assert result.verdict == cj.FAILED and result.findings == (FAILING,)


def test_the_heartbeat_is_written_whole_never_in_place(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # A reader that catches the heartbeat half written reads no number and says the checker is not running.
    beat = tmp_path / cj.HEARTBEAT
    beat.write_text("1.0", encoding="utf-8")
    opened: list[Path] = []
    real_write = Path.write_text

    def write_text(self: Path, *args: object, **kwargs: object) -> int:
        opened.append(self)
        return real_write(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, "write_text", write_text)
    stop = threading.Event()
    stop.set()
    cs._beat(beat, stop)
    assert beat not in opened, "the heartbeat file itself was opened for writing"
    assert float(beat.read_text(encoding="utf-8")) > 1.0
    assert [path.name for path in tmp_path.iterdir()] == [cj.HEARTBEAT], "no temporary file is left behind"


# -- B3: PASSED only when tests ran, cover the change, and read the copy's own pytest config ---------------------- #
def test_a_run_that_saw_no_test_is_unavailable_never_passed(repo: Path, tmp_path: Path) -> None:
    # The review's probe: a run that "ran" and saw nothing answered PASSED with ran=0.
    result = _check(repo, tmp_path, Tools(seen=0))
    assert result.verdict == cj.UNAVAILABLE and "no test ran" in result.why and result.seen == 0


def test_a_code_change_only_the_always_run_test_covers_is_unavailable(repo: Path, tmp_path: Path) -> None:
    # select() always adds tests/test_architecture.py, so "nothing selected" never happens: a new module no test
    # imports got PASSED from the architecture test alone.
    result = _check(repo, tmp_path, Tools(selected=proof.ALWAYS))
    assert result.verdict == cj.UNAVAILABLE and "no test covers" in result.why
    assert "thomas/fix_me.py" in result.why


def test_each_changed_code_file_needs_a_test_of_its_own(repo: Path, tmp_path: Path) -> None:
    # Two code files: one is covered, the other only by the always-run test. The second is not proven by the first's.
    covered = {"thomas/fix_me.py": ("tests/test_fix_me.py",), "thomas/new.py": ()}

    class PerFile(Tools):
        def __init__(self) -> None:
            super().__init__()
            self.select = lambda work, changed: proof.Selection(
                tuple(dict.fromkeys([t for path in changed for t in covered[path]] + list(proof.ALWAYS)))
            )

    job = _job(repo, {"thomas/fix_me.py": "VALUE = 2\n", "thomas/new.py": "X = 1\n"})
    result = _check(repo, tmp_path, PerFile(), job)
    assert result.verdict == cj.UNAVAILABLE and "thomas/new.py" in result.why and "thomas/fix_me.py" not in result.why


def test_a_change_with_no_code_file_passes_on_the_tests_that_ran(repo: Path, tmp_path: Path) -> None:
    job = _job(repo, {"README.md": "blue, changed\n"})
    result = _check(repo, tmp_path, Tools(selected=proof.ALWAYS, seen=4), job)
    assert result.verdict == cj.PASSED and result.seen == 4


def test_a_change_whose_covering_tests_the_cap_cut_is_unavailable(repo: Path, tmp_path: Path) -> None:
    result = _check(repo, tmp_path, Tools(left_out=("tests/test_far_away.py",)))
    assert result.verdict == cj.UNAVAILABLE and "1 test file" in result.why and "cap" in result.why


def test_the_answer_counts_the_tests_seen_and_the_files_run(repo: Path, tmp_path: Path) -> None:
    job = _job(repo, {"thomas/fix_me.py": "VALUE = 2\n", "tests/test_fix_me.py": "def test_value(): pass\n"})
    result = _check(repo, tmp_path, Tools(seen=7), job)
    assert result.verdict == cj.PASSED and (result.seen, result.ran) == (7, 1)
    assert cj.Result.parse(result.to_json()) == result


def test_every_checker_run_reads_its_own_copys_pytest_config(repo: Path, tmp_path: Path) -> None:
    # A stray tests/.pytest.ini (or PYTEST.INI) once emptied every check: pytest used the nearest config file it found.
    tools = Tools(failed=(FAILING,), on_change=proof.FAILED, on_base=proof.FAILED)
    job = _job(repo)
    _check(repo, tmp_path, tools, job)
    place = tmp_path / "copies" / job.id
    (first,) = tools.given("run_tests")
    assert first["config"] == place / "work" / "pyproject.toml" and first["require_cases"] is True
    for call in tools.given("run_one"):
        assert call["config"] == Path(str(call["work"])) / "pyproject.toml"


def test_the_promoter_takes_a_pass_with_no_test_seen_as_unavailable(tmp_path: Path) -> None:
    from scripts.cage.window_checker import CheckerLink

    link = CheckerLink(tmp_path / "check")
    job = link.post(cj.CHECK, base="1" * 40, commit="2" * 40, tree="3" * 40, changed=["thomas/x.py"])
    empty = cj.Result(job.id, job.kind, job.base, job.commit, job.tree, cj.PASSED, ran=1, seen=0, finished_at=1.0)
    cc.publish(link.root, job, empty)
    got = link.result(job)
    assert got is not None and got.verdict == cj.UNAVAILABLE and "no test" in got.why


# -- B3 with pytest itself: a stray config under tests/ is never read, and an empty shard did not run ------------- #
# These tiny copies exercise pytest's config, collection and JUnit output, not unrelated plugins installed on
# the machine. The proof's own collection plugin is still loaded explicitly by the production runner.
_REAL_PYTEST_ENV = {"PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}


def _real_copy(root: Path) -> Path:
    work = root / "work"
    (work / "tests").mkdir(parents=True)
    (work / "pyproject.toml").write_text('[tool.pytest.ini_options]\ntestpaths = ["tests"]\n', encoding="utf-8")
    (work / "tests" / "test_value.py").write_text("def test_value():\n    assert 1 == 2\n", encoding="utf-8")
    (work / "tests" / ".pytest.ini").write_text("[pytest]\npython_functions = nothing_*\n", encoding="utf-8")
    return work


def test_with_its_config_named_pytest_never_reads_a_stray_config_under_tests(tmp_path: Path) -> None:
    import sys

    work = _real_copy(tmp_path)
    files = ["tests/test_value.py"]
    stray = proof.run_tests(work, files, python=sys.executable, data_dir=tmp_path / "d1", extra_env=_REAL_PYTEST_ENV)
    assert not stray.ran and stray.seen == 0, "a stray config must not turn an empty run into completed proof"
    assert stray.unrun == tuple(files) and "no test case" in stray.why
    pinned = proof.run_tests(
        work, files, python=sys.executable, data_dir=tmp_path / "d2", extra_env=_REAL_PYTEST_ENV,
        config=work / "pyproject.toml", require_cases=True,
    )  # fmt: skip
    assert pinned.ran and pinned.seen == 1 and pinned.failed == ("tests/test_value.py::test_value",)


def test_for_the_checker_a_shard_that_collected_nothing_did_not_run(tmp_path: Path) -> None:
    import sys

    work = _real_copy(tmp_path)
    run = proof.run_tests(
        work, ["tests/test_value.py"], python=sys.executable, data_dir=tmp_path / "d",
        require_cases=True, extra_env=_REAL_PYTEST_ENV,
    )  # fmt: skip
    assert not run.ran and "collected no test" in run.why


def test_the_checker_asks_that_every_chosen_file_holds_a_case(repo: Path, tmp_path: Path) -> None:
    tools = Tools()
    _check(repo, tmp_path, tools)
    (first,) = tools.given("run_tests")
    assert first["folder"] is True, "a chosen file with no case in its shard's report must read as not run"


def test_with_folder_a_chosen_file_that_collected_nothing_did_not_run(tmp_path: Path) -> None:
    # Another file's cases once stood behind a pass while the change's own covering test collected nothing.
    import sys

    work = _real_copy(tmp_path)
    (work / "tests" / "test_value.py").write_text("def test_value():\n    assert 1 == 1\n", encoding="utf-8")
    (work / "tests" / "test_emptied.py").write_text("def check_value():\n    assert False\n", encoding="utf-8")
    files = ["tests/test_value.py", "tests/test_emptied.py"]
    run = proof.run_tests(
        work, files, python=sys.executable, data_dir=tmp_path / "d", folder=True,
        config=work / "pyproject.toml", require_cases=True, extra_env=_REAL_PYTEST_ENV,
    )  # fmt: skip
    assert not run.ran and "tests/test_emptied.py" in run.why and run.seen == 1
