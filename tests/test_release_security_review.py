"""Ensure the current release's security review artifacts satisfy their live gates."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import tomllib

from thomas.core import persistence
from thomas.marketplace.security.mutating_route_policy import evaluate_mutating_route_policy_exceptions
from thomas.marketplace.security.threat_model_cadence import evaluate_threat_model_cadence

ROOT = Path(__file__).resolve().parents[1]


def test_current_release_security_review_is_complete(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # The route audit boots an app, but must never load your actual runtime state.
    state = tmp_path / "state.json"
    reports = tmp_path / "reports"
    monkeypatch.setattr(persistence, "_DEFAULT_STATE_FILE", state)
    monkeypatch.setattr(persistence, "_DEFAULT_REPORT_DIR", reports)
    monkeypatch.setattr(persistence, "_engine", persistence.PersistenceEngine(state, report_dir=reports))

    version = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(rf"^## \[{re.escape(version)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", changelog, re.MULTILINE)

    cadence = evaluate_threat_model_cadence(ROOT / "docs/THREAT_MODEL_WEB_API.md", max_age_days=30)
    assert cadence["ok"], cadence["errors"]

    routes = evaluate_mutating_route_policy_exceptions(ROOT)
    assert routes["ok"], routes["errors"]
