from __future__ import annotations

from datetime import date
from pathlib import Path

from thomas.system.release_contracts import build_release_contract_report, evaluate_release_contract_registry

ROOT = Path(__file__).resolve().parents[1]


def test_default_release_contract_registry_is_valid() -> None:
    report = build_release_contract_report(ROOT / "docs" / "release" / "contract_registry.json")
    assert report["ok"] is True
    assert int(report["summary"]["contract_count"]) >= 1
    assert int(report["summary"]["error_count"]) == 0


def test_deprecation_notice_window_violation_is_reported(tmp_path: Path) -> None:
    registry = {
        "policy": {"min_deprecation_notice_days": 30},
        "contracts": [
            {
                "id": "api.test",
                "surface": "http_api",
                "version": "1.0.0",
                "status": "deprecated",
                "deprecated_on": "2026-02-01",
                "sunset_on": "2026-02-10",
            }
        ],
        "migration_guarantees": [{"id": "x", "guarantee": "y", "verified_by": "z"}],
    }
    report = evaluate_release_contract_registry(registry, today=date(2026, 2, 22))
    assert report["ok"] is False
    codes = {row["code"] for row in report["errors"]}
    assert "contracts.notice_window_too_short" in codes


def test_invalid_registry_json_returns_failure(tmp_path: Path) -> None:
    path = tmp_path / "contracts.json"
    path.write_text("{invalid", encoding="utf-8")
    report = build_release_contract_report(path)
    assert report["ok"] is False
    assert int(report["summary"]["error_count"]) >= 1
