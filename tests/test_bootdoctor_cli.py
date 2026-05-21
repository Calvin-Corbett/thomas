from __future__ import annotations

import sys
from pathlib import Path

import pytest

import thomas.core.boot_doctor as boot_doctor
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


def test_run_boot_doctor_leaves_repaired_retry_running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _seed_boot_layout(tmp_path)
    (tmp_path / "thomas" / "groupchat").mkdir(parents=True, exist_ok=True)
    (tmp_path / "thomas" / "server" / "__main__.py").write_text(
        "def main():\n"
        "    try:\n"
        "        from thomas.server.app import serve\n\n"
        "        serve(config, host=str(args.host), port=int(args.port))\n"
        "    except Exception:\n"
        "        raise\n",
        encoding="utf-8",
    )
    (tmp_path / "thomas" / "server" / "tool_extensions.py").write_text(
        "def _try_import(module_path: str, func_name: str):\n"
        "    try:\n"
        "        mod = __import__(module_path, fromlist=[func_name])\n"
        "        return getattr(mod, func_name)\n"
        "    except (ImportError, ModuleNotFoundError, AttributeError):\n"
        "        return None\n",
        encoding="utf-8",
    )
    (tmp_path / "thomas" / "groupchat" / "__init__.py").write_text(
        '"""Backward-compatible re-export for groupchat helpers."""\n\nfrom thomas.marketplace.groupchat import *\n',
        encoding="utf-8",
    )

    state = {"t": 0.0}
    kill_calls: list[int] = []
    spawned: list[object] = []
    spawn_modes: list[bool] = []

    class _DummyProc:
        def __init__(self, log_handle, exit_code: int | None, log_text: str = "") -> None:
            self.pid = 4100 + len(spawned)
            self._exit_code = exit_code
            if log_text:
                log_handle.write(log_text)
                log_handle.flush()
            spawned.append(self)

        def poll(self):
            return self._exit_code

    def _fake_spawn(*, py_exe, root, host, port, stdout, detached=False):
        spawn_modes.append(bool(detached))
        if len(spawned) == 0:
            return _DummyProc(
                stdout, 1, "RuntimeError: Unable to locate monolith_source_loader.py in repository root\n"
            )
        return _DummyProc(stdout, None, "14:08:17 [thomas.server] INFO: Thomas starting\n")

    monkeypatch.setattr(boot_doctor, "_resolve_python", lambda root: Path(sys.executable).resolve())
    monkeypatch.setattr(boot_doctor, "_run_cmd", lambda *args, **kwargs: (True, "exit=0"))
    monkeypatch.setattr(boot_doctor, "_thomas_http_healthy", lambda port: False)
    monkeypatch.setattr(boot_doctor, "_is_port_listening", lambda host, port, timeout=0.4: False)
    monkeypatch.setattr(boot_doctor, "_kill_pid", lambda pid: kill_calls.append(pid) or True)
    monkeypatch.setattr(
        boot_doctor, "_bootdoctor_sleep", lambda seconds: state.__setitem__("t", state["t"] + float(seconds) + 100.0)
    )
    monkeypatch.setattr(boot_doctor.time, "monotonic", lambda: state["t"])
    monkeypatch.setattr(boot_doctor, "_spawn_thomas_server", _fake_spawn)

    config = AppConfig(memory=MemoryConfig(root=str(tmp_path)))
    report_path = run_boot_doctor(
        config=config,
        root=tmp_path,
        port=9011,
        reason="simulated startup crash",
        auto_repair=True,
        allow_ai=False,
        relaunch=True,
    )

    report_text = Path(report_path).read_text(encoding="utf-8")
    assert len(spawned) == 2
    assert spawn_modes == [False, True]
    assert kill_calls == []
    assert "Known startup repair: patched thomas.server.__main__ to use app_lifecycle.serve." in report_text
    assert "Known startup repair: widened optional tool import fallback to skip broken modules." in report_text
    assert "Known startup repair: replaced crashing thomas.groupchat re-export with a safe shim." in report_text
    assert (
        "Startup recovery launch after known repair is still initializing on 127.0.0.1:9011; leaving the repaired server running for continued startup."
        in report_text
    )
    assert "app_lifecycle import serve" in (tmp_path / "thomas" / "server" / "__main__.py").read_text(encoding="utf-8")
    assert "except Exception as exc:" in (tmp_path / "thomas" / "server" / "tool_extensions.py").read_text(
        encoding="utf-8"
    )
    assert "Compatibility shim for optional groupchat surface" in (
        tmp_path / "thomas" / "groupchat" / "__init__.py"
    ).read_text(encoding="utf-8")
