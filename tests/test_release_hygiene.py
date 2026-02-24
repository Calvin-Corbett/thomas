from __future__ import annotations

import scripts.check_release_hygiene as mod


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

    rc = mod.run([])
    out = capsys.readouterr().out

    assert rc == 1
    assert "release hygiene: FAIL" in out
    assert "onboarding outcomes gate failed" in out


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
