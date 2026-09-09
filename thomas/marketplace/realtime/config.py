from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:
    # For Python < 3.11, use toml package
    try:
        import toml as tomllib  # type: ignore
    except ModuleNotFoundError:
        # If neither is available, provide a stub
        class _TOMLStub:  # type: ignore
            @staticmethod
            def loads(s: str):
                raise ImportError("Neither tomllib (Python 3.11+) nor toml package is available")

        tomllib = _TOMLStub()


@dataclass(frozen=True)
class LatencyBudget:
    stt_to_text_ms: int = 900
    user_to_first_token_ms: int = 1200
    assistant_to_tts_start_ms: int = 500


@dataclass(frozen=True)
class STTConfig:
    enabled: bool = True
    dedupe_window_ms: int = 3500
    min_confidence: float = 0.55
    max_interim_age_ms: int = 6000


@dataclass(frozen=True)
class NudgesConfig:
    enabled: bool = True
    cooldown_sec: int = 30
    max_per_minute: int = 2
    max_per_session: int = 18


@dataclass(frozen=True)
class RealtimeConfig:
    enabled: bool = False
    chat_bridge: str = "direct"  # direct | http
    uploads_dir: str = "runtime/.thomas/uploads/realtime"
    max_upload_bytes: int = 25 * 1024 * 1024
    ws_ping_interval_sec: int = 10
    ws_idle_timeout_sec: int = 60

    stt: STTConfig = field(default_factory=STTConfig)
    nudges: NudgesConfig = field(default_factory=NudgesConfig)
    budgets_fast: LatencyBudget = field(default_factory=lambda: LatencyBudget(600, 800, 350))
    budgets_balanced: LatencyBudget = field(default_factory=LatencyBudget)
    budgets_deep: LatencyBudget = field(default_factory=lambda: LatencyBudget(1400, 2000, 650))

    @property
    def uploads_path(self) -> Path:
        return Path(self.uploads_dir)

    def budget_for_mode(self, mode: str) -> LatencyBudget:
        m = (mode or "balanced").lower()
        if m == "fast":
            return self.budgets_fast
        if m in ("deep", "thinking"):
            return self.budgets_deep
        return self.budgets_balanced


def _merge_dataclass(dc_type, data: dict[str, Any]):
    # Simple, safe merge: only known fields, shallow for nested configs that we manage explicitly.
    kwargs = {}
    for f in dc_type.__dataclass_fields__.values():  # type: ignore[attr-defined]
        if f.name in data:
            kwargs[f.name] = data[f.name]
    return dc_type(**kwargs)


def load_realtime_config(repo_root: str | None = None) -> RealtimeConfig:
    # Default path matches Thomas conventions (runtime/.thomas)
    root = Path(repo_root or os.getcwd())
    cfg_path = root / "runtime" / ".thomas" / "realtime.toml"
    if not cfg_path.exists():
        return RealtimeConfig()

    raw = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    stt = _merge_dataclass(STTConfig, raw.get("stt", {}))
    nudges = _merge_dataclass(NudgesConfig, raw.get("nudges", {}))

    budgets = raw.get("budgets", {})
    bf = _merge_dataclass(LatencyBudget, budgets.get("fast", {})) if "fast" in budgets else LatencyBudget(600, 800, 350)
    bb = _merge_dataclass(LatencyBudget, budgets.get("balanced", {})) if "balanced" in budgets else LatencyBudget()
    bd = (
        _merge_dataclass(LatencyBudget, budgets.get("deep", {}))
        if "deep" in budgets
        else LatencyBudget(1400, 2000, 650)
    )

    base = {k: v for k, v in raw.items() if k not in ("stt", "nudges", "budgets")}
    cfg = _merge_dataclass(RealtimeConfig, base)
    return RealtimeConfig(
        enabled=cfg.enabled,
        chat_bridge=cfg.chat_bridge,
        uploads_dir=cfg.uploads_dir,
        max_upload_bytes=cfg.max_upload_bytes,
        ws_ping_interval_sec=cfg.ws_ping_interval_sec,
        ws_idle_timeout_sec=cfg.ws_idle_timeout_sec,
        stt=stt,
        nudges=nudges,
        budgets_fast=bf,
        budgets_balanced=bb,
        budgets_deep=bd,
    )
