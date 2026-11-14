"""A failure with the change counts unless it is noise or fails alone on dev (spec 2026-10-12 Part 1 items 2 and 4).

Nothing else excuses a failure any more: not dev's own full run (the excused_by_run path is gone) and not a hint about
what dev is known to fail, which only orders the re-runs. Re-runs run side by side, each in its own report and
sandbox; an excuse found beside other re-runs is settled once more on dev, one at a time, in a sandbox of its own.
"""

from __future__ import annotations

import dataclasses
import inspect
import sys
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from thomas.server.proof import compare, environment, runner


def test_two_re_runs_at_once_in_one_folder_never_share_a_report_or_a_sandbox(tmp_path: Path) -> None:
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pair.py").write_text("def test_fails(): pass\n\ndef test_passes(): pass\n")
    written, read = threading.Barrier(2, timeout=30), threading.Barrier(2, timeout=30)
    seen: list[tuple[str, str]] = []

    def run(command: list[str], *, cwd: Path, env: dict, timeout_s: float) -> tuple[int, str]:
        report = Path(next(arg.split("=", 1)[1] for arg in command if arg.startswith("--junit-xml=")))
        name = command[-1].split("::")[1]
        seen.append((str(report), env["THOMAS_DATA_DIR"]))
        written.wait()
        failure = '<failure message="x"/>' if name == "test_fails" else ""
        report.write_text(
            f'<testsuite><testcase classname="tests.test_pair" name="{name}" file="tests/test_pair.py">{failure}'
            "</testcase></testsuite>",
            encoding="utf-8",
        )
        read.wait()  # both reports are on disk before either run reads its own back
        return (1 if failure else 0), ""

    def one(node: str) -> str:
        return runner.run_one(tmp_path, node, python=sys.executable, data_dir=tmp_path / "d", run=run)

    with ThreadPoolExecutor(2) as both:
        answers = list(both.map(one, ["tests/test_pair.py::test_fails", "tests/test_pair.py::test_passes"]))

    assert answers == [runner.FAILED, runner.PASSED]
    assert len({report for report, _ in seen}) == 2 and len({data for _, data in seen}) == 2


def _answers(by_test: dict[str, str]) -> Callable[[str], str]:
    return lambda test: by_test.get(test, runner.UNKNOWN)


def test_no_failure_is_excused_by_a_whole_run() -> None:
    assert "excused_by_run" not in {field.name for field in dataclasses.fields(compare.Verdict)}
    assert "on_base" not in inspect.signature(compare.confirm).parameters


def test_a_failure_known_on_dev_still_blocks_unless_it_fails_alone_there() -> None:
    verdict = compare.confirm(["t::x"], known_on_dev={"t::x"}, rerun_with_change=_answers({"t::x": runner.FAILED}),
                              rerun_on_base=_answers({}))  # fmt: skip

    assert verdict.unconfirmed == ("t::x",) and verdict.blocking == ("t::x",) and verdict.excused == ()


def test_confirmations_run_side_by_side_and_known_on_dev_starts_last() -> None:
    together, starts, lock = threading.Barrier(2, timeout=30), [], threading.Lock()

    def with_change(test: str) -> str:
        with lock:
            starts.append(test)
        if test in ("t::a", "t::b"):
            together.wait()  # a serial run never gets past this
        return runner.FAILED

    base = _answers({"t::a": runner.PASSED, "t::b": runner.PASSED, "t::known": runner.FAILED})
    verdict = compare.confirm(["t::known", "t::a", "t::b"], known_on_dev={"t::known"}, workers=2,
                              rerun_with_change=with_change, rerun_on_base=base, again_on_base=base)  # fmt: skip

    assert starts[-1] == "t::known"
    assert verdict.findings == ("t::a", "t::b") and verdict.excused == ("t::known",)


def test_an_excuse_found_beside_other_re_runs_is_settled_again_alone() -> None:
    asked = {"t::a": 0}

    def on_base(test: str) -> str:
        if test != "t::a":
            return runner.PASSED
        asked["t::a"] += 1
        return runner.FAILED if asked["t::a"] == 1 else runner.PASSED

    changed = _answers({"t::a": runner.FAILED, "t::b": runner.FAILED})
    verdict = compare.confirm(["t::a", "t::b"], workers=2, rerun_with_change=changed, rerun_on_base=on_base,
                              again_on_base=on_base)  # fmt: skip

    assert verdict.findings == ("t::a", "t::b") and verdict.excused == () and asked["t::a"] == 2


def test_excuses_are_settled_again_one_at_a_time_in_their_own_slot_without_using_the_cap() -> None:
    first: list[str] = []
    again: list[str] = []
    running = most = 0
    lock = threading.Lock()

    def on_base(test: str) -> str:
        with lock:
            first.append(test)
        return runner.FAILED

    def again_on_base(test: str) -> str:
        nonlocal running, most
        with lock:
            running += 1
            most = max(most, running)
            again.append(test)
        threading.Event().wait(0.2)  # held open, so a second pass run side by side would overlap here
        with lock:
            running -= 1
        return runner.FAILED

    changed = _answers({"t::a": runner.FAILED, "t::b": runner.FAILED})
    verdict = compare.confirm(["t::a", "t::b"], workers=2, cap=2, rerun_with_change=changed, rerun_on_base=on_base,
                              again_on_base=again_on_base)  # fmt: skip

    assert verdict.excused == ("t::a", "t::b") and verdict.unconfirmed == (), "the cap counts only the failures tried"
    assert sorted(first) == ["t::a", "t::b"] and again == ["t::a", "t::b"] and most == 1


def test_re_runs_side_by_side_are_refused_without_a_sandbox_of_their_own_for_the_second_dev_settling() -> None:
    """Falling back to the first dev re-run's sandbox would settle an excuse in a folder its neighbours wrote in."""
    ran: list[str] = []

    def record(test: str) -> str:
        ran.append(test)
        return runner.FAILED

    with pytest.raises(ValueError, match="again_on_base"):
        compare.confirm(["t::a", "t::b"], workers=2, rerun_with_change=record, rerun_on_base=record)
    assert ran == [], "refused before any re-run started"


def test_a_re_run_the_pool_gave_no_place_proved_nothing_and_is_never_called_unsettled(tmp_path: Path) -> None:
    """SC1: a refusal is not a failure and not a pass. Read as UNKNOWN it became "unconfirmed", which blocks."""
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_pair.py").write_text("def test_fails(): pass\n", encoding="utf-8")

    def refused(*_a: object, **_k: object) -> tuple[int, str]:
        return environment.REFUSED, "no place in the pool of test processes"

    answer = runner.run_one(tmp_path, "tests/test_pair.py::test_fails", python=sys.executable, data_dir=tmp_path / "d",
                            run=refused)  # fmt: skip

    assert answer == runner.NO_PLACE and answer != runner.UNKNOWN
    changed = _answers({"t::a": runner.NO_PLACE, "t::b": runner.FAILED, "t::c": runner.FAILED, "t::d": runner.FAILED})
    on_dev = _answers({"t::b": runner.NO_PLACE, "t::c": runner.PASSED, "t::d": runner.FAILED})
    again = _answers({"t::d": runner.NO_PLACE})
    for workers in (1, 2):
        verdict = compare.confirm(["t::a", "t::b", "t::c", "t::d"], workers=workers, rerun_with_change=changed,
                                  rerun_on_base=on_dev, again_on_base=again)  # fmt: skip
        settled_again = ("t::d",) if workers > 1 else ()
        assert verdict.not_started == ("t::a", "t::b", *settled_again), workers
        assert verdict.findings == ("t::c",) and verdict.unconfirmed == () and verdict.blocking == ("t::c",)
