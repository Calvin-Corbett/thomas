from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _read_all_runtime_js() -> str:
    """Read and concatenate all split runtime JS files in order."""
    runtime_dir = ROOT / "thomas" / "server" / "web" / "js" / "runtime"
    if not runtime_dir.exists():
        return ""
    parts = sorted(runtime_dir.glob("*.js"))
    return "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in parts)


def test_run_ui_wires_visible_bootdoctor_rescue_and_watchdog() -> None:
    text = _read("scripts/run-ui.ps1")
    assert "function Get-StartupFailureContext" in text
    assert "function Start-ThomasStartupRecoveryWatch" in text
    assert "function Stop-ThomasStartupRecoveryWatch" in text
    assert "function Open-BootDoctorRescue" in text
    assert '"-LaunchMode", $(if ($NoTray) { "direct" } else { "tray" })' in text
    assert "-StdErrTail $bootContext.StdErrTail -StartupLogPaths $bootContext.LogPaths" in text
    assert (
        'Open-BootDoctorRescue -Reason ("Tray agent exited with code {0}" -f $exitCode) -DiagPort $Port -LaunchMode "tray" -StdErrTail $bootContext.StdErrTail -StartupLogPaths $bootContext.LogPaths'
        in text
    )
    assert "Detached server failed to become healthy on port {0} (pid {1})." in text
    assert (
        'Open-BootDoctorRescue -Reason $reason -DiagPort $Port -LaunchMode "direct" -StdErrTail $bootContext.StdErrTail -StartupLogPaths $bootContext.LogPaths'
        in text
    )
    assert "function Start-DetachedThomasServer" in text


def test_startup_recovery_watch_runs_bootdoctor_rescue_with_context() -> None:
    text = _read("scripts/startup_recovery_watch.ps1")
    assert "startup watchdog" in text.lower()
    assert "rescue" in text
    assert "--startup-context" in text
    assert "attempted_launch_mode" in text
    assert "startup_log_paths" in text
    assert "stderr_tail" in text
    assert "bootdoctor.ps1" in text


def test_bootdoctor_cli_supports_rescue_startup_context_and_relaunch() -> None:
    cli_text = _read("thomas/bootdoctor/__main__.py")
    direct_text = _read("scripts/run_boot_doctor_direct.py")
    assert 'choices=("chat", "report", "rescue")' in cli_text
    assert "--startup-context" in cli_text
    assert "--max-attempts" in cli_text
    assert "_run_rescue" in cli_text
    assert "--relaunch" in direct_text
    assert "relaunch=bool(args.relaunch)" in direct_text


def test_bootdoctor_core_persists_status_and_recovery_notice() -> None:
    text = _read("thomas/core/boot_doctor.py")
    assert "def write_boot_doctor_status(" in text
    assert "def write_boot_recovery_notice(" in text
    assert "def read_boot_recovery_notice(" in text


def test_server_and_web_surface_bootdoctor_recovery_notice() -> None:
    server_text = _read("thomas/server/app_part02.py")
    web_text = _read_all_runtime_js()
    assert "/api/bootdoctor/recovery_notice" in server_text
    assert "fetchBootDoctorRecoveryNotice" in web_text
    assert "appendAssistantChatHistoryMessage(message, noticeId)" in web_text
