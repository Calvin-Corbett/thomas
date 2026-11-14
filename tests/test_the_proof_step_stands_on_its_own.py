"""The proof step itself: which tests, run them, read them by id, compare them.

``thomas/server/proof/`` stands apart from the check that uses it, because a second caller is already
specified: the ratchet's §3 "the proof set"
(``docs/superpowers/specs/2026-09-23-praxis-ratchet-design.md``) asks for a ``proof_set(changed_files)``
and says it "has no equivalent in the repo today". The ratchet is not on dev: it is being built in another
Thomas project's own copy (``thomas/server/ratchet/``), so on dev this is one caller and a second on its
way, not two.

So these tests are written against the seam, not against the card check: they pass a work folder, a list
of files and an interpreter, and read test ids back. Nothing here knows what a green or a card is. That is
the whole point of testing it here -- the step has to be callable without a green, or the ratchet cannot
call it.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

import pytest

from thomas.server.proof import compare, environment, junit, runner, selection

REPORT = """<?xml version="1.0" encoding="utf-8"?>
<testsuites><testsuite name="pytest" tests="4">
  <testcase classname="tests.test_a" name="test_ok" file="tests/test_a.py" time="0.01"/>
  <testcase classname="tests.test_a" name="test_bad" file="tests/test_a.py" time="0.01">
    <failure message="assert 1 == 2">boom</failure>
  </testcase>
  <testcase classname="tests.test_b.TestThing" name="test_method[x]" file="tests/test_b.py" time="0.01">
    <failure message="nope">boom</failure>
  </testcase>
  <testcase classname="tests.test_c" name="test_c" file="tests/test_c.py" time="0.0">
    <error message="collection error">ImportError</error>
  </testcase>
</testsuite></testsuites>
"""


# ── which tests prove a change ─────────────────────────────────────────────────────────────────────────


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "tests").mkdir()
    (tmp_path / "thomas" / "server").mkdir(parents=True)
    (tmp_path / "thomas" / "server" / "green_handoff.py").write_text("X = 1\n", encoding="utf-8")
    (tmp_path / "thomas" / "server" / "app.py").write_text("X = 1\n", encoding="utf-8")
    files = {
        "test_architecture.py": "def test_sizes() -> None:\n    pass\n",
        "test_dotted.py": "from thomas.server.green_handoff import settle\n",
        "test_by_stem.py": "from thomas.server import green_handoff\n",
        "test_elsewhere.py": "import json\n",
        "test_handoff_and_app.py": "from thomas.server import app, green_handoff\n",
        "test_dotted_app.py": "import thomas.server.app\n",
    }
    for name, text in files.items():
        (tmp_path / "tests" / name).write_text(text, encoding="utf-8")
    return tmp_path


def test_the_proof_set_is_the_changes_own_tests_the_architecture_test_and_the_importers(repo: Path) -> None:
    chosen = selection.proof_set(repo, ["thomas/server/green_handoff.py", "tests/test_elsewhere.py"])

    assert chosen[0] == "tests/test_elsewhere.py", "the change's own test file comes first"
    assert chosen[1] == "tests/test_architecture.py", "then the one that always runs"
    assert set(chosen[2:]) == {"tests/test_dotted.py", "tests/test_by_stem.py", "tests/test_handoff_and_app.py"}
    # `from thomas.server.green_handoff import settle` and `from thomas.server import green_handoff` both import it.
    assert "tests/test_dotted.py" in chosen and "tests/test_by_stem.py" in chosen


def test_the_proof_set_leaves_out_what_is_not_there_and_says_what_its_cap_cut(repo: Path) -> None:
    gone = selection.proof_set(repo, ["tests/test_deleted.py", "thomas/server/green_handoff.py"])
    assert "tests/test_deleted.py" not in gone, "a test file the change deleted is not run"

    capped = selection.select(repo, ["thomas/server/green_handoff.py"], cap=2)
    assert capped.files == ("tests/test_architecture.py", "tests/test_by_stem.py")
    assert capped.left_out == ("tests/test_dotted.py", "tests/test_handoff_and_app.py"), "the cut is named, not hidden"


def test_a_file_is_chosen_by_what_it_imports_never_by_a_word_it_shares_with_the_module(repo: Path) -> None:
    """The stem search chose 748 files for 46162bf1: ``app`` or ``catalog`` in a file is not an import of it."""
    (repo / "tests" / "test_mentions_app.py").write_text("APP = 'app'\n# the app runs\n", encoding="utf-8")

    chosen = selection.proof_set(repo, ["thomas/server/app.py"])

    assert "tests/test_dotted_app.py" in chosen, "`import thomas.server.app` imports it"
    assert "tests/test_handoff_and_app.py" in chosen, "`from thomas.server import app` imports it too"
    assert "tests/test_mentions_app.py" not in chosen, "the word alone is not an import"
    assert "tests/test_by_stem.py" not in chosen and "tests/test_elsewhere.py" not in chosen


def test_a_test_that_reaches_the_module_through_a_patch_target_a_helper_or_a_nested_import_is_chosen(
    tmp_path: Path,
) -> None:
    """How 820602fd's 18 broken test files reached ``chat_v2``: none of them by a top-level import alone."""
    texts = {
        "tests/test_patch_target.py": 'from unittest.mock import patch\nP = patch("thomas.server.routes.chat_v2.Brain")\n',
        "tests/test_nested.py": "def test_x() -> None:\n    from thomas.server.routes import chat_v2\n",
        "tests/_chat_fakes.py": "from thomas.server.routes import chat_v2\n",
        "tests/test_through_helper.py": "from tests._chat_fakes import chat_v2\n",
        "tests/test_through_bare_helper.py": "import _chat_fakes\n",
        "tests/test_support_module.py": "from thomas.server.routes import chat_v2_support\n",
        "tests/test_architecture.py": "",
    }

    chosen = selection.select_from(texts, ["thomas/server/routes/chat_v2.py"])

    assert set(chosen.files) == {
        "tests/test_architecture.py",
        "tests/test_patch_target.py",
        "tests/test_nested.py",
        "tests/test_through_helper.py",
        "tests/test_through_bare_helper.py",
    }, "chat_v2_support is another module, and a helper is not itself a test file"
    assert chosen.files.index("tests/test_nested.py") < chosen.files.index("tests/test_through_helper.py")


def test_a_changed_conftest_reaches_its_folder_but_after_every_real_importer(tmp_path: Path) -> None:
    texts = {
        "tests/test_architecture.py": "",
        "tests/test_imports_it.py": "import thomas.core.llm_client\n",
        "tests/test_unrelated.py": "import json\n",
        "tests/sub/test_below.py": "import json\n",
    }

    chosen = selection.select_from(texts, ["tests/conftest.py", "thomas/core/llm_client.py"], cap=3)

    assert chosen.files == ("tests/test_architecture.py", "tests/test_imports_it.py", "tests/sub/test_below.py")
    assert chosen.left_out == ("tests/test_unrelated.py",), "what the conftest reaches comes last, and the cut says so"


# The 18 test files 820602fd broke, named by the two commits that repaired them (dffaa3ed and 6f9ea4c5). The other
# files those commits touched were new (the max-mode split) or already failing before 820602fd (test_server_app_core).
BROKE_820602FD = (
    "test_chat_document_upload",
    "test_chat_v2_streams_text_before_the_turn_finishes",
    "test_discord_channels",
    "test_self_work_from_chat_is_a_thomas_project",
    "test_server_batch_mode",
    "test_server_chat_controls",
    "test_server_chat_v2_max_mode",
    "test_server_chats_api",
    "test_server_done_usage_contract",
    "test_server_mixed_mode_concurrency",
    "test_server_orchestrator_only_mode",
    "test_server_preferences_runtime",
    "test_server_session_run_guard_modes",
    "test_server_task_ledger",
    "test_server_task_ledger_v2_contract",
    "test_server_token_economy",
    "test_server_usage_invariants",
    "test_the_user_turn_survives_a_turn_that_never_finishes",
)
REPO = Path(__file__).resolve().parents[1]


def _git_out(*args: str) -> bytes:
    return subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, check=True).stdout


def _tests_at(commit: str) -> dict[str, str]:
    """Every ``tests/**/*.py`` at *commit*, read from git: the tree the check's copy with the change would hold."""
    names = [n for n in _git_out("ls-tree", "-r", "--name-only", commit, "--", "tests").decode().splitlines()]
    names = [n for n in names if n.endswith(".py")]
    batch = subprocess.run(
        ["git", "-C", str(REPO), "cat-file", "--batch"],
        input="".join(f"{commit}:{name}\n" for name in names).encode(),
        capture_output=True,
        check=True,
    ).stdout
    texts, at = {}, 0
    for name in names:
        header_end = batch.index(b"\n", at)
        size = int(batch[at:header_end].split()[2])
        texts[name] = batch[header_end + 1 : header_end + 1 + size].decode("utf-8", errors="ignore")
        at = header_end + 1 + size + 1
    return texts


def _changed_by(commit: str) -> list[str]:
    return _git_out("diff-tree", "--no-commit-id", "--no-renames", "--name-only", "-r", commit).decode().splitlines()


def _have(commit: str) -> bool:
    found = subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", f"{commit}^{{commit}}"], capture_output=True)
    return found.returncode == 0


@pytest.mark.skipif(not _have("820602fd"), reason="this checkout does not have 820602fd's history")
def test_the_820602fd_case_selects_every_test_file_it_broke() -> None:
    """The stem search chose 203 files for it and the cap then dropped 10 of these 18."""
    chosen = selection.select_from(_tests_at("820602fd"), _changed_by("820602fd"))

    missing = [name for name in BROKE_820602FD if f"tests/{name}.py" not in chosen.files]
    assert missing == [], f"not run: {missing}"
    # It also changed tests/conftest.py, which reaches every test file: those come last, and the cut is named.
    assert chosen.left_out and all(f"tests/{name}.py" not in chosen.left_out for name in BROKE_820602FD)


@pytest.mark.skipif(not (_have("46162bf1") and _have("2a23ea2b")), reason="this checkout lacks their history")
def test_a_change_with_many_importers_runs_every_one_of_them() -> None:
    """Historical importers stay ahead of conftest-scope overflow in the selected set."""
    for commit in ("46162bf1", "2a23ea2b"):
        texts, changed = _tests_at(commit), _changed_by(commit)
        chosen = selection.select_from(texts, changed)
        modules = {selection._dotted(rel) for rel in changed}
        importers = {
            rel
            for rel, text in texts.items()
            if selection._is_test_file(rel) and selection._reached(text, selection._imported(text), modules)
        }
        assert importers <= set(chosen.files), f"{commit} dropped a direct importer"
        if commit == "46162bf1":
            assert set(chosen.files + chosen.left_out) == {rel for rel in texts if selection._is_test_file(rel)}
        else:
            assert chosen.left_out == (), f"{commit} left out {chosen.left_out}"


# ── reading the failures back by test id ───────────────────────────────────────────────────────────────


def test_a_junit_report_gives_every_failure_the_id_that_re_runs_it(tmp_path: Path) -> None:
    path = tmp_path / "report.xml"
    path.write_text(REPORT, encoding="utf-8")

    read = junit.read_report(path)

    assert read is not None and len(read.seen) == 4
    assert read.failed == (
        "tests/test_a.py::test_bad",
        "tests/test_b.py::TestThing::test_method[x]",
        "tests/test_c.py::test_c",
    ), "a collection <error> is a failure of the run, not an absence of one"
    assert "tests/test_a.py::test_ok" in read.seen


def test_a_report_that_is_not_there_is_never_read_as_a_pass(tmp_path: Path) -> None:
    assert junit.read_report(tmp_path / "missing.xml") is None
    (tmp_path / "half.xml").write_text("<testsuites>", encoding="utf-8")
    assert junit.read_report(tmp_path / "half.xml") is None


# ── the environment a proof runs in ────────────────────────────────────────────────────────────────────


def test_a_proof_inherits_none_of_your_thomas_git_or_pytest_variables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Your words: "Never let the check write my real data... never use the running copy's git index"."""
    monkeypatch.setenv("THOMAS_DB_PATH", r"C:\Users\you\AppData\Local\Thomas\thomas.db")
    monkeypatch.setenv("THOMAS_GREEN_ROOT", r"C:\Users\you\AppData\Local\Thomas\green")
    monkeypatch.setenv("GIT_INDEX_FILE", r"C:\Users\you\Thomas\.git\index")
    monkeypatch.setenv("PYTEST_ADDOPTS", "--exitfirst")
    monkeypatch.setenv("PATH", "keep-me")

    env = environment.sandbox_env(tmp_path / "work", tmp_path / "data")

    assert "GIT_INDEX_FILE" not in env and "PYTEST_ADDOPTS" not in env
    assert env["PATH"] == "keep-me", "everything that is not yours to lose is kept"
    for name in ("THOMAS_DATA_DIR", "THOMAS_HOME", "THOMAS_DB_PATH", "THOMAS_GREEN_ROOT", "THOMAS_CAGE_ROOT"):
        assert Path(env[name]).is_relative_to(tmp_path / "data"), f"{name} points at {env[name]}"
    assert env["PYTHONPATH"] == str(tmp_path / "work")
    assert (tmp_path / "data").is_dir()


def test_an_interpreter_is_the_one_named_then_the_repos_own_venv_then_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(environment.PYTHON_ENV, raising=False)
    assert environment.interpreter(tmp_path) == ""

    venv = tmp_path / ".venv" / ("Scripts" if sys.platform == "win32" else "bin")
    venv.mkdir(parents=True)
    named = venv / ("python.exe" if sys.platform == "win32" else "python")
    named.write_text("", encoding="utf-8")
    assert environment.interpreter(tmp_path) == str(named)

    monkeypatch.setenv(environment.PYTHON_ENV, str(tmp_path / "nowhere.exe"))
    assert environment.interpreter(tmp_path) == "", "a named interpreter that is not there is not a fallback"


def test_shards_overlap_and_keep_failure_order_when_opted_in(tmp_path: Path) -> None:
    files = [f"tests/test_{n}.py" for n in range(3)]
    for rel in files:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_bad(): pass\n", encoding="utf-8")
    first_two_started = threading.Event()
    active = 0
    peak = 0
    starts = 0
    sandbox_dirs: set[str] = set()
    lock = threading.Lock()

    def fake_run(command: list[str], **kwargs: object) -> tuple[int, str]:
        nonlocal active, peak, starts
        env = kwargs["env"]
        assert isinstance(env, dict)
        with lock:
            sandbox_dirs.add(env["THOMAS_DATA_DIR"])
            active += 1
            starts += 1
            peak = max(peak, active)
            if starts == 2:
                first_two_started.set()
        assert first_two_started.wait(5), "the first two shards must overlap"
        report = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junit-xml=")))
        rel = command[-1]
        module = rel[:-3].replace("/", ".")
        report.write_text(
            f'<testsuite><testcase file="{rel}" classname="{module}" '
            'name="test_bad"><failure message="failed"/></testcase></testsuite>',
            encoding="utf-8",
        )
        with lock:
            active -= 1
        return 1, ""

    result = runner.run_tests(
        tmp_path,
        files,
        python=sys.executable,
        data_dir=tmp_path / "data",
        shard_files=1,
        shard_workers=2,
        run=fake_run,
    )
    assert peak == 2
    assert len(sandbox_dirs) == len(files), "parallel shards must not share writable Thomas state"
    assert result.ran and result.seen == 3 and result.shards == 3
    assert result.failed == tuple(f"{rel}::test_bad" for rel in files)


def test_parallel_shards_do_not_pass_after_the_whole_proof_deadline(tmp_path: Path) -> None:
    from thomas.server.proof.deadline import Deadline

    files = [f"tests/test_{n}.py" for n in range(2)]
    for rel in files:
        target = tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("def test_ok(): pass\n", encoding="utf-8")
    started = threading.Barrier(2)
    deadline = Deadline(0.2)

    def fake_run(command: list[str], **kwargs: object) -> tuple[int, str]:
        started.wait(timeout=5)
        threading.Event().wait(0.3)
        report = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junit-xml=")))
        report.write_text(f'<testsuite><testcase file="{command[-1]}" name="test_ok"/></testsuite>', encoding="utf-8")
        return 0, ""

    result = runner.run_tests(
        tmp_path,
        files,
        python=sys.executable,
        data_dir=tmp_path / "data",
        shard_files=1,
        shard_workers=2,
        deadline=deadline,
        run=fake_run,
    )
    assert result.out_of_time and not result.ran


# ── the comparison ─────────────────────────────────────────────────────────────────────────────────────


def _answers(by_test: dict[str, str]) -> Callable[[str], str]:
    return lambda test: by_test.get(test, runner.UNKNOWN)


def test_only_a_failure_confirmed_alone_on_both_copies_counts_against_the_change() -> None:
    verdict = compare.confirm(
        ["t::a", "t::flaky", "t::already", "t::new_test"],
        known_on_dev=["t::already"],
        rerun_with_change=_answers(
            {
                "t::a": runner.FAILED,
                "t::flaky": runner.PASSED,
                "t::already": runner.FAILED,
                "t::new_test": runner.FAILED,
            }
        ),
        rerun_on_base=_answers({"t::a": runner.PASSED, "t::already": runner.FAILED, "t::new_test": runner.MISSING}),
    )

    assert verdict.findings == ("t::a",), "fails with the change, passes on dev, both confirmed alone"
    assert verdict.added == ("t::new_test",), "a failing test the change brings with it is its own finding"
    assert verdict.excused == ("t::already",), "dev fails it too, confirmed on its own"
    assert verdict.flaky == ("t::flaky",), "it passed when nothing else ran beside it"
    assert set(verdict.blocking) == {"t::a", "t::new_test"}


def test_a_base_failure_that_passes_on_its_own_does_not_excuse_the_change() -> None:
    """Your rule, not the subset one: a plain subset test would excuse this, and it is a real regression."""
    verdict = compare.confirm(
        ["t::shared"],
        known_on_dev=["t::shared"],
        rerun_with_change=_answers({"t::shared": runner.FAILED}),
        rerun_on_base=_answers({"t::shared": runner.PASSED}),
    )

    assert verdict.findings == ("t::shared",) and verdict.excused == ()


def test_a_failure_nobody_could_settle_alone_blocks_rather_than_passes() -> None:
    """A collection error has no id pytest takes back: nobody can settle it, known on dev or not, so it blocks."""
    murky = compare.confirm(["t::murky"], rerun_with_change=_answers({}), rerun_on_base=_answers({}))
    assert murky.unconfirmed == ("t::murky",) and murky.blocking == ("t::murky",)

    known = compare.confirm(["t::x"], known_on_dev=["t::x"], rerun_with_change=_answers({}), rerun_on_base=_answers({}))
    assert known.unconfirmed == ("t::x",) and known.blocking == ("t::x",)
    assert known.excused == (), "dev failing it somewhere else is not an excuse"


def test_past_the_rerun_cap_every_unsettled_failure_blocks_and_known_on_dev_goes_last() -> None:
    asked: list[str] = []

    def with_change(test: str) -> str:
        asked.append(test)
        return runner.FAILED

    verdict = compare.confirm(["t::old", "t::new"], known_on_dev=["t::old"], rerun_with_change=with_change,
                              rerun_on_base=_answers({"t::new": runner.PASSED}), cap=1)  # fmt: skip

    assert verdict.findings == ("t::new",), "the ones dev is not known to fail are confirmed first"
    assert verdict.unconfirmed == ("t::old",) and "t::old" in verdict.blocking
    assert verdict.excused == () and asked == ["t::new"]


# ── a re-run that did not finish ───────────────────────────────────────────────────────────────────────


def test_a_base_re_run_that_timed_out_never_excuses_the_change_and_is_never_called_confirmed() -> None:
    """Finding 5: a base re-run that hung for 180 s was read as a failure on dev, so it excused the change."""
    from thomas.server.precard import report
    from thomas.server.precard.lint import LintResult

    verdict = compare.confirm(
        ["t::hangs_on_dev"],
        rerun_with_change=_answers({"t::hangs_on_dev": runner.FAILED}),
        rerun_on_base=_answers({"t::hangs_on_dev": runner.TIMEOUT}),
    )

    assert verdict.excused == ()
    assert verdict.timed_out == ("t::hangs_on_dev",) and verdict.blocking == ("t::hangs_on_dev",)
    findings = report.findings_text("abc123456789", verdict, LintResult(True, "", (), ()), [])
    assert "did not finish in time" in findings and "t::hangs_on_dev" in findings
    assert "confirmed on its own" not in findings


def test_a_re_run_that_timed_out_with_the_change_is_not_a_confirmed_failure_either() -> None:
    new = compare.confirm(["t::hangs"], rerun_with_change=_answers({"t::hangs": runner.TIMEOUT}),
                          rerun_on_base=_answers({}))  # fmt: skip
    assert new.timed_out == ("t::hangs",) and new.findings == () and new.blocking == ("t::hangs",)

    old = compare.confirm(
        ["t::hangs"],
        known_on_dev=["t::hangs"],
        rerun_with_change=_answers({"t::hangs": runner.TIMEOUT}),
        rerun_on_base=_answers({}),
    )
    assert old.excused == () and old.timed_out == ("t::hangs",) and old.blocking == ("t::hangs",)


def test_the_cards_line_never_calls_an_unsettled_excuse_confirmed_and_names_what_the_cap_cut() -> None:
    from thomas.server.precard import report
    from thomas.server.precard.lint import LintResult

    verdict = compare.Verdict((), (), ("t::a",), (), ())
    run = runner.ProofRun(True, "", ("t::a", "t::b", "t::c"), 40, 1)
    line = report.line_passed(
        "abc123456789", ["tests/test_x.py"], run, verdict, LintResult(True, "", (), ()), [], ("tests/test_y.py",)
    )

    assert "1 failure(s) dev already has, each confirmed on its own" in line
    assert "own run also had" not in line
    assert "1 more test file(s) that cover it were not run" in line and "tests/test_y.py" in line


def test_a_real_test_that_hangs_alone_answers_timeout_and_never_fail(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_hang.py").write_text(
        "import time\n\n\ndef test_hangs() -> None:\n    time.sleep(60)\n", encoding="utf-8"
    )

    answer = runner.run_one(
        tmp_path, "tests/test_hang.py::test_hangs", python=sys.executable, data_dir=tmp_path / "d", timeout_s=5.0
    )

    assert answer == runner.TIMEOUT


def test_a_proof_whose_deadline_has_passed_starts_nothing_and_says_it_ran_out_of_time(tmp_path: Path) -> None:
    from thomas.server.proof.deadline import Deadline

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pair.py").write_text(ONE_GOOD_ONE_BAD, encoding="utf-8")
    spent = Deadline(0.0)
    started: list[object] = []

    def run(*args: object, **kwargs: object) -> tuple[int, str]:
        started.append(args)
        return 0, ""

    proof = runner.run_tests(
        tmp_path, ["tests/test_pair.py"], python=sys.executable, data_dir=tmp_path / "d", deadline=spent, run=run
    )

    assert not proof.ran and proof.out_of_time and "limit" in proof.why and started == []
    one = runner.run_one(tmp_path, "tests/test_pair.py::test_fails", python=sys.executable, data_dir=tmp_path / "d",
                         deadline=spent, run=run)  # fmt: skip
    assert one == runner.TIMEOUT and started == []


# ── running them for real ──────────────────────────────────────────────────────────────────────────────


ONE_GOOD_ONE_BAD = "def test_passes() -> None:\n    assert True\n\n\ndef test_fails() -> None:\n    assert 1 == 2\n"


def test_a_real_run_reports_the_failing_test_by_an_id_that_re_runs_only_that_test(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pair.py").write_text(ONE_GOOD_ONE_BAD, encoding="utf-8")

    run = runner.run_tests(
        tmp_path, ["tests/test_pair.py"], python=sys.executable, data_dir=tmp_path / "data", timeout_s=300.0
    )

    assert run.ran and run.shards == 1 and run.seen == 2
    assert run.failed == ("tests/test_pair.py::test_fails",)

    alone = dict(python=sys.executable, data_dir=tmp_path / "data", timeout_s=180.0)
    assert runner.run_one(tmp_path, "tests/test_pair.py::test_fails", **alone) == runner.FAILED
    assert runner.run_one(tmp_path, "tests/test_pair.py::test_passes", **alone) == runner.PASSED
    assert runner.run_one(tmp_path, "tests/test_gone.py::test_x", **alone) == runner.MISSING


def test_a_file_that_cannot_even_be_collected_is_a_failure_and_never_an_empty_pass(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_broken.py").write_text("import a_module_that_is_not_there\n", encoding="utf-8")

    run = runner.run_tests(
        tmp_path, ["tests/test_broken.py"], python=sys.executable, data_dir=tmp_path / "data", timeout_s=300.0
    )

    assert run.failed and run.failed[0].startswith("tests/test_broken.py")
