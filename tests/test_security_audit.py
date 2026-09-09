from __future__ import annotations

from pathlib import Path

from thomas.marketplace.security.security_audit import run_security_audit

ROOT = Path(__file__).resolve().parents[1]


def test_security_audit_returns_aggregated_checks() -> None:
    payload = run_security_audit(ROOT, include_incident_drill=False)
    assert "summary" in payload
    assert "checks" in payload
    summary = payload["summary"]
    assert int(summary["check_count"]) >= 5
    checks = payload["checks"]
    assert "dependency_policy" in checks
    assert "threat_model_cadence" in checks
    assert "mutating_route_policy" in checks
    assert "release_contracts" in checks
    assert "extension_certification" in checks
