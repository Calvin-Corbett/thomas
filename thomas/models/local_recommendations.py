"""Hardware-aware local model recommendations and background-task catalog."""

from __future__ import annotations

import ctypes
import json
import os
import platform
import subprocess
from typing import Any

_DEFAULT_GPU_HEADROOM_PCT = 35

_TIER_MODEL_RECIPES: dict[str, list[dict[str, Any]]] = {
    "low": [],
    "standard": [
        {
            "id": "qwen2.5:7b",
            "role": "daily_local_agent",
            "min_vram_gb": 8.0,
            "tool_use": "recommended",
            "notes": "Balanced local model for routine tool-using flows.",
        },
        {
            "id": "llama3.1:8b",
            "role": "fallback_local_agent",
            "min_vram_gb": 10.0,
            "tool_use": "recommended",
            "notes": "Secondary model for resilience when the main local model is busy.",
        },
    ],
    "power": [
        {
            "id": "qwen2.5:14b",
            "role": "primary_local_agent",
            "min_vram_gb": 16.0,
            "tool_use": "strong",
            "notes": "Primary local model for long tool-heavy tasks.",
        },
        {
            "id": "llama3.1:8b",
            "role": "fast_local_agent",
            "min_vram_gb": 10.0,
            "tool_use": "recommended",
            "notes": "Fast model for lightweight local background execution.",
        },
        {
            "id": "deepseek-r1:14b",
            "role": "reasoning_local_agent",
            "min_vram_gb": 16.0,
            "tool_use": "recommended",
            "notes": "Reasoning-heavy fallback for complex local planning.",
        },
    ],
}

_BACKGROUND_TASK_CATALOG: list[dict[str, Any]] = [
    {
        "id": "memory_digest_refresh",
        "name": "Memory Digest Refresh",
        "category": "memory",
        "description": "Roll up recent turns and open goals into a compact memory digest for faster retrieval.",
        "cadence": "idle_cycle",
    },
    {
        "id": "local_model_readiness",
        "name": "Local Model Readiness Check",
        "category": "models",
        "description": "Compare installed Ollama models against the hardware-recommended local model set.",
        "cadence": "idle_cycle",
    },
    {
        "id": "local_model_backlog",
        "name": "Local Model Backlog Planner",
        "category": "models",
        "description": "Build a prioritized install/repair queue so missing local models can be synced automatically.",
        "cadence": "idle_cycle",
    },
    {
        "id": "workspace_queue_index",
        "name": "Workspace Queue Index",
        "category": "workspace",
        "description": "Snapshot pending git workspace changes into a deterministic queue summary.",
        "cadence": "idle_cycle",
    },
    {
        "id": "goal_backlog_triage",
        "name": "Goal Backlog Triage",
        "category": "planning",
        "description": "Classify open goals by urgency and staleness so local agents can prioritize follow-up work.",
        "cadence": "periodic",
    },
    {
        "id": "memory_signal_quality",
        "name": "Memory Signal Quality Scan",
        "category": "memory",
        "description": "Score recent conversation history for weak memory signals and persistence health issues.",
        "cadence": "periodic",
    },
    {
        "id": "toolchain_preflight",
        "name": "Toolchain Preflight",
        "category": "operations",
        "description": "Validate local toolchain entry points (Ollama, shell, git) without performing destructive actions.",
        "cadence": "periodic",
    },
]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (ValueError, TypeError):
        return float(default)


def _run_command(cmd: list[str], *, timeout_s: float = 4.0) -> str:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=max(0.5, float(timeout_s)),
            check=False,
        )
    except (subprocess.CalledProcessError, OSError):
        return ""
    if int(proc.returncode or 0) != 0:
        return ""
    return str(proc.stdout or "").strip()


def _detect_ram_bytes_windows() -> int:
    class _MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = _MemoryStatusEx()
    status.dwLength = ctypes.sizeof(_MemoryStatusEx)
    try:
        ok = bool(ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)))
    except (ValueError, TypeError):
        ok = False
    if not ok:
        return 0
    return int(status.ullTotalPhys or 0)


def _detect_ram_bytes_posix() -> int:
    page_size = int(getattr(os, "sysconf", lambda *_: 0)("SC_PAGE_SIZE"))
    pages = int(getattr(os, "sysconf", lambda *_: 0)("SC_PHYS_PAGES"))
    if page_size <= 0 or pages <= 0:
        return 0
    return int(page_size * pages)


def _detect_system_memory_bytes() -> int:
    system_name = platform.system().lower()
    if system_name == "windows":
        return _detect_ram_bytes_windows()
    return _detect_ram_bytes_posix()


def _parse_nvidia_csv_line(line: str) -> dict[str, Any] | None:
    parts = [p.strip() for p in str(line or "").split(",")]
    if len(parts) < 2:
        return None
    name = str(parts[0]).strip()
    if not name:
        return None
    vram_mib = _safe_float(parts[1], default=0.0)
    util_pct: float | None = None
    if len(parts) >= 3:
        util_raw = str(parts[2] or "").strip().lower().replace("%", "")
        if util_raw and util_raw not in {"n/a", "na"}:
            util_pct = _safe_float(util_raw, default=0.0)
    return {
        "name": name,
        "vendor": "nvidia",
        "vram_gb": round(max(0.0, float(vram_mib)) / 1024.0, 1),
        "utilization_pct": util_pct,
    }


def _detect_gpu_with_nvidia_smi() -> list[dict[str, Any]]:
    out = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,utilization.gpu",
            "--format=csv,noheader,nounits",
        ],
        timeout_s=3.5,
    )
    rows: list[dict[str, Any]] = []
    for line in out.splitlines():
        parsed = _parse_nvidia_csv_line(line)
        if parsed is not None:
            rows.append(parsed)
    return rows


def _detect_gpu_with_windows_cim() -> list[dict[str, Any]]:
    if platform.system().lower() != "windows":
        return []
    out = _run_command(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            ("Get-CimInstance Win32_VideoController | Select-Object Name,AdapterRAM | ConvertTo-Json -Compress"),
        ],
        timeout_s=4.0,
    )
    if not out:
        return []
    try:
        payload = json.loads(out)
    except json.JSONDecodeError:
        return []
    rows: list[dict[str, Any]] = []
    entries = payload if isinstance(payload, list) else [payload]
    for row in entries:
        if not isinstance(row, dict):
            continue
        name = str(row.get("Name") or "").strip()
        if not name:
            continue
        lower_name = name.lower()
        if "microsoft basic render" in lower_name:
            continue
        adapter_ram = _safe_float(row.get("AdapterRAM"), default=0.0)
        vendor = "nvidia" if "nvidia" in lower_name else ("amd" if "amd" in lower_name else "other")
        rows.append(
            {
                "name": name,
                "vendor": vendor,
                "vram_gb": round(max(0.0, adapter_ram) / (1024.0**3), 1),
                "utilization_pct": None,
            }
        )
    return rows


def classify_device_tier(*, cpu_cores: int, ram_gb: float, max_vram_gb: float) -> str:
    cores = max(1, int(cpu_cores or 1))
    ram = max(0.0, float(ram_gb or 0.0))
    vram = max(0.0, float(max_vram_gb or 0.0))

    if vram >= 16.0 and ram >= 32.0 and cores >= 10:
        return "power"
    if (vram >= 8.0 and ram >= 16.0 and cores >= 8) or (vram <= 0.0 and ram >= 32.0 and cores >= 12):
        return "standard"
    return "low"


def detect_local_hardware_profile() -> dict[str, Any]:
    cpu_cores = max(1, int(os.cpu_count() or 1))
    ram_bytes = max(0, int(_detect_system_memory_bytes() or 0))
    ram_gb = round(float(ram_bytes) / (1024.0**3), 1) if ram_bytes > 0 else 0.0

    gpus = _detect_gpu_with_nvidia_smi()
    if not gpus:
        gpus = _detect_gpu_with_windows_cim()

    max_vram_gb = max((float(row.get("vram_gb") or 0.0) for row in gpus), default=0.0)
    util_values = [float(row["utilization_pct"]) for row in gpus if row.get("utilization_pct") is not None]
    avg_util = round(sum(util_values) / len(util_values), 1) if util_values else None
    tier = classify_device_tier(cpu_cores=cpu_cores, ram_gb=ram_gb, max_vram_gb=max_vram_gb)

    return {
        "cpu": {
            "cores": int(cpu_cores),
        },
        "memory": {
            "total_gb": float(ram_gb),
        },
        "gpu": {
            "count": int(len(gpus)),
            "devices": gpus,
            "max_vram_gb": round(float(max_vram_gb), 1),
            "average_utilization_pct": avg_util,
        },
        "device_tier": tier,
    }


def recommended_local_models_for_tier(tier: str) -> list[dict[str, Any]]:
    rows = _TIER_MODEL_RECIPES.get(str(tier or "").strip().lower(), [])
    return [dict(item) for item in rows]


def local_background_task_catalog() -> list[dict[str, Any]]:
    return [dict(item) for item in _BACKGROUND_TASK_CATALOG]


def build_local_runtime_plan(
    *,
    hardware: dict[str, Any] | None = None,
    local_profile_exists: bool = True,
    ollama_installed: bool = False,
    ollama_running: bool = False,
) -> dict[str, Any]:
    hw = hardware if isinstance(hardware, dict) else detect_local_hardware_profile()
    cpu_cores = int((hw.get("cpu") or {}).get("cores") or 1)
    ram_gb = float((hw.get("memory") or {}).get("total_gb") or 0.0)
    max_vram_gb = float((hw.get("gpu") or {}).get("max_vram_gb") or 0.0)

    tier = classify_device_tier(cpu_cores=cpu_cores, ram_gb=ram_gb, max_vram_gb=max_vram_gb)
    if tier == "power":
        recommended_mode = "local_preferred"
        reason = "Power-tier hardware can run strong local models while retaining cloud fallback."
    elif tier == "standard":
        recommended_mode = "hybrid"
        reason = "Standard-tier hardware is best served by cloud + local hybrid execution."
    else:
        recommended_mode = "cloud_only"
        reason = "Lower-tier hardware should default to cloud models for reliability."

    local_ready = bool(local_profile_exists and ollama_running)
    local_available = bool(local_profile_exists and ollama_installed)
    if recommended_mode in {"hybrid", "local_preferred"} and (local_ready or local_available):
        recommended_connection_path = "local"
    else:
        recommended_connection_path = "cloud"

    models = recommended_local_models_for_tier(tier)
    return {
        "device_tier": tier,
        "recommended_mode": recommended_mode,
        "recommended_connection_path": recommended_connection_path,
        "reason": reason,
        "local_profile_exists": bool(local_profile_exists),
        "local_available": bool(local_available),
        "local_ready": bool(local_ready),
        "recommended_models": models,
        "settings_defaults": {
            "local_background_agents_enabled": bool(tier == "power"),
            "local_background_min_gpu_headroom_pct": int(_DEFAULT_GPU_HEADROOM_PCT),
        },
        "background_tasks": local_background_task_catalog(),
        "fallback": {
            "cloud_mode_supported": True,
            "low_performance_policy": "cloud_only",
        },
    }
