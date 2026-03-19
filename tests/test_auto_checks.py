from __future__ import annotations

import scripts.auto_checks as mod


def _enable_breakglass(monkeypatch) -> None:
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.setenv("THOMAS_SKIP_TICKET", "OPS-12345")
    monkeypatch.setenv("THOMAS_SKIP_REASON", "emergency bypass for focused test harness")
    monkeypatch.setenv("AGENT_ID", "Codex Test")


def test_gate_steps_include_surface_parity() -> None:
    assert any(
        label == "Surface parity gate" and tuple(cmd) == (mod.PY, "scripts/check_surface_parity.py")
        for label, cmd in mod.GATE_STEPS
    )


def test_run_includes_surface_parity_gate_when_not_quick(monkeypatch) -> None:
    seen: list[tuple[str, tuple[str, ...]]] = []

    def _fake_run_step(label: str, cmd: tuple[str, ...]) -> int:
        seen.append((label, tuple(cmd)))
        return 0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_warn_missing_optional_modules", lambda: None)
    _enable_breakglass(monkeypatch)

    rc = mod.run(["--skip-tests"])
    assert rc == 0
    assert any(label == "Surface parity gate" for label, _ in seen)


def test_run_quick_skips_gates(monkeypatch) -> None:
    seen: list[str] = []

    def _fake_run_step(label: str, _cmd: tuple[str, ...]) -> int:
        seen.append(label)
        return 0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_warn_missing_optional_modules", lambda: None)

    rc = mod.run(["--quick"])
    assert rc == 0
    assert "Surface parity gate" not in seen
    assert seen == [label for label, _ in mod.CORE_STEPS]


def test_run_stops_on_surface_parity_failure_without_continue(monkeypatch) -> None:
    seen: list[str] = []

    def _fake_run_step(label: str, _cmd: tuple[str, ...]) -> int:
        seen.append(label)
        if label == "Surface parity gate":
            return 1
        return 0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_warn_missing_optional_modules", lambda: None)
    _enable_breakglass(monkeypatch)

    rc = mod.run(["--skip-tests"])
    assert rc == 1
    assert "Surface parity gate" in seen
    assert "Workboard claims gate" not in seen


def test_run_records_problem_ledger_on_failure(monkeypatch) -> None:
    seen: list[str] = []
    recorded: list[tuple[str, int]] = []

    def _fake_run_step(label: str, _cmd: tuple[str, ...]) -> int:
        seen.append(label)
        if label == "Surface parity gate":
            return 1
        return 0

    def _fake_record_failure(
        *,
        label: str,
        cmd: tuple[str, ...],
        exit_code: int,
        task_id: str,
        agent: str,
    ) -> tuple[bool, str]:
        _ = (cmd, task_id, agent)
        recorded.append((label, exit_code))
        return True, "recorded"

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_record_problem_failure", _fake_record_failure)
    monkeypatch.setattr(mod, "_warn_missing_optional_modules", lambda: None)
    _enable_breakglass(monkeypatch)

    rc = mod.run(["--skip-tests"])
    assert rc == 1
    assert "Surface parity gate" in seen
    assert recorded == [("Surface parity gate", 1)]


def test_run_continues_after_surface_parity_failure_with_continue(monkeypatch) -> None:
    seen: list[str] = []

    def _fake_run_step(label: str, _cmd: tuple[str, ...]) -> int:
        seen.append(label)
        if label == "Surface parity gate":
            return 1
        return 0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_warn_missing_optional_modules", lambda: None)
    _enable_breakglass(monkeypatch)

    rc = mod.run(["--skip-tests", "--continue-on-fail"])
    assert rc == 1
    assert "Surface parity gate" in seen
    assert "Workboard claims gate" in seen


def test_run_defaults_repo_hygiene_to_strict_locally(monkeypatch) -> None:
    seen: list[tuple[str, tuple[str, ...]]] = []

    def _fake_run_step(label: str, cmd: tuple[str, ...]) -> int:
        seen.append((label, tuple(cmd)))
        return 0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_warn_missing_optional_modules", lambda: None)
    monkeypatch.delenv("CI", raising=False)
    _enable_breakglass(monkeypatch)

    rc = mod.run(["--skip-tests"])
    assert rc == 0
    repo_cmd = dict(seen)["Repo hygiene gate"]
    assert "--no-require-clean-worktree" not in repo_cmd


def test_run_defaults_repo_hygiene_to_strict_in_ci(monkeypatch) -> None:
    seen: list[tuple[str, tuple[str, ...]]] = []

    def _fake_run_step(label: str, cmd: tuple[str, ...]) -> int:
        seen.append((label, tuple(cmd)))
        return 0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_warn_missing_optional_modules", lambda: None)
    monkeypatch.setenv("CI", "true")
    _enable_breakglass(monkeypatch)

    rc = mod.run(["--skip-tests"])
    assert rc == 0
    repo_cmd = dict(seen)["Repo hygiene gate"]
    assert "--no-require-clean-worktree" not in repo_cmd


def test_run_repo_hygiene_cli_override_to_no_require_clean_worktree(monkeypatch) -> None:
    seen: list[tuple[str, tuple[str, ...]]] = []

    def _fake_run_step(label: str, cmd: tuple[str, ...]) -> int:
        seen.append((label, tuple(cmd)))
        return 0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_warn_missing_optional_modules", lambda: None)
    monkeypatch.setenv("CI", "true")
    _enable_breakglass(monkeypatch)

    rc = mod.run(["--skip-tests", "--no-require-clean-worktree"])
    assert rc == 0
    repo_cmd = dict(seen)["Repo hygiene gate"]
    assert "--no-require-clean-worktree" in repo_cmd


def test_run_rejects_skip_overrides_without_breakglass(monkeypatch, capsys) -> None:
    called = {"count": 0}

    def _fake_run_step(_label: str, _cmd: tuple[str, ...]) -> int:
        called["count"] += 1
        return 0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_warn_missing_optional_modules", lambda: None)
    monkeypatch.delenv("THOMAS_SKIP_BREAKGLASS", raising=False)
    monkeypatch.delenv("THOMAS_SKIP_TICKET", raising=False)
    monkeypatch.delenv("THOMAS_SKIP_REASON", raising=False)
    monkeypatch.delenv("AGENT_ID", raising=False)

    rc = mod.run(["--skip-tests"])
    out = capsys.readouterr().out
    assert rc == 1
    assert "--skip-gates/--skip-tests are breakglass-only" in out
    assert called["count"] == 0


def test_run_autofills_breakglass_metadata_for_skip_flags(monkeypatch) -> None:
    seen: list[str] = []

    def _fake_run_step(label: str, _cmd: tuple[str, ...]) -> int:
        seen.append(label)
        return 0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_warn_missing_optional_modules", lambda: None)
    monkeypatch.setenv("THOMAS_SKIP_BREAKGLASS", "1")
    monkeypatch.delenv("THOMAS_SKIP_TICKET", raising=False)
    monkeypatch.delenv("THOMAS_SKIP_REASON", raising=False)
    monkeypatch.delenv("AGENT_ID", raising=False)

    rc = mod.run(["--skip-tests"])
    assert rc == 0
    assert "Python compile check" in seen
    assert len(str(mod.os.getenv("THOMAS_SKIP_TICKET", ""))) >= 6
    assert len(str(mod.os.getenv("THOMAS_SKIP_REASON", ""))) >= 12
    assert str(mod.os.getenv("AGENT_ID", "")).strip()
