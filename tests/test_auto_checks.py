from __future__ import annotations

import scripts.auto_checks as mod


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

    rc = mod.run(["--skip-tests"])
    assert rc == 1
    assert "Surface parity gate" in seen
    assert "Workboard claims gate" not in seen


def test_run_continues_after_surface_parity_failure_with_continue(monkeypatch) -> None:
    seen: list[str] = []

    def _fake_run_step(label: str, _cmd: tuple[str, ...]) -> int:
        seen.append(label)
        if label == "Surface parity gate":
            return 1
        return 0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_warn_missing_optional_modules", lambda: None)

    rc = mod.run(["--skip-tests", "--continue-on-fail"])
    assert rc == 1
    assert "Surface parity gate" in seen
    assert "Workboard claims gate" in seen


def test_run_defaults_repo_hygiene_to_no_require_clean_worktree_locally(monkeypatch) -> None:
    seen: list[tuple[str, tuple[str, ...]]] = []

    def _fake_run_step(label: str, cmd: tuple[str, ...]) -> int:
        seen.append((label, tuple(cmd)))
        return 0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_warn_missing_optional_modules", lambda: None)
    monkeypatch.delenv("CI", raising=False)

    rc = mod.run(["--skip-tests"])
    assert rc == 0
    repo_cmd = dict(seen)["Repo hygiene gate"]
    assert "--no-require-clean-worktree" in repo_cmd


def test_run_defaults_repo_hygiene_to_strict_in_ci(monkeypatch) -> None:
    seen: list[tuple[str, tuple[str, ...]]] = []

    def _fake_run_step(label: str, cmd: tuple[str, ...]) -> int:
        seen.append((label, tuple(cmd)))
        return 0

    monkeypatch.setattr(mod, "_run_step", _fake_run_step)
    monkeypatch.setattr(mod, "_warn_missing_optional_modules", lambda: None)
    monkeypatch.setenv("CI", "true")

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

    rc = mod.run(["--skip-tests", "--no-require-clean-worktree"])
    assert rc == 0
    repo_cmd = dict(seen)["Repo hygiene gate"]
    assert "--no-require-clean-worktree" in repo_cmd
