from __future__ import annotations

from pathlib import Path

import pytest

from thomas.bootdoctor.__main__ import (
    BootDoctorPathPolicy,
    RestrictedTool,
    _build_parser,
    _extract_patch_targets,
    _extract_repo_paths_from_text,
)
from thomas.core.boot_doctor import read_boot_recovery_notice, write_boot_recovery_notice
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
    patch = "--- a/scripts/run-ui.ps1\n" "+++ b/scripts/run-ui.ps1\n" "@@ -1,1 +1,1 @@\n" "-old\n" "+new\n"
    assert _extract_patch_targets(patch) == ["scripts/run-ui.ps1"]


def test_extract_repo_paths_from_traceback_text(tmp_path: Path) -> None:
    text = (
        "Traceback (most recent call last):\n"
        f"  File \"{tmp_path / 'thomas' / 'agent' / 'loop.py'}\", line 324, in <module>\n"
        f"  File \"{tmp_path / 'thomas' / 'server' / 'app.py'}\", line 52, in <module>\n"
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