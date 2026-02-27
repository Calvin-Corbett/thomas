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
    assert "required freshness sources are stale" in out


def test_guard_uses_latest_registry_run_when_newer_than_report(tmp_path: Path, capsys) -> None:
    result = tmp_path / "latest_full_suite_compare.json"
    registry = tmp_path / "competitor_registry.json"
    _write_json(result, {"computed_at_utc": "2026-02-24T20:00:00Z"})
    _write_json(
        registry,
        {
            "updated_at_utc": "2026-02-24T20:00:00Z",
            "runs": [
                {"computed_at_utc": "2026-02-24T21:00:00Z"},
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
    assert payload["required_stale_sources"] == []
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
    assert "missing or invalid required timestamp: result.computed_at_utc" in payload["errors"]
    assert "missing or invalid required timestamp: registry.updated_at_utc" in payload["errors"]


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


def test_guard_uses_suite_config_artifact_paths_when_paths_omitted(tmp_path: Path, capsys) -> None:
    result = tmp_path / "artifacts" / "latest_full_suite_compare.json"
    legacy = tmp_path / "artifacts" / "latest_compare.json"
    registry = tmp_path / "artifacts" / "competitor_registry.json"
    suite_config = tmp_path / "suite.json"

    _write_json(result, {"computed_at_utc": "2026-02-24T23:00:00Z"})
    _write_json(legacy, {"computed_at_utc": "2026-02-24T23:00:00Z"})
    _write_json(registry, {"updated_at_utc": "2026-02-24T23:00:00Z", "runs": []})
    _write_json(
        suite_config,
        {
            "artifact_paths": {
                "latest_json": str(result),
                "latest_legacy_json": str(legacy),
                "registry_json": str(registry),
            }
        },
    )

    rc = mod.run(
        [
            "--suite-config",
            str(suite_config),
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
    assert payload["result_json"] == str(result)
    assert payload["legacy_result_json"] == str(legacy)
    assert payload["registry_json"] == str(registry)


def test_guard_uses_latest_legacy_result_from_suite_config_candidates(tmp_path: Path, capsys) -> None:
    result = tmp_path / "artifacts" / "latest_full_suite_compare.json"
    legacy = tmp_path / "artifacts" / "latest_compare.json"
    registry = tmp_path / "artifacts" / "competitor_registry.json"
    suite_config = tmp_path / "suite.json"

    _write_json(result, {"computed_at_utc": "2026-02-24T20:00:00Z"})
    _write_json(legacy, {"computed_at_utc": "2026-02-24T20:30:00Z"})
    _write_json(registry, {"updated_at_utc": "2026-02-24T20:00:00Z", "runs": []})
    _write_json(
        suite_config,
        {
            "artifact_paths": {
                "latest_json": str(result),
                "latest_legacy_json": str(legacy),
                "registry_json": str(registry),
            }
        },
    )

    rc = mod.run(
        [
            "--suite-config",
            str(suite_config),
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
    assert payload["latest_run_source"] == "legacy_result.computed_at_utc"
    assert payload["required_stale_sources"] == []
    assert payload["stale"] is False


def test_guard_fails_when_canonical_timestamps_are_stale_even_if_legacy_is_fresh(tmp_path: Path, capsys) -> None:
    result = tmp_path / "artifacts" / "latest_full_suite_compare.json"
    legacy = tmp_path / "artifacts" / "latest_compare.json"
    registry = tmp_path / "artifacts" / "competitor_registry.json"
    suite_config = tmp_path / "suite.json"

    _write_json(result, {"computed_at_utc": "2026-02-01T00:00:00Z"})
    _write_json(legacy, {"computed_at_utc": "2026-02-24T20:30:00Z"})
    _write_json(registry, {"updated_at_utc": "2026-02-01T00:00:00Z", "runs": []})
    _write_json(
        suite_config,
        {
            "artifact_paths": {
                "latest_json": str(result),
                "latest_legacy_json": str(legacy),
                "registry_json": str(registry),
            }
        },
    )

    rc = mod.run(
        [
            "--suite-config",
            str(suite_config),
            "--max-age-days",
            "7",
            "--now",
            "2026-02-25T12:00:00+00:00",
            "--json",
        ]
    )
    payload = json.loads(capsys.readouterr().out)

    assert rc == 1
    assert payload["ok"] is False
    assert payload["stale"] is True
    assert set(payload["required_stale_sources"]) == {
        "result.computed_at_utc",
        "registry.updated_at_utc",
    }


def test_guard_skips_implicit_legacy_lookup_when_result_path_is_explicit(tmp_path: Path, capsys) -> None:
    result = tmp_path / "latest_full_suite_compare.json"
    registry = tmp_path / "competitor_registry.json"
    suite_config = tmp_path / "suite.json"

    _write_json(result, {"computed_at_utc": "2026-02-24T23:00:00Z"})
    _write_json(registry, {"updated_at_utc": "2026-02-24T23:00:00Z", "runs": []})
    _write_json(
        suite_config,
        {"artifact_paths": {"latest_legacy_json": str(tmp_path / "missing_latest_compare.json")}},
    )

    rc = mod.run(
        [
            "--suite-config",
            str(suite_config),
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
    assert payload["legacy_result_json"] == ""
