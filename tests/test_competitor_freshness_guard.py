from __future__ import annotations

import json
from pathlib import Path

import scripts.check_competitor_freshness_guard as mod


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_guard_passes_when_latest_run_is_within_threshold(tmp_path: Path, capsys) -> None:
    result = tmp_path / "latest_full_suite_compare.json"
    registry = tmp_path / "competitor_registry.json"
    _write_json(result, {"computed_at_utc": "2026-02-24T23:00:00Z"})
    _write_json(
        registry,
        {
            "updated_at_utc": "2026-02-24T23:00:00Z",
            "runs": [{"computed_at_utc": "2026-02-24T23:00:00Z"}],
        },
    )

    rc = mod.run(
        [
            "--result-json",
            str(result),
            "--registry-json",
            str(registry),
            "--max-age-days",
            "7",
            "--now",
            "2026-02-25T12:00:00+00:00",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 0
    assert "Competitor freshness guard: PASS" in out


def test_guard_fails_when_latest_run_is_stale(tmp_path: Path, capsys) -> None:
    result = tmp_path / "latest_full_suite_compare.json"
    registry = tmp_path / "competitor_registry.json"
    _write_json(result, {"computed_at_utc": "2026-02-01T00:00:00Z"})
    _write_json(
        registry,
        {
            "updated_at_utc": "2026-02-01T00:00:00Z",
            "runs": [{"computed_at_utc": "2026-02-01T00:00:00Z"}],
        },
    )

    rc = mod.run(
        [
            "--result-json",
            str(result),
            "--registry-json",
            str(registry),
            "--max-age-days",
            "7",
            "--now",
            "2026-02-25T12:00:00+00:00",
        ]
    )
    out = capsys.readouterr().out

    assert rc == 1
    assert "Competitor freshness guard: FAIL" in out
    assert "latest run is stale" in out


def test_guard_uses_latest_registry_run_when_newer_than_report(tmp_path: Path, capsys) -> None:
    result = tmp_path / "latest_full_suite_compare.json"
    registry = tmp_path / "competitor_registry.json"
    _write_json(result, {"computed_at_utc": "2026-02-01T00:00:00Z"})
    _write_json(
        registry,
        {
            "updated_at_utc": "2026-02-01T00:00:00Z",
            "runs": [
                {"computed_at_utc": "2026-02-24T20:00:00Z"},
                {"computed_at_utc": "2026-02-12T09:00:00Z"},
            ],
        },
    )

    rc = mod.run(
        [
            "--result-json",
            str(result),
            "--registry-json",
            str(registry),
            "--max-age-days",
            "7",
            "--now",
            "2026-02-25T12:00:00+00:00",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 0
    assert payload["ok"] is True
    assert payload["latest_run_source"] == "registry.runs[0].computed_at_utc"
    assert payload["stale"] is False


def test_guard_fails_when_no_valid_timestamps_exist(tmp_path: Path, capsys) -> None:
    result = tmp_path / "latest_full_suite_compare.json"
    registry = tmp_path / "competitor_registry.json"
    _write_json(result, {})
    _write_json(registry, {"updated_at_utc": "", "runs": [{}, {"computed_at_utc": ""}]})

    rc = mod.run(
        [
            "--result-json",
            str(result),
            "--registry-json",
            str(registry),
            "--max-age-days",
            "7",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert any("no valid competitor run timestamps found" in item for item in payload["errors"])


def test_guard_rejects_non_positive_threshold(tmp_path: Path, capsys) -> None:
    result = tmp_path / "latest_full_suite_compare.json"
    registry = tmp_path / "competitor_registry.json"
    _write_json(result, {"computed_at_utc": "2026-02-24T23:00:00Z"})
    _write_json(registry, {"updated_at_utc": "2026-02-24T23:00:00Z", "runs": []})

    rc = mod.run(
        [
            "--result-json",
            str(result),
            "--registry-json",
            str(registry),
            "--max-age-days",
            "0",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert "--max-age-days must be > 0" in payload["errors"]


def test_guard_fails_when_required_artifact_is_missing(tmp_path: Path, capsys) -> None:
    result = tmp_path / "latest_full_suite_compare.json"
    _write_json(result, {"computed_at_utc": "2026-02-24T23:00:00Z"})

    rc = mod.run(
        [
            "--result-json",
            str(result),
            "--registry-json",
            str(tmp_path / "missing_registry.json"),
            "--max-age-days",
            "7",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert any("missing JSON file" in item for item in payload["errors"])
