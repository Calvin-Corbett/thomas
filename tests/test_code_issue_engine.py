import subprocess

from thomas.core.code_issue_engine import CodeIssueEngine, CommandCheck


def _heartbeat_pass_report() -> dict:
    return {
        "ok": True,
        "results": [
            {
                "name": "python_compile",
                "status": "pass",
                "message": "ok",
                "auto_fixable": False,
            }
        ],
        "summary": {"total": 1, "pass": 1, "warn": 0, "fail": 0},
    }


def test_code_issue_engine_runs_heartbeat_fix_until_clean() -> None:
    engine = CodeIssueEngine(
        command_checks=[],
        max_passes_per_cycle=3,
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
    )

    calls: list[bool] = []

    def fake_heartbeat_report(*, fix: bool) -> dict:
        calls.append(bool(fix))
        if fix:
            return _heartbeat_pass_report()
        return {
            "ok": False,
            "results": [
                {
                    "name": "python_compile",
                    "status": "fail",
                    "message": "syntax error",
                    "auto_fixable": True,
                }
            ],
            "summary": {"total": 1, "pass": 0, "warn": 0, "fail": 1},
        }

    engine._heartbeat_report = fake_heartbeat_report  # type: ignore[method-assign]
    report = engine.run_cycle_once(reason="test", force=True)

    assert report.get("ok") is True
    assert report.get("clean") is True
    assert int(report.get("unresolved_count") or 0) == 0
    assert int(report.get("fixes_attempted") or 0) >= 1
    assert calls == [False, True]


def test_code_issue_engine_command_fix_path() -> None:
    engine = CodeIssueEngine(
        command_checks=[
            CommandCheck(
                name="lint",
                check_command="check-lint",
                fix_command="fix-lint",
                timeout_seconds=5.0,
            )
        ],
        max_passes_per_cycle=2,
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
    )
    engine._heartbeat_report = lambda *, fix: _heartbeat_pass_report()  # type: ignore[method-assign]

    check_count = {"value": 0}

    def fake_run_shell_command(command: str, *, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        assert timeout_seconds > 0
        if command == "fix-lint":
            return subprocess.CompletedProcess(command, 0, stdout="fixed", stderr="")
        if command == "check-lint":
            check_count["value"] += 1
            if check_count["value"] == 1:
                return subprocess.CompletedProcess(command, 1, stdout="", stderr="lint failed")
            return subprocess.CompletedProcess(command, 0, stdout="lint ok", stderr="")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    engine._run_shell_command = fake_run_shell_command  # type: ignore[method-assign]
    report = engine.run_cycle_once(reason="test-command-fix", force=True)

    assert report.get("clean") is True
    assert int(report.get("unresolved_count") or 0) == 0
    assert int(report.get("fixes_attempted") or 0) == 1
    first_pass = list(report.get("passes") or [])[0]
    checks = list(first_pass.get("command_checks") or [])
    assert checks and checks[0].get("ok") is True


def test_code_issue_engine_stops_when_unfixable() -> None:
    engine = CodeIssueEngine(
        command_checks=[],
        max_passes_per_cycle=4,
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
    )

    engine._heartbeat_report = lambda *, fix: {  # type: ignore[method-assign]
        "ok": False,
        "results": [
            {
                "name": "architecture_fitness",
                "status": "fail",
                "message": "failing test",
                "auto_fixable": False,
            }
        ],
        "summary": {"total": 1, "pass": 0, "warn": 0, "fail": 1},
    }

    report = engine.run_cycle_once(reason="test-unfixable", force=True)

    assert report.get("clean") is False
    assert int(report.get("unresolved_count") or 0) == 1
    assert int(report.get("fixes_attempted") or 0) == 0
    assert len(list(report.get("passes") or [])) == 1


def test_code_issue_engine_manual_cycle_returns_busy_when_active() -> None:
    engine = CodeIssueEngine(
        command_checks=[],
        idle_threshold_s=0.0,
        poll_interval_s=1.0,
        cycle_interval_s=1.0,
    )
    engine._active_cycle = True
    report = engine.run_cycle_once(reason="manual", force=True)
    assert report.get("ok") is False
    assert report.get("reason") == "busy"
