"""scripts/praxis/check_load.py starts its checks in the same second, records their clocks, and leaves no copy behind.

Spec 2026-10-12 Part 1's pass line is about 6 hand-ins arriving together, which real traffic rarely does, so the pass
line is measured by a staged run whose checks write the same clocks a real hand-in does.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts.praxis import check_load
from scripts.praxis.check_load_machine import Reading

from thomas.server import green_checkout
from thomas.server.precard import check, clocks

# A machine with no other work on it, so these tests read nothing real.
_quiet = SimpleNamespace(available=True, own_from="a fake sampler", read=lambda: Reading(time.time(), 1.0, 0.0, 0))


def test_modules_are_picked_by_how_many_test_files_cover_them(tmp_path: Path) -> None:
    blue = tmp_path / "blue"
    (blue / "thomas").mkdir(parents=True)
    for name in ("few", "many", "right"):
        (blue / "thomas" / f"{name}.py").write_text("X = 1\n", encoding="utf-8")
    (blue / "thomas" / "huge.py").write_text("X = 1\n" * 790, encoding="utf-8")
    texts = {"tests/test_architecture.py": ""}
    for name, count in (("right", 30), ("many", 130), ("huge", 30), ("few", 3)):
        texts.update({f"tests/test_{name}_{n}.py": f"from thomas import {name}\n" for n in range(count)})

    picked = check_load.pick_modules(blue, count=2, min_files=20, max_files=120, texts=texts)

    assert picked == [("thomas/right.py", 31)], "too many importers, too long a file and too few are all passed over"
    assert check_load.pick_modules(blue, count=0, min_files=1, max_files=120, texts=texts) == []


def test_the_checks_start_together_and_their_copies_are_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    made: list[str] = []
    removed: list[str] = []
    started: list[float] = []

    def create(*, blue: Path, execution_id: str) -> SimpleNamespace:
        work = tmp_path / "work" / execution_id
        (work / "thomas").mkdir(parents=True)
        (work / "thomas" / "right.py").write_text("X = 1\n", encoding="utf-8")
        made.append(execution_id)
        return SimpleNamespace(execution_id=execution_id, work=work)

    def checked(execution_id: str, *, files: list[str] | None = None) -> check.Checked:
        started.append(time.time())
        time.sleep(0.2)
        clocks.note("selected_files", 31)
        return check.Checked(check.PASSED, "checked")

    monkeypatch.setattr(check_load.green_checkout, "create_green", create)
    monkeypatch.setattr(check_load.green_checkout, "remove_green", lambda green: removed.append(green.execution_id))
    monkeypatch.setattr(check_load.green_checkout, "green_root", lambda: tmp_path)
    monkeypatch.setattr(check_load.precard, "check_before_card", checked)
    monkeypatch.setattr(check_load, "SAMPLE_S", 0.05)  # free disk is read inside each 0.2 s check
    catalog = tmp_path / "catalog"

    picked = [("thomas/right.py", 31)] * 3

    result = check_load.run_load(tmp_path / "blue", catalog, picked, stamp="t1", sampler=_quiet)

    assert len(made) == 3 and sorted(removed) == sorted(made)
    assert max(started) - min(started) < 1.0, "they started together"
    assert [entry["state"] for entry in result["checks"]] == ["passed"] * 3
    assert result["free_disk_min_bytes"] > 0 and result["free_disk_start_bytes"] > 0
    assert all(entry["free_disk_min_bytes"] > 0 and entry["disk_peak_bytes"] >= 0 for entry in result["checks"])
    assert result["check_disk_peak_bytes"] == max(entry["disk_peak_bytes"] for entry in result["checks"])
    assert datetime.fromisoformat(result["started_at_local"]).timestamp() == pytest.approx(result["started_at"], abs=1)
    assert set(check_load.disk_record(result)) == {"schema", "measured_at", "checks", "selected_files",
                                                    "free_disk_start_bytes", "free_disk_min_bytes",
                                                    "check_disk_peak_bytes"}  # fmt: skip
    for execution_id in made:
        assert (
            (tmp_path / "work" / execution_id / "thomas" / "right.py")
            .read_text(encoding="utf-8")
            .endswith(check_load.MARK)
        )
    records = [json.loads(line) for line in clocks.clocks_path(catalog).read_text(encoding="utf-8").splitlines()]
    assert len(records) == 3
    assert all(
        r["load_run"] == "t1" and r["selected_files"] == 31 and "check_for_hand_in" in r["stages"] for r in records
    )
    assert result["copies_left"] == []
    assert result["quiet"] is True and result["other_load"]["own_cpu_from"] == "a fake sampler"


def test_a_load_run_refuses_while_the_check_is_turned_off(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setenv(check.CHECK_ENV, "off")

    assert check_load.main(["--count", "2"]) == 2
    assert check.CHECK_ENV in capsys.readouterr().out


def test_a_checks_disk_is_read_inside_its_own_stage_window() -> None:
    entry = {"ran_from": 10.0, "ran_to": 20.0}
    samples = [(5.0, 50 * 2**30), (12.0, 47 * 2**30), (18.0, 46 * 2**30), (25.0, 40 * 2**30)]

    check_load._disk(entry, samples, 50 * 2**30)

    assert entry["free_disk_min_bytes"] == 46 * 2**30 and entry["disk_peak_bytes"] == 4 * 2**30
    freed = {"ran_from": 10.0, "ran_to": 20.0}
    check_load._disk(freed, [(5.0, 52 * 2**30), (12.0, 49 * 2**30)], 50 * 2**30)
    assert freed["disk_peak_bytes"] == 3 * 2**30, "disk freed before it began is not taken off its own use"
    slot = {"start": "2026-10-12T10:00:05.000+00:00", "end": "2026-10-12T10:01:00.000+00:00"}
    ran_from, ran_to = check_load._ran({"stages": {"in_slot": slot}}, 0.0, 1.0)
    assert ran_to - ran_from == 55.0, "the in_slot window is used, not the whole call"
    assert check_load._ran({"stages": {}}, 3.0, 4.0) == (3.0, 4.0)


def _passes(execution_id: str, *, files: list[str] | None = None) -> check.Checked:
    time.sleep(0.05)
    return check.Checked(check.PASSED, "checked")


def _install(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    fake_check,
    *,
    held: tuple[str, ...] = (),
    fail_third: bool = False,
    module_exists: bool = True,
) -> tuple[list[str], list[str]]:
    """Fake copies that record what was made and what removal was tried on; *held* ones refuse to be removed."""
    made: list[str] = []
    removed: list[str] = []

    def create(*, blue: Path, execution_id: str) -> SimpleNamespace:
        if fail_third and len(made) == 2:
            raise green_checkout.GreenUnavailable("there is no room for another copy")
        work = tmp_path / "work" / execution_id
        (work / "thomas").mkdir(parents=True)
        if module_exists:
            (work / "thomas" / "right.py").write_text("X = 1\n", encoding="utf-8")
        made.append(execution_id)
        return SimpleNamespace(execution_id=execution_id, work=work)

    def remove(green: SimpleNamespace) -> None:
        removed.append(green.execution_id)
        if green.execution_id in held:
            raise OSError(f"{green.execution_id} is held open")

    monkeypatch.setattr(check_load.green_checkout, "create_green", create)
    monkeypatch.setattr(check_load.green_checkout, "remove_green", remove)
    monkeypatch.setattr(check_load.green_checkout, "green_root", lambda: tmp_path)
    monkeypatch.setattr(check_load.precard, "check_before_card", fake_check)
    monkeypatch.setattr(check_load, "SAMPLE_S", 0.05)
    return made, removed


def _load(tmp_path: Path, stamp: str, copies: int = 3) -> dict:
    picked = [("thomas/right.py", 31)] * copies
    return check_load.run_load(tmp_path / "blue", tmp_path / "catalog", picked, stamp=stamp, sampler=_quiet)


def test_every_copy_is_removed_when_a_check_raises_and_a_removal_failure_does_not_hide_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    def broken(execution_id: str, *, files: list[str] | None = None) -> check.Checked:
        if execution_id.endswith("-2"):
            raise RuntimeError("the check itself broke")
        return _passes(execution_id)

    made, removed = _install(tmp_path, monkeypatch, broken, held=("load-t2-1",))

    with pytest.raises(RuntimeError, match="the check itself broke"):
        _load(tmp_path, "t2")

    assert len(made) == 3 and sorted(removed) == sorted(made), "a copy that will not go does not stop the others"
    err = capsys.readouterr().err
    assert "load-t2-1" in err and "held open" in err, "the copy that could not be removed is reported"
    assert "load-t2-2" in err and "the check itself broke" in err, "and so is the check's own error"
    records = clocks.clocks_path(tmp_path / "catalog").read_text(encoding="utf-8")
    assert '"outcome": "RuntimeError"' in records, "the clocks say the check raised"


def test_a_copy_that_will_not_go_is_reported_with_the_result(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    made, removed = _install(tmp_path, monkeypatch, _passes, held=("load-t3-2",))

    result = _load(tmp_path, "t3", copies=2)

    assert sorted(removed) == sorted(made) and len(result["checks"]) == 2
    (left,) = result["copies_left"]
    assert left["execution_id"] == "load-t3-2" and "held open" in left["error"]
    assert left["work"] == str(tmp_path / "work" / "load-t3-2")


@pytest.mark.parametrize(
    ("fault", "error", "made_before"),
    [({"fail_third": True}, green_checkout.GreenUnavailable, 2), ({"module_exists": False}, FileNotFoundError, 1)],
    ids=["the next copy cannot be made", "the module cannot be marked"],
)
def test_copies_already_made_are_removed_when_making_the_next_step_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: dict, error: type[Exception], made_before: int
) -> None:
    made, removed = _install(tmp_path, monkeypatch, _passes, **fault)

    with pytest.raises(error):
        _load(tmp_path, "t4")

    assert len(made) == made_before and sorted(removed) == sorted(made), "a copy made before the fault goes too"


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_check_that_ends_without_an_answer_is_an_error_not_a_gap_in_the_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def odd(execution_id: str, *, files: list[str] | None = None) -> check.Checked:
        raise AssertionError("not one of the faults a check is expected to have")

    made, removed = _install(tmp_path, monkeypatch, odd)

    with pytest.raises(RuntimeError, match="without an answer"):
        _load(tmp_path, "t8", copies=2)

    assert len(made) == 2 and sorted(removed) == sorted(made)


def test_copies_are_removed_when_the_run_is_interrupted(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    made, removed = _install(tmp_path, monkeypatch, _passes)

    def interrupt(path: Path) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(check_load, "shutil", SimpleNamespace(disk_usage=interrupt))  # read after every copy is made

    with pytest.raises(KeyboardInterrupt):
        _load(tmp_path, "t6")

    assert len(made) == 3 and sorted(removed) == sorted(made)


def test_the_mark_leaves_every_other_byte_of_the_module_alone(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    mark = check_load.MARK.encode("utf-8")
    target.write_bytes(b"X = 1\r\nY = 2\r\n")
    check_load._mark(target)
    crlf = b"X = 1\r\nY = 2\r\n\r\n\r\n" + mark.replace(b"\n", b"\r\n")
    assert target.read_bytes() == crlf, "a Windows file keeps its line ends and is not rewritten line by line"
    target.write_bytes(b"X = 1")
    check_load._mark(target)
    assert target.read_bytes() == b"X = 1\n\n\n" + mark, "two blank lines set the mark apart, as ruff format wants"


def _fake_result(started: float, left: list[dict]) -> dict:
    base = {"module": "thomas/secret_module.py", "seconds": 1.5}
    checks = [
        {"execution_id": "load-t7-1", "state": "passed", "cause": "", **base},
        {"execution_id": "load-t7-2", "state": "unavailable", "cause": "dev-side", **base},
    ]
    return {
        "stamp": "t7", "started_at": started, "ended_at": started + 60, "checks": checks, "copies_left": left,
        "free_disk_start_bytes": 100, "free_disk_min_bytes": 90, "check_disk_peak_bytes": 7,
    }  # fmt: skip


def test_main_prints_each_check_and_the_timeline_window_and_writes_aggregates_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.delenv(check.CHECK_ENV, raising=False)  # tests/conftest.py turns the check off for every test
    started = time.time()
    monkeypatch.setattr(check_load, "pick_modules", lambda blue, **kwargs: [("thomas/secret_module.py", 25)] * 2)
    monkeypatch.setattr(check_load, "run_load", lambda *args, **kwargs: _fake_result(started, []))
    disk_out = tmp_path / "repo" / "disk.json"

    code = check_load.main(
        ["--count", "2", "--blue", str(tmp_path), "--out-dir", str(tmp_path / "out"), "--disk-out", str(disk_out)]
    )

    lines = capsys.readouterr().out.splitlines()
    assert code == 0 and "passed, unavailable dev-side" in "\n".join(lines)
    since, rest = lines[-1].removeprefix("timeline: --since ").split(" --until ")
    until, catalog = rest.split(" --catalog-root ")
    assert catalog == str(tmp_path), "the timeline reads the folder this run wrote its clocks into"
    assert datetime.fromisoformat(since).timestamp() == pytest.approx(started - 300, abs=1)
    assert datetime.fromisoformat(until).timestamp() == pytest.approx(started + 360, abs=1)
    recorded = disk_out.read_text(encoding="utf-8")
    assert json.loads(recorded)["check_disk_peak_bytes"] == 7 and json.loads(recorded)["checks"] == 2
    assert not any(secret in recorded for secret in ("load-t7", "secret_module", str(tmp_path)))


def test_main_says_which_copies_it_could_not_remove_and_exits_non_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.delenv(check.CHECK_ENV, raising=False)
    left = [{"execution_id": "load-t7-2", "work": str(tmp_path / "work" / "load-t7-2"), "error": "OSError: held open"}]
    monkeypatch.setattr(check_load, "pick_modules", lambda blue, **kwargs: [("thomas/a.py", 25)] * 2)
    monkeypatch.setattr(check_load, "run_load", lambda *args, **kwargs: _fake_result(time.time(), left))

    code = check_load.main(["--count", "2", "--blue", str(tmp_path), "--out-dir", str(tmp_path / "out")])

    out = capsys.readouterr().out
    assert code == 1 and left[0]["work"] in out and "held open" in out
    assert out.splitlines()[-1].startswith("timeline: --since "), "the window is still the last line"
