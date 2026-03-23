from __future__ import annotations

import os
import time
from pathlib import Path

from thomas.marketplace.security.threat_model_cadence import evaluate_threat_model_cadence


def test_threat_model_cadence_flags_stale_file(tmp_path: Path) -> None:
    model = tmp_path / "THREAT_MODEL.md"
    model.write_text("# Threat model\nLast reviewed: 2000-01-01\n", encoding="utf-8")

    stale_seconds = 60 * 60 * 24 * 60
    old = time.time() - stale_seconds
    os.utime(model, (old, old))

    report = evaluate_threat_model_cadence(model, max_age_days=14)
    assert report["ok"] is False
    codes = {item["code"] for item in report["errors"]}
    assert "threat_model.stale_file_mtime" in codes
    assert "threat_model.last_reviewed_stale" in codes


def test_threat_model_cadence_warns_when_last_reviewed_missing(tmp_path: Path) -> None:
    model = tmp_path / "THREAT_MODEL.md"
    model.write_text("# Threat model\n", encoding="utf-8")

    report = evaluate_threat_model_cadence(model, max_age_days=365)
    assert report["ok"] is True
    assert any(item["code"] == "threat_model.last_reviewed_missing" for item in report["warnings"])
