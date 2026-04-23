from __future__ import annotations

from datetime import date
from pathlib import Path

from thomas.marketplace.security import mutating_route_policy as mod


def _snapshot(*, authz: str = "require_api_access", csrf: str = "same_origin_browser_local_mode") -> dict:
    return {
        "generated_at_utc": "2026-02-22T00:00:00Z",
        "defaults": {
            "authz": "require_api_access",
            "csrf": "same_origin_browser_local_mode",
        },
        "policies": [
            {
                "method": "POST",
                "path": "/api/demo",
                "authz": authz,
                "csrf": csrf,
            }
        ],
    }


def test_manifest_audit_passes_when_runtime_uses_default_policy() -> None:
    report = mod.evaluate_mutating_route_policy_manifest(
        _snapshot(),
        {
            "defaults": {
                "authz": "require_api_access",
                "csrf": "same_origin_browser_local_mode",
            },
            "exceptions": [],
        },
        today=date(2026, 2, 22),
    )
    assert report["ok"] is True
    assert int(report["summary"]["error_count"]) == 0
    assert int(report["summary"]["warning_count"]) == 0


def test_manifest_audit_fails_for_unapproved_runtime_exception() -> None:
    report = mod.evaluate_mutating_route_policy_manifest(
        _snapshot(authz="token_override"),
        {
            "defaults": {
                "authz": "require_api_access",
                "csrf": "same_origin_browser_local_mode",
            },
            "exceptions": [],
        },
        today=date(2026, 2, 22),
    )
    assert report["ok"] is False
    codes = {str(item.get("code") or "") for item in list(report.get("errors") or [])}
    assert "mutating_route_policy.unapproved_exception" in codes


def test_manifest_audit_emits_warning_for_stale_exception_record() -> None:
    report = mod.evaluate_mutating_route_policy_manifest(
        _snapshot(),
        {
            "defaults": {
                "authz": "require_api_access",
                "csrf": "same_origin_browser_local_mode",
            },
            "exceptions": [
                {
                    "method": "POST",
                    "path": "/api/demo",
                    "authz": "require_api_access",
                    "csrf": "same_origin_browser_local_mode",
                    "reason": "legacy exemption retained for visibility",
                    "owner": "security-team",
                    "reviewed_on": "2026-02-20",
                    "expires_on": "2026-12-31",
                }
            ],
        },
        today=date(2026, 2, 22),
    )
    assert report["ok"] is True
    assert int(report["summary"]["error_count"]) == 0
    assert int(report["summary"]["warning_count"]) == 1
    warn_codes = {str(item.get("code") or "") for item in list(report.get("warnings") or [])}
    assert "mutating_route_policy.stale_manifest_exception" in warn_codes


def test_policy_exception_report_surfaces_loader_failures(monkeypatch) -> None:
    monkeypatch.setattr(mod, "_load_manifest", lambda _path: ({}, []))
    monkeypatch.setattr(
        mod,
        "_load_policy_snapshot",
        lambda _root: (
            {},
            [
                {
                    "code": "mutating_route_policy.snapshot_build_failed",
                    "message": "boom",
                    "remediation": "fix it",
                }
            ],
        ),
    )

    report = mod.evaluate_mutating_route_policy_exceptions(
        Path("."),
        manifest_path=Path("docs/security/mutating_route_policy_exceptions.json"),
        today=date(2026, 2, 22),
    )
    assert report["ok"] is False
    assert int(report["summary"]["error_count"]) == 1
    error_codes = {str(item.get("code") or "") for item in list(report.get("errors") or [])}
    assert "mutating_route_policy.snapshot_build_failed" in error_codes
