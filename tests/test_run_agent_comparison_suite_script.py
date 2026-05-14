from __future__ import annotations

import json
from pathlib import Path
from collections.abc import Sequence

import scripts.run_agent_comparison_suite as mod


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _arg_value(argv: Sequence[str], flag: str) -> str | None:
    for idx, token in enumerate(argv):
        if token == flag and idx + 1 < len(argv):
            return str(argv[idx + 1])
        if token.startswith(f"{flag}="):
            return str(token.split("=", 1)[1])
    return None


def _read_suite_config_from_forwarded_argv(argv: Sequence[str]) -> dict:
    suite_config = _arg_value(argv, "--suite-config")
    assert suite_config is not None
    return json.loads(Path(suite_config).read_text(encoding="utf-8"))


def test_run_injects_artifact_paths_from_suite_config_when_missing(monkeypatch, tmp_path: Path) -> None:
    latest_json = tmp_path / "artifacts" / "latest_full_suite_compare.json"
    latest_md = tmp_path / "artifacts" / "latest_full_suite_compare.md"
    legacy_json = tmp_path / "artifacts" / "latest_compare.json"
    registry_json = tmp_path / "artifacts" / "competitor_registry.json"
    registry_md = tmp_path / "artifacts" / "competitor_registry.md"
    suite_config = tmp_path / "suite.json"
    _write_json(
        suite_config,
        {
            "artifact_paths": {
                "latest_json": str(latest_json),
                "latest_markdown": str(latest_md),
                "latest_legacy_json": str(legacy_json),
                "registry_json": str(registry_json),
                "registry_markdown": str(registry_md),
            }
        },
    )

    captured: dict[str, list[str]] = {}

    def fake_main(argv: Sequence[str] | None = None) -> int:
        assert argv is not None
        captured["argv"] = list(argv)
        write_path = _arg_value(argv, "--write-path")
        assert write_path is not None
        path = Path(write_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"computed_at_utc":"2026-02-25T00:00:00Z"}', encoding="utf-8")
        return 0

    monkeypatch.setattr(mod._suite, "main", fake_main)

    rc = mod.run(["--suite-config", str(suite_config), "--write", "--write-md"])
    assert rc == 0
    forwarded = captured["argv"]
    assert _arg_value(forwarded, "--write-path") == str(latest_json)
    assert _arg_value(forwarded, "--write-md-path") == str(latest_md)
    assert _arg_value(forwarded, "--registry-path") == str(registry_json)
    assert _arg_value(forwarded, "--registry-md-path") == str(registry_md)


def test_run_mirrors_canonical_json_to_legacy_json(monkeypatch, tmp_path: Path) -> None:
    latest_json = tmp_path / "artifacts" / "latest_full_suite_compare.json"
    legacy_json = tmp_path / "artifacts" / "latest_compare.json"
    registry_json = tmp_path / "artifacts" / "competitor_registry.json"
    registry_md = tmp_path / "artifacts" / "competitor_registry.md"
    suite_config = tmp_path / "suite.json"
    _write_json(
        suite_config,
        {
            "artifact_paths": {
                "latest_json": str(latest_json),
                "latest_legacy_json": str(legacy_json),
                "registry_json": str(registry_json),
                "registry_markdown": str(registry_md),
            }
        },
    )

    payload = {"computed_at_utc": "2026-02-25T01:00:00Z", "suite": {"id": "x"}}

    def fake_main(argv: Sequence[str] | None = None) -> int:
        assert argv is not None
        write_path = _arg_value(argv, "--write-path")
        assert write_path is not None
        _write_json(Path(write_path), payload)
        return 0

    monkeypatch.setattr(mod._suite, "main", fake_main)

    rc = mod.run(["--suite-config", str(suite_config), "--write"])
    assert rc == 0
    assert latest_json.exists()
    assert legacy_json.exists()
    assert json.loads(latest_json.read_text(encoding="utf-8")) == payload
    assert json.loads(legacy_json.read_text(encoding="utf-8")) == payload


def test_run_normalizes_legacy_benchmark_keys_and_aliases(monkeypatch, tmp_path: Path) -> None:
    suite_config = tmp_path / "suite.json"
    _write_json(
        suite_config,
        {
            "agents": [
                {
                    "id": "openclaw",
                    "benchmark_alias": "openclaw_live",
                    "benchmark_scorecard_glob": "demo/agentic-runs/*/scorecard.json",
                    "benchmark_raw_glob": "demo/agentic-runs/*/benchmark_results.raw.json",
                }
            ]
        },
    )

    captured: dict[str, list[str]] = {}

    def fake_main(argv: Sequence[str] | None = None) -> int:
        assert argv is not None
        captured["argv"] = list(argv)
        payload = _read_suite_config_from_forwarded_argv(argv)
        agent = dict(payload["agents"][0])
        assert agent["benchmark_aliases"] == ["openclaw_live", "openclaw"]
        assert agent["benchmark_scorecard_globs"] == ["demo/agentic-runs/*/scorecard.json"]
        assert agent["benchmark_raw_globs"] == ["demo/agentic-runs/*/benchmark_results.raw.json"]
        assert agent["benchmark_evidence_globs"] == ["demo/agentic-runs/*/benchmark_results.raw.json"]
        return 0

    monkeypatch.setattr(mod._suite, "main", fake_main)

    rc = mod.run(["--suite-config", str(suite_config)])
    assert rc == 0
    forwarded = captured["argv"]
    normalized_suite_config = Path(_arg_value(forwarded, "--suite-config") or "")
    assert normalized_suite_config != suite_config
    assert normalized_suite_config.exists() is False


def test_run_normalizes_single_string_benchmark_lists(monkeypatch, tmp_path: Path) -> None:
    suite_config = tmp_path / "suite.json"
    _write_json(
        suite_config,
        {
            "agents": [
                {
                    "id": "thomas",
                    "benchmark_aliases": "thomas_os",
                    "benchmark_scorecard_globs": "demo/agentic-runs/*/scorecard.json",
                    "benchmark_raw_globs": "demo/agentic-runs/*/benchmark_results.raw.json",
                    "benchmark_evidence_glob": "demo/agentic-runs/*/benchmark_results.raw.json",
                }
            ]
        },
    )

    def fake_main(argv: Sequence[str] | None = None) -> int:
        assert argv is not None
        payload = _read_suite_config_from_forwarded_argv(argv)
        agent = dict(payload["agents"][0])
        assert agent["benchmark_aliases"] == ["thomas_os", "thomas"]
        assert agent["benchmark_scorecard_globs"] == ["demo/agentic-runs/*/scorecard.json"]
        assert agent["benchmark_raw_globs"] == ["demo/agentic-runs/*/benchmark_results.raw.json"]
        assert agent["benchmark_evidence_globs"] == ["demo/agentic-runs/*/benchmark_results.raw.json"]
        return 0

    monkeypatch.setattr(mod._suite, "main", fake_main)
    rc = mod.run(["--suite-config", str(suite_config)])
    assert rc == 0


def test_default_suite_config_includes_resilience_soak_probe_with_streak_limits() -> None:
    payload = json.loads(Path(mod.DEFAULT_SUITE_CONFIG).read_text(encoding="utf-8"))
    agents = {
        str(agent.get("id") or "").strip(): dict(agent)
        for agent in list(payload.get("agents") or [])
        if str(agent.get("id") or "").strip()
    }
    thomas = dict(agents["thomas"])
    probes = list(thomas.get("resilience_probes") or [])
    soak = next((row for row in probes if str(row.get("id") or "") == "resilience_soak_models_status"), None)
    assert soak is not None

    command = [str(item) for item in list(soak.get("command") or [])]
    assert "scripts/soak_runner.py" in command
    assert _arg_value(command, "--iterations") == "5"
    assert _arg_value(command, "--max-consecutive-failures") == "1"
    assert _arg_value(command, "--max-consecutive-probe-failures") == "1"
    assert _arg_value(command, "--max-failure-rate") == "0.2"
    assert _arg_value(command, "--max-probe-failure-rate") == "0.2"

    assertions = list(soak.get("assertions") or [])
    paths = {str(item.get("path") or "") for item in assertions if isinstance(item, dict)}
    assert "summary.max_consecutive_failures" in paths
    assert "summary.max_consecutive_probe_failures" in paths
