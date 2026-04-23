from __future__ import annotations

import json
from pathlib import Path

import scripts.check_onboarding_outcomes_gate as mod


def _patch_gate(monkeypatch, *, warnings: list[str], errors: list[str], ok: bool = True) -> None:
    monkeypatch.setattr(mod, "resolve_runs_db_path", lambda: Path("runs.sqlite3"))
    monkeypatch.setattr(mod, "build_onboarding_outcome_report", lambda *_a, **_k: {"summary": {"events": 0}})
    monkeypatch.setattr(
        mod,
        "evaluate_onboarding_outcomes_gate",
        lambda *_a, **_k: {
            "ok": bool(ok),
            "warnings": list(warnings),
            "errors": list(errors),
            "summary": {},
        },
    )


def test_strict_mode_fails_when_warnings_present(monkeypatch, capsys) -> None:
    _patch_gate(monkeypatch, warnings=["onboarding timing data missing for completed journeys"], errors=[])
    rc = mod.main(["--json", "--strict"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["ok"] is False
    assert "strict mode enabled and warnings were present" in payload["errors"]


def test_strict_mode_can_ignore_low_sample_warning(monkeypatch, capsys) -> None:
    low_sample = "insufficient onboarding telemetry sample for KPI threshold checks: events=0, required>=20"
    _patch_gate(monkeypatch, warnings=[low_sample], errors=[])
    rc = mod.main(["--json", "--strict", "--ignore-low-sample-warning"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["ok"] is True
    assert payload["ignored_warnings"] == [low_sample]
    assert "strict mode enabled and warnings were present" not in payload["errors"]


def test_strict_mode_still_fails_with_non_low_sample_warning(monkeypatch, capsys) -> None:
    low_sample = "insufficient onboarding telemetry sample for KPI threshold checks: events=0, required>=20"
    other_warning = "onboarding timing data missing for completed journeys"
    _patch_gate(monkeypatch, warnings=[low_sample, other_warning], errors=[])
    rc = mod.main(["--json", "--strict", "--ignore-low-sample-warning"])
    payload = json.loads(capsys.readouterr().out)
    assert rc == 2
    assert payload["ok"] is False
    assert payload["ignored_warnings"] == [low_sample]
    assert "strict mode enabled and warnings were present" in payload["errors"]
