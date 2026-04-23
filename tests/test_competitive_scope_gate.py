from __future__ import annotations

import json
from pathlib import Path

import scripts.check_competitive_scope_gate as gate


def _valid_scope_text() -> str:
    return """# Project Scope: Thomas

## Consumer Mission (Permanent)
consumer value first. Outperforming OpenClaw is a quality instrument, not the sole product purpose.

## Competitive Program (Release-Bound)
Thomas must beat the currently released OpenClaw baseline.

## OpenClaw Baseline Lock
- Pinned baseline artifact: demo/baselines/openclaw.current.json

## Capability Contract (Must Exist)
- capability contract text

## Hard Win Gates (Must All Pass)
- Task Success Rate: +10
- p95 Time-to-First-Useful-Output: 20%
- Crash-Free Run Rate: 99.5%
- Autonomous Recovery Success: 95% within <=30s
- Unsafe Action Block Rate: 99%
- False Block Rate: <=5%
- Cross-Provider Pass Rate: at least `3`
- Cost-per-Success: 5%

## Evidence Policy
- benchmark evidence required
"""


def _write_scope(path: Path) -> None:
    path.write_text(_valid_scope_text(), encoding="utf-8")


def _write_baseline(path: Path, *, commit: str = "d17a1f3") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "system": "openclaw",
        "repo_url": "https://github.com/openclaw/openclaw",
        "baseline_type": "released_snapshot",
        "commit": commit,
        "captured_at_utc": "2026-02-19T00:00:00Z",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_competitive_scope_gate_passes_with_consumer_primary_scope(tmp_path, monkeypatch):
    scope_doc = tmp_path / "PROJECT_SCOPE.md"
    baseline_doc = tmp_path / "openclaw.current.json"
    _write_scope(scope_doc)
    _write_baseline(baseline_doc)
    monkeypatch.setattr(gate, "SCOPE_DOC", scope_doc)
    monkeypatch.setattr(gate, "BASELINE_DOC", baseline_doc)
    assert gate.run() == 0


def test_competitive_scope_gate_fails_when_baseline_artifact_missing(tmp_path, monkeypatch):
    scope_doc = tmp_path / "PROJECT_SCOPE.md"
    _write_scope(scope_doc)
    monkeypatch.setattr(gate, "SCOPE_DOC", scope_doc)
    monkeypatch.setattr(gate, "BASELINE_DOC", tmp_path / "missing.json")
    assert gate.run() == 1


def test_competitive_scope_gate_fails_on_invalid_commit_hash(tmp_path, monkeypatch):
    scope_doc = tmp_path / "PROJECT_SCOPE.md"
    baseline_doc = tmp_path / "openclaw.current.json"
    _write_scope(scope_doc)
    _write_baseline(baseline_doc, commit="not-a-sha")
    monkeypatch.setattr(gate, "SCOPE_DOC", scope_doc)
    monkeypatch.setattr(gate, "BASELINE_DOC", baseline_doc)
    assert gate.run() == 1
