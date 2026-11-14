from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

import thomas.core.boot_doctor as boot_doctor
from tests._bootdoctor_fakes import isolate_offline_checks
from thomas.bootdoctor.__main__ import (
    BootDoctorPathPolicy,
    RestrictedTool,
    _build_parser,
    _extract_patch_targets,
    _extract_repo_paths_from_text,
)
from thomas.core.boot_doctor import read_boot_recovery_notice, run_boot_doctor, write_boot_recovery_notice
from thomas.core.config import AppConfig, MemoryConfig
from thomas.tools.base import Tool, ToolResult


class _DummyWriteTool(Tool):
    name = "fs.write_file"
    category = "filesystem"
    description = "dummy write"
    parameters = {"type": "object"}

    async def execute(self, args):
        return ToolResult(ok=True, data=args.get("path", ""))


def _seed_boot_layout(root: Path) -> None:
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "thomas" / "agent").mkdir(parents=True, exist_ok=True)
    (root / "thomas" / "bootdoctor").mkdir(parents=True, exist_ok=True)
    (root / "thomas" / "core").mkdir(parents=True, exist_ok=True)
    (root / "thomas" / "server").mkdir(parents=True, exist_ok=True)
    (root / "thomas" / "tray_agent").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "logs").mkdir(parents=True, exist_ok=True)
    (root / "runtime" / "boot_doctor").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "run-ui.ps1").write_text("# test\n", encoding="utf-8")
    (root / "thomas" / "agent" / "loop_part01.py").write_text("# test\n", encoding="utf-8")


def test_bootdoctor_path_policy_scopes(tmp_path: Path) -> None:
    _seed_boot_layout(tmp_path)
    policy = BootDoctorPathPolicy(tmp_path)

    assert policy.is_read_allowed((tmp_path / "scripts" / "run-ui.ps1").resolve())
    assert policy.is_write_allowed((tmp_path / "scripts" / "run-ui.ps1").resolve())
    assert policy.is_read_allowed((tmp_path / "runtime" / "logs").resolve())
    assert policy.is_write_allowed((tmp_path / "thomas" / "agent" / "loop_part01.py").resolve())
    assert not policy.is_write_allowed((tmp_path / "README.md").resolve())


@pytest.mark.asyncio
async def test_restricted_tool_blocks_out_of_scope_write(tmp_path: Path) -> None:
    _seed_boot_layout(tmp_path)
    policy = BootDoctorPathPolicy(tmp_path)
    guarded = RestrictedTool(_DummyWriteTool(), policy)

    blocked = await guarded.execute({"path": "README.md", "content": "x"})
    assert not blocked.ok
    assert "blocked write outside boot scope" in str(blocked.error or "")

    allowed = await guarded.execute({"path": "scripts/run-ui.ps1", "content": "x"})
    assert allowed.ok


def test_extract_patch_targets_handles_git_prefixes() -> None:
    patch = "--- a/scripts/run-ui.ps1\n+++ b/scripts/run-ui.ps1\n@@ -1,1 +1,1 @@\n-old\n+new\n"
    assert _extract_patch_targets(patch) == ["scripts/run-ui.ps1"]


def test_extract_repo_paths_from_traceback_text(tmp_path: Path) -> None:
    text = (
        "Traceback (most recent call last):\n"
        f'  File "{tmp_path / "thomas" / "agent" / "loop.py"}", line 324, in <module>\n'
        f'  File "{tmp_path / "thomas" / "server" / "app.py"}", line 52, in <module>\n'
    )

    assert _extract_repo_paths_from_text(text, tmp_path) == [
        "thomas/agent/loop.py",
        "thomas/server/app.py",
    ]


def test_bootdoctor_parser_accepts_rescue_startup_context() -> None:
    parser = _build_parser()
    args = parser.parse_args(
        [
            "rescue",
            "--startup-context",
            "runtime/boot_doctor/startup_context.json",
            "--max-attempts",
            "4",
            "--relaunch",
        ]
    )

    assert args.command == "rescue"
    assert args.startup_context == "runtime/boot_doctor/startup_context.json"
    assert args.max_attempts == 4
    assert args.relaunch is True


def test_boot_recovery_notice_roundtrip_and_consume(tmp_path: Path) -> None:
    report_path = (tmp_path / "runtime" / "boot_doctor" / "boot_doctor_test.txt").resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("report", encoding="utf-8")

    write_boot_recovery_notice(
        tmp_path,
        reason="Startup watchdog timeout",
        report_path=report_path,
        repairs=["Stopped stale listener PID 1234", "Reinstalled server deps"],
        recovered=True,
        offline_fallback_reason="",
        ai_summary="Likely stale port ownership during relaunch.",
    )

    notice = read_boot_recovery_notice(tmp_path, consume=False)
    assert notice is not None
    assert notice["recovered"] is True
    assert "Startup watchdog timeout" in str(notice["message"])
    assert "Stopped stale listener PID 1234" in str(notice["message"])

    consumed = read_boot_recovery_notice(tmp_path, consume=True)
    assert consumed is not None
    assert read_boot_recovery_notice(tmp_path, consume=False) is None


class _Launch:
    """A fake server launch: what BootDoctor spawned, what it killed, and how healthy the port looks."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, healthy_once_spawned: bool) -> None:
        self.spawned: list[object] = []
        self.killed: list[int] = []
        self.clock = 0.0
        launch = self

        class _Proc:
            pid = 4101

            def poll(self):
                return None  # still running

        def _spawn(*, py_exe, root, host, port, stdout):
            stdout.write("14:08:17 [thomas.server] INFO: Thomas starting\n")
            stdout.flush()
            proc = _Proc()
            launch.spawned.append(proc)
            return proc

        def _jump_the_clock(seconds: float) -> None:
            # A real sleep would run the launch deadline out for real; move the clock instead.
            launch.clock += 100.0

        monkeypatch.setattr(boot_doctor, "_resolve_python", lambda root: Path(sys.executable).resolve())
        monkeypatch.setattr(boot_doctor, "_run_cmd", lambda *args, **kwargs: (True, "exit=0"))
        monkeypatch.setattr(boot_doctor, "_is_port_listening", lambda host, port, timeout=0.4: False)
        monkeypatch.setattr(
            boot_doctor, "_thomas_http_healthy", lambda port: healthy_once_spawned and bool(launch.spawned)
        )
        monkeypatch.setattr(boot_doctor, "_kill_pid", lambda pid: launch.killed.append(pid) or True)
        monkeypatch.setattr(boot_doctor, "_spawn_thomas_server", _spawn)
        monkeypatch.setattr(boot_doctor, "_bootdoctor_sleep", _jump_the_clock)
        monkeypatch.setattr(boot_doctor, "time", SimpleNamespace(monotonic=lambda: launch.clock))

    def run(self, tmp_path: Path, *, relaunch: bool) -> str:
        report = run_boot_doctor(
            config=AppConfig(memory=MemoryConfig(root=str(tmp_path / "mem"))),
            root=tmp_path,
            port=9011,
            reason="simulated startup crash",
            auto_repair=True,
            allow_ai=False,
            relaunch=relaunch,
        )
        return Path(report).read_text(encoding="utf-8")


def test_a_relaunch_leaves_the_healthy_server_it_started_running(tmp_path: Path, monkeypatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    launch = _Launch(monkeypatch, healthy_once_spawned=True)

    text = launch.run(tmp_path, relaunch=True)

    assert len(launch.spawned) == 1
    assert launch.killed == []
    assert "Startup recovery launch: server left running on 127.0.0.1:9011." in text


def test_a_diagnostic_launch_stops_the_healthy_server_it_started(tmp_path: Path, monkeypatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    launch = _Launch(monkeypatch, healthy_once_spawned=True)

    text = launch.run(tmp_path, relaunch=False)

    assert launch.killed == [4101]
    assert "Startup probe: server became healthy in diagnostic launch." in text


def test_a_relaunch_leaves_a_server_that_is_still_initializing_alone(tmp_path: Path, monkeypatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    launch = _Launch(monkeypatch, healthy_once_spawned=False)

    text = launch.run(tmp_path, relaunch=True)

    assert launch.killed == []
    assert "Startup recovery launch is still initializing on 127.0.0.1:9011" in text


def test_a_diagnostic_launch_that_never_gets_healthy_is_stopped_and_reported(tmp_path: Path, monkeypatch) -> None:
    isolate_offline_checks(tmp_path, monkeypatch)
    launch = _Launch(monkeypatch, healthy_once_spawned=False)

    text = launch.run(tmp_path, relaunch=False)

    assert launch.killed == [4101]
    assert "Startup probe failed (exit=running)" in text
