from __future__ import annotations

import json

from thomas.core.local_agent_engine import LocalAgentEngine


def _hardware(*, gpu_util: float | None = None):
    return {
        "cpu": {"cores": 12},
        "memory": {"total_gb": 64.0},
        "gpu": {
            "count": 1,
            "devices": [],
            "max_vram_gb": 16.0,
            "average_utilization_pct": gpu_util,
        },
        "device_tier": "power",
    }


def test_local_agent_engine_skips_when_settings_disabled(monkeypatch, tmp_path) -> None:
    engine = LocalAgentEngine(log_path=tmp_path / "local-agent.jsonl", idle_threshold_s=0.0)
    engine._last_user_ts = 0.0

    monkeypatch.setattr(engine, "_load_runtime_settings", lambda: {"enabled": False, "min_gpu_headroom_pct": 35})
    monkeypatch.setattr(
        "thomas.core.local_agent_engine.detect_local_hardware_profile", lambda: _hardware(gpu_util=10.0)
    )
    monkeypatch.setattr(
        "thomas.core.local_agent_engine.build_local_runtime_plan",
        lambda **_kwargs: {"recommended_mode": "hybrid", "recommended_models": []},
    )

    result = engine.run_cycle_once(reason="manual", force=False)
    assert result["ok"] is False
    assert result["reason"] == "engine_disabled"
    assert result["skip_reason"] == "disabled_in_settings"


def test_local_agent_engine_runs_when_enabled(monkeypatch, tmp_path) -> None:
    engine = LocalAgentEngine(log_path=tmp_path / "local-agent.jsonl", idle_threshold_s=0.0)
    engine._last_user_ts = 0.0

    monkeypatch.setattr(engine, "_load_runtime_settings", lambda: {"enabled": True, "min_gpu_headroom_pct": 20})
    monkeypatch.setattr(
        "thomas.core.local_agent_engine.detect_local_hardware_profile", lambda: _hardware(gpu_util=30.0)
    )
    monkeypatch.setattr(
        "thomas.core.local_agent_engine.build_local_runtime_plan",
        lambda **_kwargs: {"recommended_mode": "hybrid", "recommended_models": [{"id": "qwen2.5:7b"}]},
    )
    monkeypatch.setattr(
        engine,
        "_run_background_tasks",
        lambda **_kwargs: [{"ok": True, "id": "memory_digest_refresh"}],
    )

    result = engine.run_cycle_once(reason="manual", force=False)
    assert result["ok"] is True
    assert result["skip_reason"] == ""
    assert result["tasks"][0]["id"] == "memory_digest_refresh"


def test_local_agent_engine_reports_health_from_cycle_log(tmp_path) -> None:
    log_path = tmp_path / "local-agent.jsonl"
    rows = [
        {"ok": True, "timestamp": "2026-01-01T00:00:00+00:00", "skip_reason": "", "tasks": [{"ok": True}]},
        {
            "ok": False,
            "timestamp": "2026-01-01T01:00:00+00:00",
            "skip_reason": "gpu_headroom_low",
            "tasks": [{"ok": False}],
        },
        {
            "ok": False,
            "timestamp": "2026-01-01T02:00:00+00:00",
            "skip_reason": "disabled_in_settings",
            "tasks": [{"ok": True}],
        },
    ]
    with log_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    engine = LocalAgentEngine(log_path=log_path, idle_threshold_s=0.0)
    recent = engine.recent_reports(limit=2)
    assert len(recent) == 2
    assert recent[-1]["skip_reason"] == "disabled_in_settings"

    health = engine.health_snapshot(history_limit=5)
    assert health["history_count"] == 3
    assert health["failed_cycles"] == 2
    assert health["task_failures"] == 1
    assert health["skip_reasons"]["gpu_headroom_low"] == 1
