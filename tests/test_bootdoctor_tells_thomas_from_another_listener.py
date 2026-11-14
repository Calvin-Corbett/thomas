"""BootDoctor counts a listener as Thomas only when it is Thomas.

Any HTTP listener on the port used to count, so an unrelated program made BootDoctor refuse to run, and a rescue
reported a foreign server as "Thomas is healthy again". A Thomas that is still starting, or too busy to answer
/api/health in time, has bound the port without answering, so a Thomas process listening counts too; only a foreign
owner is left out.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

import thomas.bootdoctor.__main__ as bd_main
import thomas.core.boot_process as boot_process
from tests._bootdoctor_fakes import (
    ForeignServer,
    JsonList,
    JsonVersionOnly,
    JsonWithoutVersion,
    ThomasServer,
    fake_owners,
    isolate_offline_checks,
    listener,
    raw_listener,
)
from thomas.core.boot_checks import answers_as_thomas
from thomas.core.config import AppConfig, MemoryConfig

WINDOWS_ONLY = pytest.mark.skipif(os.name != "nt", reason="the port owner is looked up with netstat on Windows")
THOMAS_CMD = r"C:\x\.venv\Scripts\python.exe -m thomas.server"
OTHER_CMD = r"C:\Program Files\Other\app.exe --serve"


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    fake_owners(monkeypatch)


@pytest.mark.parametrize("handler", [ForeignServer, JsonWithoutVersion, JsonVersionOnly, JsonList])
def test_a_foreign_listener_is_not_taken_for_thomas(handler) -> None:
    # An HTML 404, a 200 whose JSON has no "version", one with no "status", and a body that is not an object at all.
    with listener(handler) as port:
        assert bd_main._runtime_detected("127.0.0.1", port) is False


def test_a_program_that_is_not_a_web_server_is_not_thomas_and_does_not_stop_the_report(tmp_path: Path) -> None:
    # urlopen raises http.client.BadStatusLine for an answer that is not HTTP. It is not an OSError, so a check that
    # only expected OSError would end `bootdoctor report` and `rescue` in a traceback when such a program holds the port.
    with raw_listener() as port:
        assert answers_as_thomas("127.0.0.1", port) is False
        assert bd_main._runtime_detected("127.0.0.1", port) is False
        report = bd_main._run_report(
            config=AppConfig(memory=MemoryConfig(root=str(tmp_path / "mem"))),
            root=tmp_path,
            port=port,
            reason="port check",
            report_path=None,
            auto_repair=False,
            allow_ai=False,
        )
    text = report.read_text(encoding="utf-8")
    status = json.loads((tmp_path / "runtime" / "boot_doctor" / "rescue_status.json").read_text(encoding="utf-8"))

    assert "(Fallback)" not in text
    assert re.search(rf"\[fail\] port_probe: Port {port} ", text)
    assert (status["severity"], status["recovered"], status["blocking"]) == ("fatal", False, True)


def test_a_listener_that_answers_with_thomas_health_is_detected() -> None:
    with listener(ThomasServer) as port:
        assert bd_main._runtime_detected("127.0.0.1", port) is True


def test_a_thomas_that_is_still_starting_counts_but_a_foreign_owner_does_not(monkeypatch) -> None:
    # Bound the port, answering nothing yet: the window before /api/health first replies.
    starting = {"ready": False, "severity": "fatal", "listening": True, "probe_results": []}
    monkeypatch.setattr(bd_main, "probe_boot_runtime", lambda port, host="127.0.0.1": starting)

    monkeypatch.setattr(bd_main, "thomas_owns_port", lambda port: True)
    assert bd_main._runtime_detected("127.0.0.1", 22058) is True

    monkeypatch.setattr(bd_main, "thomas_owns_port", lambda port: False)
    assert bd_main._runtime_detected("127.0.0.1", 22058) is False


def test_a_busy_thomas_that_misses_the_second_request_still_counts(monkeypatch) -> None:
    # The probes passed, then the /api/health identity request timed out: Thomas under load, not another program.
    ready = {"ready": True, "severity": "healthy", "listening": True, "probe_results": []}
    monkeypatch.setattr(bd_main, "probe_boot_runtime", lambda port, host="127.0.0.1": ready)
    monkeypatch.setattr(bd_main, "answers_as_thomas", lambda host, port: False)

    monkeypatch.setattr(bd_main, "thomas_owns_port", lambda port: True)
    assert bd_main._runtime_detected("127.0.0.1", 22058) is True

    monkeypatch.setattr(bd_main, "thomas_owns_port", lambda port: False)
    assert bd_main._runtime_detected("127.0.0.1", 22058) is False


def test_a_port_nobody_listens_on_is_not_detected(monkeypatch) -> None:
    free = {"ready": False, "severity": "fatal", "listening": False, "probe_results": []}
    monkeypatch.setattr(bd_main, "probe_boot_runtime", lambda port, host="127.0.0.1": free)
    monkeypatch.setattr(bd_main, "thomas_owns_port", lambda port: True)

    assert bd_main._runtime_detected("127.0.0.1", 22058) is False


@WINDOWS_ONLY
def test_thomas_owns_the_port_when_a_listening_process_runs_thomas(monkeypatch) -> None:
    fake_owners(monkeypatch, {101: OTHER_CMD, 202: THOMAS_CMD})
    assert boot_process.thomas_owns_port(22058) is True

    fake_owners(monkeypatch, {101: OTHER_CMD})
    assert boot_process.thomas_owns_port(22058) is False


def test_the_report_says_a_foreign_listener_is_not_thomas(tmp_path: Path) -> None:
    with listener(ForeignServer) as port:
        report = bd_main._run_report(
            config=AppConfig(memory=MemoryConfig(root=str(tmp_path / "mem"))),
            root=tmp_path,
            port=port,
            reason="port check",
            report_path=None,
            auto_repair=False,
            allow_ai=False,
        )
    text = report.read_text(encoding="utf-8")

    assert "healthy Thomas endpoint" not in text
    assert f"[fail] port_probe: Port {port} answers HTTP but not as Thomas" in text


def test_a_plain_check_runs_beside_a_running_thomas_but_moving_files_refuses(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    with listener(ThomasServer) as port:
        assert bd_main.main(["check", "--root", str(tmp_path), "--port", str(port)]) == 0
        assert bd_main.main(["check", "--quarantine", "--root", str(tmp_path), "--port", str(port)]) == 2


@WINDOWS_ONLY
def test_the_port_owner_note_names_the_program_and_never_its_command_line(monkeypatch) -> None:
    fake_owners(
        monkeypatch,
        {
            101: r'"C:\Program Files\Chat\chat.exe" --token=SECRET123 --user alice',
            202: r"C:\Users\alice\Thomas\.venv\Scripts\python.exe -m thomas.server --port 22058",
        },
    )

    note = boot_process.port_owner_note(22058)

    assert "PID 101 (chat.exe) is not a Thomas process" in note
    assert "PID 202 (python.exe) is a Thomas process" in note
    for leaked in ("SECRET123", "alice", "--token", r"C:\Users"):
        assert leaked not in note


@pytest.mark.parametrize(
    ("cmdline", "name"),
    [
        (r'"C:\Program Files\Chat\chat.exe" --token=abc', "chat.exe"),
        (r"C:\Users\me\Thomas\.venv\Scripts\python.exe -m thomas.server", "python.exe"),
        (r"C:\Program Files (x86)\Some App\tool.exe", "tool.exe"),
        ("/usr/bin/python3 -m thomas.server", "python3"),
        ("", ""),
    ],
)
def test_process_name_keeps_only_the_program(cmdline: str, name: str) -> None:
    assert boot_process.process_name(cmdline) == name
