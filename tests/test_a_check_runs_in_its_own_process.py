"""The check before your card runs in its own process, so the server stays free while it runs (2026-10-27).

Five checks inside the server held its one core at 95 to 98% and every request waited 60 to 120 s. These tests run
real child processes: a real check process for a copy that does not exist, and small stand-ins for the slow, the
silent and the orphaned cases.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time

import pytest

from thomas.server.precard import check, clocks, handover, worker_process, workers

MISSING = "thomas-000000000000"


def _verdict_script(checked: dict[str, object], observed: dict[str, object]) -> str:
    line = worker_process.RESULT_MARK + json.dumps({"checked": checked, "clocks": observed})
    return f"import sys; print('noise before the verdict'); sys.stdout.write({line!r} + '\\n')"


def test_a_check_stays_in_this_process_under_tests_unless_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(worker_process.WORKER_ENV, raising=False)
    assert not worker_process.separate()
    monkeypatch.setenv(worker_process.WORKER_ENV, "on")
    assert worker_process.separate()
    monkeypatch.setenv("THOMAS_PRECARD_PARALLEL", "off")  # one at a time is a lock in this process
    assert not worker_process.separate()
    monkeypatch.delenv("THOMAS_PRECARD_PARALLEL")
    monkeypatch.setenv(worker_process.WORKER_ENV, "off")
    assert not worker_process.separate()


def test_a_real_check_process_gives_the_same_verdict_as_this_process(monkeypatch: pytest.MonkeyPatch) -> None:
    here = handover.check_for_hand_in(MISSING, processes_ended=True)
    monkeypatch.setenv(worker_process.WORKER_ENV, "on")
    there = worker_process.check_for_hand_in(MISSING, processes_ended=True)
    assert (there.state, there.line, there.cause) == (here.state, here.line, here.cause)


def test_the_verdict_and_its_timing_notes_come_back() -> None:
    sent = {"state": check.PASSED, "line": "Checked against dev abc", "patch_sha256": "f" * 64, "dev_tip": "abc"}
    observed = {"stages": {"selection": {"start": "s", "end": "e", "seconds": 1.5}}, "selected_files": 7}
    with clocks.collecting() as record:
        checked = worker_process.run([sys.executable, "-c", _verdict_script(sent, observed)])
    assert (checked.state, checked.line, checked.dev_tip) == (check.PASSED, "Checked against dev abc", "abc")
    assert record["selected_files"] == 7 and record["stages"]["selection"]["seconds"] == 1.5


def test_a_process_that_ends_without_a_verdict_is_a_check_that_did_not_run() -> None:
    checked = worker_process.run([sys.executable, "-c", "import sys; print('boom', file=sys.stderr); sys.exit(4)"])
    assert checked.state == check.UNAVAILABLE and checked.costly
    assert "exit 4" in checked.line and "boom" in checked.line


def test_a_stopping_server_ends_its_check_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_process, "POLL_S", 0.2)
    monkeypatch.setattr(workers, "generation_stopping", lambda: True)
    started = time.monotonic()
    checked = worker_process.run([sys.executable, "-c", "import time; time.sleep(60)"])
    assert time.monotonic() - started < 20
    assert checked.state == check.UNAVAILABLE and not checked.costly and "stopping" in checked.line


def test_a_check_process_past_its_deadline_is_ended(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker_process, "POLL_S", 0.2)
    checked = worker_process.run([sys.executable, "-c", "import time; time.sleep(60)"], deadline_s=1)
    assert checked.state == check.UNAVAILABLE and "ran past 1 s" in checked.line


def test_the_check_process_prints_its_verdict_and_notes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake(execution_id: str, *, processes_ended: bool = False) -> check.Checked:
        with clocks.stage("selection"):
            clocks.note("selected_files", 3)
        return check.Checked(check.FAILED, "one test fails", findings=f"{execution_id} {processes_ended}")

    monkeypatch.setattr(handover, "check_for_hand_in", fake)
    assert worker_process.main(["thomas-abc", "--processes-ended"]) == 0
    result = worker_process._result(capsys.readouterr().out)
    assert result is not None
    assert result["checked"].state == check.FAILED and result["checked"].findings == "thomas-abc True"
    assert result["clocks"]["selected_files"] == 3 and "selection" in result["clocks"]["stages"]


def test_a_check_process_ends_itself_when_its_server_is_gone() -> None:
    server = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.5)"])
    orphan = subprocess.Popen(
        [
            sys.executable,
            "-c",
            "from thomas.server.precard import worker_process as w; import time; "
            f"w.POLL_S = 0.2; w._watch_parent({server.pid}); time.sleep(60)",
        ]
    )
    try:
        assert orphan.wait(timeout=45) == 3
    finally:
        for proc in (server, orphan):
            if proc.poll() is None:
                proc.kill()


def test_its_process_outlives_the_wait_for_a_turn_and_the_deadline() -> None:
    # 4,500 s ended checks that had waited for their turn before their hour was up (2026-10-27).
    assert worker_process.DEADLINE_S == check.ADMISSION_WAIT_S + check.CHECK_DEADLINE_S + worker_process.GRACE_S
    assert worker_process.run.__kwdefaults__["deadline_s"] == worker_process.DEADLINE_S
