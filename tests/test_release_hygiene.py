from __future__ import annotations

from pathlib import Path

import pytest
import scripts.forge.gates.release_hygiene as mod


@pytest.fixture(autouse=True)
def isolated_release_metadata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep unit tests focused on mocked gate outcomes, not live release files."""
    (tmp_path / "thomas").mkdir()
    (tmp_path / "pyproject.toml").write_text('[project]\nversion = "9.9.9"\n', encoding="utf-8")
    (tmp_path / "thomas" / "__init__.py").write_text('__version__ = "9.9.9"\n', encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [9.9.9] - 2099-01-01\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)


def _gate_payload(*, ok: bool, errors: list[str] | None = None, warnings: list[str] | None = None) -> dict:
    return {
        "ok": bool(ok),
        "db_path": "runs.sqlite3",
        "errors": list(errors or []),
        "warnings": list(warnings or []),
        "summary": {
            "events": 25,
            "completion_rate": 0.95,
            "recovery_success_rate": 0.85,
            "median_time_to_ready_seconds": 120.0,
        },
        "thresholds": {},
    }


def _security_audit_payload(
    *,
    ok: bool,
    failing_checks: list[str] | None = None,
    warning_count: int = 0,
) -> dict:
    return {
        "ok": bool(ok),
        "checks": {},
        "summary": {
            "check_count": 5,
            "failing_checks": list(failing_checks or []),
            "error_count": 0,
            "warning_count": int(warning_count),
        },
    }


def test_release_hygiene_fails_when_onboarding_gate_errors(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        mod,
        "_evaluate_onboarding_gate",
        lambda **_: _gate_payload(
            ok=False,
            errors=["onboarding completion rate below target: completion_rate=0.4200, target>=0.9000"],
            warnings=[],
        ),
    )
    monkeypatch.setattr(mod, "run_security_audit", lambda *_args, **_kwargs: _security_audit_payload(ok=True))

    # Onboarding completion is usage telemetry, not code correctness, so an error is
    # advisory by default (a fresh worktree has 0% completion); --strict-warnings
    # promotes it to a hard release failure.
    rc = mod.run(["--enforce-onboarding-gate", "--strict-warnings"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "release hygiene: FAIL" in out
    assert "onboarding outcomes gate" in out


def test_release_hygiene_passes_when_onboarding_gate_warns_only(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        mod,
        "_evaluate_onboarding_gate",
        lambda **_: _gate_payload(
            ok=True,
            errors=[],
            warnings=["insufficient onboarding telemetry sample for KPI threshold checks: events=3, required>=20"],
        ),
    )
    monkeypatch.setattr(mod, "run_security_audit", lambda *_args, **_kwargs: _security_audit_payload(ok=True))

    rc = mod.run([])
    out = capsys.readouterr().out

    assert rc == 0
    assert "release hygiene: PASS" in out
    assert "onboarding gate: OK" in out
    assert "onboarding outcomes gate warning" in out


def test_release_hygiene_can_disable_onboarding_gate(monkeypatch, capsys) -> None:
    called = {"value": False}

    def _sentinel(**_):
        called["value"] = True
        return _gate_payload(ok=True)

    monkeypatch.setattr(mod, "_evaluate_onboarding_gate", _sentinel)
    monkeypatch.setattr(mod, "run_security_audit", lambda *_args, **_kwargs: _security_audit_payload(ok=True))

    rc = mod.run(["--no-enforce-onboarding-gate"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "release hygiene: PASS" in out
    assert called["value"] is False


def test_release_hygiene_fails_when_security_audit_fails(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_evaluate_onboarding_gate", lambda **_: _gate_payload(ok=True))
    monkeypatch.setattr(
        mod,
        "run_security_audit",
        lambda *_args, **_kwargs: _security_audit_payload(ok=False, failing_checks=["mutating_route_policy"]),
    )

    rc = mod.run([])
    out = capsys.readouterr().out

    assert rc == 1
    assert "release hygiene: FAIL" in out
    assert "security audit failed (high severity): mutating_route_policy" in out


def test_release_hygiene_passes_when_security_audit_warns_only(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_evaluate_onboarding_gate", lambda **_: _gate_payload(ok=True))
    monkeypatch.setattr(
        mod,
        "run_security_audit",
        lambda *_args, **_kwargs: _security_audit_payload(ok=True, warning_count=2),
    )

    rc = mod.run([])
    out = capsys.readouterr().out

    assert rc == 0
    assert "release hygiene: PASS" in out
    assert "security audit: OK" in out
    assert "security audit warnings present: 2" in out
    assert out.count("security audit warnings present: 2") == 1


def test_release_hygiene_can_disable_security_audit(monkeypatch, capsys) -> None:
    called = {"value": False}

    def _sentinel(*_args, **_kwargs):
        called["value"] = True
        return _security_audit_payload(ok=True)

    monkeypatch.setattr(mod, "_evaluate_onboarding_gate", lambda **_: _gate_payload(ok=True))
    monkeypatch.setattr(mod, "run_security_audit", _sentinel)

    rc = mod.run(["--no-enforce-security-audit"])
    out = capsys.readouterr().out

    assert rc == 0
    assert "release hygiene: PASS" in out
    assert "security audit:" not in out
    assert called["value"] is False


def test_release_hygiene_strict_warnings_fails_on_onboarding_warning(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        mod,
        "_evaluate_onboarding_gate",
        lambda **_: _gate_payload(ok=True, errors=[], warnings=["low sample"]),
    )
    monkeypatch.setattr(mod, "run_security_audit", lambda *_args, **_kwargs: _security_audit_payload(ok=True))

    rc = mod.run(["--strict-warnings"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "release hygiene: FAIL" in out
    assert "WARN: onboarding outcomes gate warning: low sample" in out


def test_release_hygiene_strict_warnings_fails_on_security_warning(monkeypatch, capsys) -> None:
    monkeypatch.setattr(mod, "_evaluate_onboarding_gate", lambda **_: _gate_payload(ok=True))
    monkeypatch.setattr(
        mod,
        "run_security_audit",
        lambda *_args, **_kwargs: _security_audit_payload(ok=True, warning_count=2),
    )

    rc = mod.run(["--strict-warnings"])
    out = capsys.readouterr().out

    assert rc == 1
    assert "release hygiene: FAIL" in out
    assert "WARN: security audit warnings present: 2" in out


# --- release bundle boundary ---------------------------------------------------
#
# scripts/package_release.py selects by ALLOW-LIST. It used to be a deny-list,
# which shipped anything new by default: scripts/crew (41 files of workboard and
# claim tooling), all 59 gates, AGENTS.md, PROJECT_MANAGEMENT_RULES.md and
# plans/ all reached user bundles without anyone deciding they should. A user's
# Thomas has no workboard, files no claims, and has no peer agents.
#
# These two tests pin both directions. Dropping either one lets the boundary rot
# back: the first to shipping internal state, the second to a bundle that is
# clean and cannot start.


def _bundle_paths() -> set[str]:
    import importlib.util
    import subprocess

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("_pkg_release", root / "scripts" / "package_release.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    tracked = subprocess.run(
        ["git", "ls-files"], cwd=root, capture_output=True, text=True, check=False
    ).stdout.splitlines()
    return {p.strip() for p in tracked if p.strip() and module._is_excluded(p.strip()) is None}


def test_release_bundle_excludes_build_system_and_process() -> None:
    """No maintainer-only tooling may reach a user bundle."""
    shipped = _bundle_paths()
    assert shipped, "bundle selection returned nothing -- packaging is broken"

    forbidden_prefixes = (
        "scripts/crew/",
        "scripts/forge/gates/",
        "plans/",
        "tests/",
        ".github/",
        "prompt_pack/",
        ".codex/",
        "docs/ai/",
        "evolve_corpus/",
        "code_intake/",
    )
    for prefix in forbidden_prefixes:
        leaked = sorted(p for p in shipped if p.startswith(prefix))
        assert not leaked, f"{prefix} must not ship: {leaked[:5]}"

    forbidden_files = (
        "AGENTS.md",
        "CLAUDE.md",
        "CONTRIBUTING_AI.md",
        "PROJECT_MANAGEMENT_RULES.md",
        "GUARDRAILS.md",
        "agent_safety.toml",
    )
    for name in forbidden_files:
        assert name not in shipped, f"{name} must not ship"


def test_release_bundle_still_contains_a_cold_install() -> None:
    """Clean is not enough -- a bundle that cannot start is a worse regression.

    The root .cmd launchers immediately delegate into scripts/*.ps1, which the
    allow-list excludes wholesale. Those specific launcher files are named back in
    individually; if that ever gets dropped the bundle stays 'clean' and nothing
    runs.
    """
    shipped = _bundle_paths()

    required = (
        "README.md",
        "LICENSE",
        "SECURITY.md",
        "pyproject.toml",
        "requirements-lock.txt",
        "thomas.toml",
        # spend caps read by evolve_supervisor/spend_governor.py, which ships
        "evolve_governor.toml",
        # runtime guidance sources read by thomas/agent/guidance.py
        "SOUL.md",
        "IDENTITY.md",
        # entry points and the launchers they call
        "install.cmd",
        "run-ui.cmd",
        "scripts/run-ui.ps1",
        "scripts/setup.ps1",
        "scripts/repair.ps1",
        "scripts/bootdoctor.ps1",
        "scripts/run-repl.ps1",
        "scripts/create_shortcut.py",
        "installer/ThomasSetup.iss",
        # the product itself
        "thomas/server/web/chat.html",
    )
    missing = [p for p in required if p not in shipped]
    assert not missing, f"cold install would break, missing: {missing}"

    assert any(p.startswith("thomas/") for p in shipped), "the product package must ship"
