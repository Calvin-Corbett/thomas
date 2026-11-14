"""BootDoctor's report for a failed start names what broke, and never crashes on the way there.

The recovery tool run-ui.ps1 launches failed on its own first steps. It opened its probe log in a folder a fresh
install does not have yet, so the report came out as a "(Fallback)" traceback with no findings; the stale "known
startup repair" blocks that followed rewrote source files whose targets no longer exist. Even when it did run, it
looked at nothing but the port: a damaged database or a thomas.toml that will not parse read [ok]. The rescue
prompt it builds was one line of literal backtick-n.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

import thomas.bootdoctor.__main__ as bd_main
import thomas.core.boot_doctor as boot_doctor
import thomas.core.boot_process as boot_process
from tests._bootdoctor_fakes import fake_owners, isolate_offline_checks
from thomas.bootdoctor.runtime_helpers import build_rescue_prompt
from thomas.core.boot_doctor import read_boot_recovery_notice
from thomas.core.config import AppConfig, MemoryConfig

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    fake_owners(monkeypatch)


def _patch_failed_start(monkeypatch: pytest.MonkeyPatch, log_text: str) -> None:
    class _Proc:
        pid = 4242

        def poll(self) -> int:
            return 1

    def _spawn(*, py_exe, root, host, port, stdout):
        stdout.write(log_text)
        stdout.flush()
        return _Proc()

    monkeypatch.setattr(boot_doctor, "_resolve_python", lambda root: Path(sys.executable).resolve())
    monkeypatch.setattr(boot_doctor, "_run_cmd", lambda *args, **kwargs: (True, "exit=0"))
    monkeypatch.setattr(boot_doctor, "_thomas_http_healthy", lambda port: False)
    monkeypatch.setattr(boot_doctor, "_is_port_listening", lambda host, port, timeout=0.4: False)
    monkeypatch.setattr(boot_doctor, "_kill_pid", lambda pid: True)
    monkeypatch.setattr(boot_doctor, "_spawn_thomas_server", _spawn)


def _run_report(tmp_path: Path, *, auto_repair: bool) -> Path:
    return bd_main._run_report(
        config=AppConfig(memory=MemoryConfig(root=str(tmp_path / "mem"))),
        root=tmp_path,
        port=9031,
        reason="simulated startup crash",
        report_path=None,
        auto_repair=auto_repair,
        allow_ai=False,
    )


def test_a_failed_start_on_a_fresh_install_reports_the_real_cause(tmp_path: Path, monkeypatch) -> None:
    _patch_failed_start(
        monkeypatch,
        "Traceback (most recent call last):\nsqlite3.DatabaseError: file is not a database\n",
    )
    assert not (tmp_path / "runtime").exists()

    text = _run_report(tmp_path, auto_repair=True).read_text(encoding="utf-8")

    assert "(Fallback)" not in text
    findings = text.split("Findings:")[1].split("Repairs Attempted:")[0]
    assert "[warn] startup_probe_cause: a Thomas database file is damaged" in findings
    assert "sqlite3.DatabaseError: file is not a database" in findings
    assert re.search(r"Startup probe failed \(exit=1\)\. Log: .*probe_\d{8}_\d{6}\.log", text)


def test_a_blocked_port_is_reported_as_blocked_not_as_an_unwritable_folder(tmp_path: Path, monkeypatch) -> None:
    # aiohttp raises PermissionError for WinError 10013 when the port sits in a Hyper-V/WSL reserved range.
    _patch_failed_start(
        monkeypatch,
        "Traceback (most recent call last):\n"
        "PermissionError: [WinError 10013] An attempt was made to access a socket in a way forbidden by its "
        "access permissions\n",
    )

    text = _run_report(tmp_path, auto_repair=True).read_text(encoding="utf-8")

    assert "the port is blocked by Windows" in text
    assert "not writable" not in text


def test_the_stale_source_patching_repairs_are_gone(tmp_path: Path, monkeypatch) -> None:
    # The old blocks rewrote thomas/server/__main__.py, tool_extensions.py and a thomas/groupchat shim.
    _patch_failed_start(monkeypatch, "RuntimeError: Unable to locate monolith_source_loader.py in repository root\n")
    (tmp_path / "thomas" / "server").mkdir(parents=True)
    main_py = tmp_path / "thomas" / "server" / "__main__.py"
    main_py.write_text("from thomas.server.app import serve\n", encoding="utf-8")

    text = _run_report(tmp_path, auto_repair=True).read_text(encoding="utf-8")

    assert "(Fallback)" not in text
    assert "Known startup repair" not in text
    assert main_py.read_text(encoding="utf-8") == "from thomas.server.app import serve\n"
    assert not (tmp_path / "thomas" / "groupchat").exists()


def test_an_unwritable_runtime_folder_still_gets_a_report(tmp_path: Path) -> None:
    (tmp_path / "runtime").write_text("a file where the folder should be", encoding="utf-8")
    (tmp_path / "thomas.toml").write_text("[server\nport = = 1\n", encoding="utf-8")

    report = _run_report(tmp_path, auto_repair=False)
    try:
        text = report.read_text(encoding="utf-8")
        assert report.parent == Path(tempfile.gettempdir())
        assert "Fallback" in text
        # The full report failed, but the fallback still says what the offline checks found.
        assert re.search(r"\[fail\] config_file: .*thomas\.toml: .*line 1", text)
        assert re.search(r"\[fail\] state_dir_writable: .*runtime: .*is a file, not a folder", text)
    finally:
        report.unlink(missing_ok=True)


def test_the_report_names_a_damaged_database_and_a_config_that_will_not_parse(tmp_path: Path) -> None:
    (tmp_path / "mem" / ".thomas").mkdir(parents=True)
    (tmp_path / "mem" / ".thomas" / "runs.sqlite3").write_bytes(b"not a database, only text padding" * 4)
    (tmp_path / "thomas.toml").write_text("[server\nport = = 1\n", encoding="utf-8")

    text = _run_report(tmp_path, auto_repair=False).read_text(encoding="utf-8")

    assert re.search(r"\[fail\] database_integrity: .*runs\.sqlite3: file is not a database", text)
    assert re.search(r"\[fail\] config_file: .*thomas\.toml: .*line 1", text)
    status = json.loads((tmp_path / "runtime" / "boot_doctor" / "rescue_status.json").read_text(encoding="utf-8"))
    assert "runs.sqlite3" in status["ai_summary"]
    assert "thomas.toml" in status["ai_summary"]
    # The notice the web UI shows carries the same failed findings; without them it only said
    # "No suitable model profile configured for AI diagnosis."
    notice = read_boot_recovery_notice(tmp_path)
    assert notice is not None
    assert "runs.sqlite3" in notice["needs_attention"]
    assert "thomas.toml" in notice["needs_attention"]


def test_the_rescue_prompt_is_one_instruction_per_line() -> None:
    args = SimpleNamespace(port=22058, reason="runtime not detected")
    prompt = build_rescue_prompt(
        args=args,
        context={"stderr_tail": 'File "thomas/agent/loop.py", line 3', "startup_log_paths": ["runtime/logs/a.log"]},
        report_excerpt="Findings: none",
        root=ROOT,
        attempt_number=1,
        max_attempts=3,
    )

    assert "`n" not in prompt
    lines = prompt.splitlines()
    assert lines[0] == "Thomas failed to become healthy during startup."
    assert "Attempt: 1/3" in lines
    assert "Port: 22058" in lines


def test_nothing_points_the_rescue_at_part_files_that_do_not_exist() -> None:
    for name in ("__main__.py", "runtime_helpers.py", "check_command.py"):
        source = (ROOT / "thomas" / "bootdoctor" / name).read_text(encoding="utf-8")
        assert "_part*" not in source, name
        assert "utcnow" not in source, name


def _creation_flags_of(call, monkeypatch: pytest.MonkeyPatch) -> list:
    """Run ``call`` with subprocess faked, and return the creationflags of every child it tried to start."""
    flags: list = []

    def fake_run(cmd, **kwargs):
        flags.append(kwargs.get("creationflags"))
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    class FakePopen:
        def __init__(self, cmd, **kwargs) -> None:
            flags.append(kwargs.get("creationflags"))

    monkeypatch.setattr(boot_process.subprocess, "run", fake_run)
    monkeypatch.setattr(boot_process.subprocess, "Popen", FakePopen)
    monkeypatch.setitem(sys.modules, "psutil", None)  # _pid_cmdline then asks PowerShell
    call()
    return flags


# Taken at import, before the autouse fixture replaces the two lookups with stand-ins.
_REAL_LISTENING_PIDS = boot_process._listening_pids_windows
_REAL_PID_CMDLINE = boot_process._pid_cmdline
_CHILDREN = {
    "netstat": lambda: _REAL_LISTENING_PIDS(22058),
    "powershell": lambda: _REAL_PID_CMDLINE(4242),
    "taskkill": lambda: boot_process._kill_pid(4242),
    "helper command": lambda: boot_process._run_cmd(["python", "-c", "pass"], cwd=Path.cwd()),
    "probe server": lambda: boot_process._spawn_thomas_server(
        py_exe=Path("python"), root=Path.cwd(), host="127.0.0.1", port=22058, stdout=None
    ),
}


@pytest.mark.skipif(os.name != "nt", reason="CREATE_NO_WINDOW is a Windows process flag")
@pytest.mark.parametrize("child", list(_CHILDREN))
def test_every_console_child_bootdoctor_starts_asks_windows_for_no_window(child: str, monkeypatch) -> None:
    # Recovery runs from a process with no console of its own, so each child would otherwise open a window.
    flags = _creation_flags_of(_CHILDREN[child], monkeypatch)

    assert flags == [subprocess.CREATE_NO_WINDOW]


def test_the_findings_carry_the_last_fifteen_lines_of_the_probe_log(tmp_path: Path, monkeypatch) -> None:
    # They are findings, not the end of the report: the repairs and the offline steps follow them.
    _patch_failed_start(monkeypatch, "".join(f"probe log line {n}\n" for n in range(40)))

    text = _run_report(tmp_path, auto_repair=True).read_text(encoding="utf-8")

    findings = text.split("Findings:")[1].split("Repairs Attempted:")[0]
    assert "[warn] startup_probe_log_tail: last lines of the probe log:" in findings
    assert "probe log line 39" in findings
    assert "probe log line 25" in findings
    assert "probe log line 24" not in text


def test_a_warning_is_not_a_problem_the_status_and_notice_carry(tmp_path: Path) -> None:
    # "No suitable model profile" is a [warn] row; only [fail] rows are what needs your attention.
    (tmp_path / "thomas.toml").write_text("[server\n", encoding="utf-8")

    text = _run_report(tmp_path, auto_repair=False).read_text(encoding="utf-8")
    status = json.loads((tmp_path / "runtime" / "boot_doctor" / "rescue_status.json").read_text(encoding="utf-8"))

    assert "[warn] ai_diagnosis: No suitable model profile" in text
    assert "thomas.toml" in status["ai_summary"]
    assert "No suitable model profile" not in status["ai_summary"]
