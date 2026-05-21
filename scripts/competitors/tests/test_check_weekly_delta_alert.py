from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import scripts.competitors.check_weekly_delta_alert as mod


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _run(ts: str, *, beat: Any = None, threat: Any = None, competitor: str = "comp_a") -> dict:
    row: dict = {"competitor": competitor}
    if beat is not None:
        row["metrics_beating_focus"] = beat
    if threat is not None:
        row["composite_score"] = threat
    return {
        "computed_at_utc": ts,
        "focus": {
            "competitor_pressure": {
                "ranked_competitors": [row],
            }
        },
    }


def _run_json(*, registry: Path, args: list[str], capsys) -> tuple[int, dict]:
    rc = mod.run(
        [
            "--registry-json",
            str(registry),
            "--json",
            *args,
        ]
    )
    payload = json.loads(capsys.readouterr().out)
    return rc, payload


def _run_json_args(*, args: list[str], capsys) -> tuple[int, dict]:
    rc = mod.run(["--json", *args])
    payload = json.loads(capsys.readouterr().out)
    return rc, payload


def test_guard_passes_with_insufficient_history_even_in_strict_mode(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "competitor_registry.json"
    _write_json(
        registry,
        {
            "runs": [
                _run("2026-02-24T00:00:00Z", beat=1, threat=32.0),
                _run("2026-02-25T00:00:00Z", beat=2, threat=34.0),
            ]
        },
    )

    rc, payload = _run_json(registry=registry, args=["--lookback-days", "7", "--strict"], capsys=capsys)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["status"] == "insufficient_history"
    assert payload["alert_count"] == 0


def test_guard_alerts_when_beat_metric_count_worsens(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "competitor_registry.json"
    _write_json(
        registry,
        {
            "runs": [
                _run("2026-02-01T00:00:00Z", beat=1, threat=42.0),
                _run("2026-02-10T00:00:00Z", beat=3, threat=42.0),
            ]
        },
    )

    rc, payload = _run_json(registry=registry, args=["--lookback-days", "7", "--strict"], capsys=capsys)

    assert rc == 1
    assert payload["status"] == "alert"
    assert payload["alert_count"] == 1
    assert payload["metrics"]["beat_metric_count"]["delta"] == 2.0
    assert payload["alerts"][0]["metric"] == "beat_metric_count"


def test_guard_alerts_when_threat_score_worsens(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "competitor_registry.json"
    _write_json(
        registry,
        {
            "runs": [
                _run("2026-02-01T00:00:00Z", beat=2, threat=33.5),
                _run("2026-02-10T00:00:00Z", beat=2, threat=50.0),
            ]
        },
    )

    rc, payload = _run_json(registry=registry, args=["--lookback-days", "7", "--strict"], capsys=capsys)

    assert rc == 1
    assert payload["status"] == "alert"
    assert payload["alert_count"] == 1
    assert payload["metrics"]["threat_score"]["delta"] == 16.5
    assert payload["alerts"][0]["metric"] == "threat_score"


def test_guard_alerts_in_non_strict_mode_without_nonzero_exit(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "competitor_registry.json"
    _write_json(
        registry,
        {
            "runs": [
                _run("2026-02-01T00:00:00Z", beat=1, threat=20.0),
                _run("2026-02-10T00:00:00Z", beat=3, threat=33.5),
            ]
        },
    )

    rc, payload = _run_json(registry=registry, args=["--lookback-days", "7"], capsys=capsys)

    assert rc == 0
    assert payload["ok"] is False
    assert payload["strict"] is False
    assert payload["status"] == "alert"
    assert payload["would_fail_strict"] is True
    assert payload["errors"] == []
    assert payload["alert_count"] == 2


def test_guard_allows_partial_metric_comparison_with_warning(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "competitor_registry.json"
    _write_json(
        registry,
        {
            "runs": [
                _run("2026-02-01T00:00:00Z", beat=1, threat=20.0),
                _run("2026-02-10T00:00:00Z", beat=3, threat=None),
            ]
        },
    )

    rc, payload = _run_json(registry=registry, args=["--lookback-days", "7", "--strict"], capsys=capsys)

    assert rc == 1
    assert payload["status"] == "alert"
    assert payload["alert_count"] == 1
    assert payload["metrics"]["beat_metric_count"]["delta"] == 2.0
    assert "threat_score" not in payload["metrics"]
    assert any("missing comparable metric 'threat_score'" in item for item in payload["warnings"])


def test_guard_errors_when_latest_and_baseline_have_no_common_metric(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "competitor_registry.json"
    _write_json(
        registry,
        {
            "runs": [
                _run("2026-02-01T00:00:00Z", beat=1, threat=None),
                _run("2026-02-10T00:00:00Z", beat=None, threat=45.0),
            ]
        },
    )

    rc, payload = _run_json(registry=registry, args=["--lookback-days", "7"], capsys=capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["strict"] is False
    assert payload["would_fail_strict"] is True
    assert payload["status"] == "error"
    assert payload["alert_count"] == 0
    assert payload["metrics"] == {}
    assert "no comparable competitor pressure metrics found between latest and baseline runs" in payload["errors"]
    assert any("missing comparable metric 'beat_metric_count'" in item for item in payload["warnings"])
    assert any("missing comparable metric 'threat_score'" in item for item in payload["warnings"])


def test_guard_passes_when_metrics_improve_or_hold(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "competitor_registry.json"
    _write_json(
        registry,
        {
            "runs": [
                _run("2026-02-01T00:00:00Z", beat=2, threat=50.0),
                _run("2026-02-10T00:00:00Z", beat=1, threat=49.0),
            ]
        },
    )

    rc, payload = _run_json(registry=registry, args=["--lookback-days", "7", "--strict"], capsys=capsys)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["alert_count"] == 0


def test_guard_selects_latest_baseline_run_on_or_before_cutoff(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "competitor_registry.json"
    _write_json(
        registry,
        {
            "runs": [
                _run("2026-02-10T00:00:00Z", beat=1, threat=20.0, competitor="old_baseline"),
                _run("2026-02-19T00:00:00Z", beat=9, threat=90.0, competitor="too_new_for_baseline"),
                _run("2026-02-25T00:00:00Z", beat=2, threat=21.0, competitor="latest"),
            ]
        },
    )

    rc, payload = _run_json(registry=registry, args=["--lookback-days", "7", "--strict"], capsys=capsys)

    assert rc == 1
    assert payload["baseline_run_source"] == "registry.runs[0]"
    assert payload["baseline_top_competitor"] == "old_baseline"
    assert payload["alert_count"] == 2
    assert {row["metric"] for row in payload["alerts"]} == {
        "beat_metric_count",
        "threat_score",
    }


def test_guard_rejects_non_positive_lookback_days(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "competitor_registry.json"
    _write_json(registry, {"runs": []})

    rc, payload = _run_json(registry=registry, args=["--lookback-days", "0"], capsys=capsys)

    assert rc == 1
    assert payload["ok"] is False
    assert "--lookback-days must be > 0" in payload["errors"]


def test_guard_rejects_non_finite_lookback_days(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "competitor_registry.json"
    _write_json(
        registry,
        {
            "runs": [
                _run("2026-02-01T00:00:00Z", beat=1, threat=10.0),
                _run("2026-02-10T00:00:00Z", beat=1, threat=10.0),
            ]
        },
    )

    for token in ("nan", "inf", "-inf"):
        rc, payload = _run_json(registry=registry, args=[f"--lookback-days={token}"], capsys=capsys)
        assert rc == 1
        assert payload["ok"] is False
        assert payload["status"] == "error"
        assert payload["strict"] is False
        assert payload["would_fail_strict"] is True
        assert payload["lookback_days"] is None
        assert "--lookback-days must be finite" in payload["errors"]


def test_guard_skips_non_finite_metric_values_with_warning(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "competitor_registry.json"
    _write_json(
        registry,
        {
            "runs": [
                _run("2026-02-01T00:00:00Z", beat=1, threat=20.0),
                _run("2026-02-10T00:00:00Z", beat="NaN", threat=21.0),
            ]
        },
    )

    rc, payload = _run_json(registry=registry, args=["--lookback-days", "7", "--strict"], capsys=capsys)

    assert rc == 1
    assert payload["status"] == "alert"
    assert payload["alert_count"] == 1
    assert payload["alerts"][0]["metric"] == "threat_score"
    assert payload["metrics"]["threat_score"]["delta"] == 1.0
    assert "beat_metric_count" not in payload["metrics"]
    assert any("non-finite competitor metric 'metrics_beating_focus'" in item for item in payload["warnings"])
    assert any("missing comparable metric 'beat_metric_count'" in item for item in payload["warnings"])


def test_guard_resolves_registry_path_from_suite_config(tmp_path: Path, capsys) -> None:
    registry = tmp_path / "alt" / "registry.json"
    _write_json(
        registry,
        {
            "runs": [
                _run("2026-02-01T00:00:00Z", beat=1, threat=42.0),
                _run("2026-02-10T00:00:00Z", beat=1, threat=42.0),
            ]
        },
    )
    suite = tmp_path / "agent_comparison_suite.current.json"
    _write_json(
        suite,
        {
            "artifact_paths": {
                "registry_json": str(registry),
            }
        },
    )

    rc, payload = _run_json_args(args=["--suite-config", str(suite), "--lookback-days", "7"], capsys=capsys)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["registry_json"] == str(registry.resolve())
    assert payload["suite_config"] == str(suite.resolve())


def test_workflows_wire_weekly_delta_alerting_guards() -> None:
    root = Path(__file__).resolve().parents[3]
    robustness = (root / ".github" / "workflows" / "robustness-gates.yml").read_text(encoding="utf-8")
    nightly = (root / ".github" / "workflows" / "nightly-reliability.yml").read_text(encoding="utf-8")

    assert "python scripts/competitors/check_weekly_delta_alert.py --strict" in robustness
    assert "python -m pytest -q scripts/competitors/tests/test_check_weekly_delta_alert.py" in robustness
    # Nightly runs the alert in --strict mode so a delta returns non-zero, then
    # captures the exit code via `set +e` / `competitor_delta_exit_code=$?` so
    # the workflow itself doesn't fail. The strict-mode invocation is asserted
    # separately by tests/test_ci_workflow_guards.py::
    #   test_nightly_reliability_uses_strict_competitor_and_security_checks
    nightly_delta_lines = [line.strip() for line in nightly.splitlines() if "check_weekly_delta_alert.py" in line]
    assert nightly_delta_lines
    assert any(
        "--json" in line and "artifacts/nightly_reliability/competitor_delta_alerting.json" in line
        for line in nightly_delta_lines
    )
    assert "competitor_delta_exit_code=$?" in nightly
    assert "artifacts/nightly_reliability/competitor_delta_alerting.exit_code" in nightly
    assert "competitor weekly delta strict-fail signal" in nightly
    assert "competitor weekly delta command exit code" in nightly
    assert "competitor weekly delta status" in nightly
