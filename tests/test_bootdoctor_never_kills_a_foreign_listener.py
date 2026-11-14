"""BootDoctor stops only a Thomas that holds the port, and never files another program's server as a healthy start.

A web server that is not Thomas passes every runtime probe (a 404 is "an answer"), so the status and the notice used
to call it "recovered". It is now a failed start that names the taken port, and BootDoctor does not start a second
Thomas at a port it cannot bind. And the repair that frees a busy port must only ever be aimed at a Thomas process.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

import thomas.bootdoctor.__main__ as bd_main
import thomas.core.boot_doctor as boot_doctor
from tests._bootdoctor_fakes import (
    Broken,
    ForeignServer,
    JsonList,
    JsonWithoutVersion,
    ThomasServer,
    fake_owners,
    isolate_offline_checks,
    listener,
)
from thomas.core.boot_doctor import read_boot_recovery_notice
from thomas.core.config import AppConfig, MemoryConfig

WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="the port owner is looked up with netstat on Windows")
THOMAS_CMD = r"C:\x\.venv\Scripts\python.exe -m thomas.server"
OTHER_CMD = r"C:\Program Files\Other\app.exe --serve"
TAKEN = "OSError: [WinError 10048] Only one usage of each socket address (protocol/network address/port)\n"
NOT_THOMAS = "answers HTTP but not as Thomas"


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    fake_owners(monkeypatch)


class FailedLaunch:
    """Stands in for the diagnostic server launch: a process that dies at once, and a record of what was killed."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, log_text: str = TAKEN) -> None:
        self.spawned = 0
        self.killed: list[int] = []
        launch = self

        class _Proc:
            pid = 4242

            def poll(self) -> int:
                return 1

        def _spawn(*, py_exe, root, host, port, stdout):
            launch.spawned += 1
            stdout.write(log_text)
            stdout.flush()
            return _Proc()

        monkeypatch.setattr(boot_doctor, "_resolve_python", lambda root: Path(sys.executable).resolve())
        monkeypatch.setattr(boot_doctor, "_run_cmd", lambda *args, **kwargs: (True, "exit=0"))
        monkeypatch.setattr(boot_doctor, "_kill_pid", lambda pid: launch.killed.append(pid) or True)
        monkeypatch.setattr(boot_doctor, "_spawn_thomas_server", _spawn)
        monkeypatch.setattr(boot_doctor, "_bootdoctor_sleep", lambda seconds: None)


def _run(tmp_path: Path, port: int, *, auto_repair: bool, relaunch: bool = False) -> tuple[str, dict]:
    report = bd_main._run_report(
        config=AppConfig(memory=MemoryConfig(root=str(tmp_path / "mem"))),
        root=tmp_path,
        port=port,
        reason="port check",
        report_path=None,
        auto_repair=auto_repair,
        allow_ai=False,
        relaunch=relaunch,
    )
    status = json.loads((tmp_path / "runtime" / "boot_doctor" / "rescue_status.json").read_text(encoding="utf-8"))
    return report.read_text(encoding="utf-8"), status


@pytest.mark.parametrize("handler", [ForeignServer, JsonWithoutVersion, JsonList])
def test_another_programs_server_is_a_failed_start_not_a_healthy_one(tmp_path: Path, handler) -> None:
    with listener(handler) as port:
        _text, status = _run(tmp_path, port, auto_repair=False)

    assert (status["severity"], status["recovered"], status["blocking"]) == ("fatal", False, True)
    assert NOT_THOMAS in status["ai_summary"]
    notice = read_boot_recovery_notice(tmp_path)
    assert notice is not None
    assert (notice["severity"], notice["recovered"]) == ("fatal", False)
    assert NOT_THOMAS in notice["needs_attention"]
    assert "kept Thomas available" not in notice["message"]


def test_a_listener_that_answers_as_thomas_is_still_a_healthy_start(tmp_path: Path, monkeypatch) -> None:
    launch = FailedLaunch(monkeypatch)
    with listener(ThomasServer) as port:
        text, status = _run(tmp_path, port, auto_repair=True)

    assert (status["severity"], status["recovered"]) == ("healthy", True)
    assert "[ok] port_probe: Port" in text
    assert launch.spawned == 0


@pytest.mark.parametrize("relaunch", [False, True])
@pytest.mark.parametrize("handler", [ForeignServer, Broken])
def test_no_thomas_is_started_at_a_port_another_program_holds(
    tmp_path: Path, monkeypatch, handler, relaunch: bool
) -> None:
    # A second server cannot bind the port, and launching one boots the whole engine stack (and, under --relaunch,
    # leaves it running and retrying) only to find that out. The report names the taken port without it.
    launch = FailedLaunch(monkeypatch)
    with listener(handler) as port:
        text, status = _run(tmp_path, port, auto_repair=True, relaunch=relaunch)

    assert launch.spawned == 0
    assert launch.killed == []
    assert f"Startup probe skipped: what holds port {port} did not answer as Thomas when it was checked" in text
    assert re.search(rf"\[fail\] port_probe: Port {port} .*(not as Thomas|not healthy)", text)
    for untrue in ("Startup probe failed", "still initializing", "left running", "became healthy"):
        assert untrue not in text
    assert (status["severity"], status["recovered"], status["blocking"]) == ("fatal", False, True)


def test_a_listener_that_looked_like_another_program_but_answers_as_thomas_by_the_end_is_healthy(
    tmp_path: Path, monkeypatch
) -> None:
    # A Thomas that missed the identity request while it was still starting (off Windows there is no owner lookup to
    # tell it apart) must not be reported as a taken port once it answers. Only the last check decides the status.
    launch = FailedLaunch(monkeypatch)
    real = boot_doctor.answers_as_thomas
    asked: list[int] = []

    def answers_late(host: str, port: int, *args, **kwargs) -> bool:
        asked.append(port)
        return len(asked) > 2 and real(host, port)

    monkeypatch.setattr(boot_doctor, "answers_as_thomas", answers_late)
    with listener(ThomasServer) as port:
        text, status = _run(tmp_path, port, auto_repair=True, relaunch=True)

    assert len(asked) >= 3  # seen as foreign at the start, still foreign at the launch decision, Thomas by the end
    assert "[fail] port_probe" in text  # the start really did look like another program
    # The report says what was true when it checked, so it does not contradict the healthy status below.
    assert "did not answer as Thomas when it was checked, so no second server was started" in text
    assert "does not answer" not in text
    assert launch.spawned == 0
    assert (status["severity"], status["recovered"], status["blocking"]) == ("healthy", True, False)
    notice = read_boot_recovery_notice(tmp_path)
    assert notice is not None
    assert (notice["severity"], notice["recovered"]) == ("healthy", True)


@WINDOWS_ONLY
def test_a_busy_thomas_that_holds_the_port_is_not_reported_as_another_program(tmp_path: Path, monkeypatch) -> None:
    launch = FailedLaunch(monkeypatch)
    fake_owners(monkeypatch, {202: THOMAS_CMD})
    with listener(JsonWithoutVersion) as port:  # the probes pass, the identity request does not
        text, status = _run(tmp_path, port, auto_repair=True)

    assert NOT_THOMAS not in text
    assert "[fail] port_probe" not in text
    assert launch.spawned == 0
    assert status["severity"] == "healthy"


@WINDOWS_ONLY
def test_only_the_thomas_listener_is_stopped(tmp_path: Path, monkeypatch) -> None:
    launch = FailedLaunch(monkeypatch)
    fake_owners(monkeypatch, {101: OTHER_CMD, 202: THOMAS_CMD})
    with listener(Broken) as port:
        text, _status = _run(tmp_path, port, auto_repair=True)

    assert launch.killed == [202]
    assert "Stopped stale Thomas listener PID(s): 202" in text
    assert "Skipped non-Thomas or protected PID(s): 101" in text


@WINDOWS_ONLY
@pytest.mark.parametrize("handler", [Broken, ForeignServer])
def test_nothing_is_stopped_when_every_listener_is_another_program(tmp_path: Path, monkeypatch, handler) -> None:
    launch = FailedLaunch(monkeypatch)
    fake_owners(monkeypatch, {101: OTHER_CMD, 102: r"C:\Program Files\Chat\chat.exe --serve"})
    with listener(handler) as port:
        text, _status = _run(tmp_path, port, auto_repair=True)

    assert launch.killed == []
    assert "Stopped stale Thomas listener" not in text
    assert "PID 101 (app.exe) is not a Thomas process" in text
