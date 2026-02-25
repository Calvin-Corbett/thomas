from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import scripts.module_audit_status as mod
from thomas.observability.module_audit import MAJOR_MODULES


def _write_registry(
    path: Path,
    *,
    audited_at: str,
    status: str = "pass",
    with_issues: bool = False,
) -> None:
    latest = {}
    for idx, module in enumerate(MAJOR_MODULES):
        issues = [f"{module}-issue"] if with_issues and idx % 2 == 0 else []
        latest[module] = {
            "audited_at": audited_at,
            "auditor": "qa",
            "status": status,
            "signature": "abc123",
            "issues": issues,
        }
    payload = {"schema_version": 1, "updated_at": audited_at, "latest_by_module": latest, "history": []}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_module_audit_status_reports_stale_without_strict(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "module_audit_log.json"
    old = (datetime.now(timezone.utc) - timedelta(days=2)).replace(microsecond=0).isoformat()
    _write_registry(registry, audited_at=old)

    rc = mod.run(["--registry", str(registry), "--max-age-hours", "24", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is False
    assert payload["stale_count"] == len(MAJOR_MODULES)


def test_module_audit_status_strict_fails_for_stale(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "module_audit_log.json"
    old = (datetime.now(timezone.utc) - timedelta(days=2)).replace(microsecond=0).isoformat()
    _write_registry(registry, audited_at=old)

    rc = mod.run(["--registry", str(registry), "--max-age-hours", "24", "--strict", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["strict"] is True


def test_module_audit_status_passes_with_fresh_entries_and_issue_count(
    tmp_path: Path, capsys
) -> None:
    registry = tmp_path / "module_audit_log.json"
    fresh = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    _write_registry(registry, audited_at=fresh, with_issues=True)

    rc = mod.run(["--registry", str(registry), "--max-age-hours", "24", "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["stale_count"] == 0
    assert payload["missing_count"] == 0
    assert payload["total_issue_count"] > 0
