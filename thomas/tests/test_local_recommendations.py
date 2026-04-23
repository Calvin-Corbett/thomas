from __future__ import annotations

from thomas.models.local_recommendations import (
    build_local_runtime_plan,
    classify_device_tier,
    local_background_task_catalog,
    recommended_local_models_for_tier,
)


def _hardware(*, cpu_cores: int, ram_gb: float, max_vram_gb: float, gpu_util: float | None = None):
    return {
        "cpu": {"cores": cpu_cores},
        "memory": {"total_gb": ram_gb},
        "gpu": {
            "count": 1 if max_vram_gb > 0 else 0,
            "devices": [],
            "max_vram_gb": max_vram_gb,
            "average_utilization_pct": gpu_util,
        },
        "device_tier": "unknown",
    }


def test_classify_device_tier_bounds() -> None:
    assert classify_device_tier(cpu_cores=4, ram_gb=8.0, max_vram_gb=0.0) == "low"
    assert classify_device_tier(cpu_cores=8, ram_gb=32.0, max_vram_gb=8.0) == "standard"
    assert classify_device_tier(cpu_cores=16, ram_gb=64.0, max_vram_gb=24.0) == "power"


def test_low_tier_plan_defaults_to_cloud_only() -> None:
    plan = build_local_runtime_plan(
        hardware=_hardware(cpu_cores=4, ram_gb=8.0, max_vram_gb=0.0),
        local_profile_exists=True,
        ollama_installed=False,
        ollama_running=False,
    )
    assert plan["device_tier"] == "low"
    assert plan["recommended_mode"] == "cloud_only"
    assert plan["recommended_connection_path"] == "cloud"
    assert plan["recommended_models"] == []


def test_power_tier_plan_recommends_local_models() -> None:
    plan = build_local_runtime_plan(
        hardware=_hardware(cpu_cores=16, ram_gb=64.0, max_vram_gb=24.0),
        local_profile_exists=True,
        ollama_installed=True,
        ollama_running=True,
    )
    assert plan["device_tier"] == "power"
    assert plan["recommended_mode"] == "local_preferred"
    assert plan["recommended_connection_path"] == "local"
    assert len(plan["recommended_models"]) >= 2


def test_catalogs_are_non_empty_for_supported_tiers() -> None:
    assert recommended_local_models_for_tier("standard")
    assert recommended_local_models_for_tier("power")
    task_ids = {row["id"] for row in local_background_task_catalog()}
    assert "memory_digest_refresh" in task_ids
