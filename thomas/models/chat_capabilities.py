"""Chat-surface control capabilities for model profiles.

This keeps chat UI controls explicit and provider-aware. Thomas-owned controls
stay available across profiles, while model-owned controls only surface when a
profile actually supports them.
"""

from __future__ import annotations

from typing import Any

from thomas.core.config import ModelConfig


def _option(value: str, label: str) -> dict[str, str]:
    return {"value": str(value), "label": str(label)}


def _normalize_reasoning_effort(value: str) -> str:
    raw = str(value or "").strip().lower()
    if raw == "max":
        return "xhigh"
    return raw if raw in {"low", "medium", "high", "xhigh"} else ""


def profile_chat_control_map(cfg: ModelConfig) -> dict[str, Any]:
    """Return chat control metadata for a profile."""
    provider = str(getattr(cfg, "provider", "") or "").strip().lower()
    reasoning_default = _normalize_reasoning_effort(getattr(cfg, "reasoning_effort", ""))
    supports_reasoning_effort = bool(provider == "codex" or reasoning_default)

    model_controls: dict[str, Any] = {}
    if supports_reasoning_effort:
        model_controls["reasoning_effort"] = {
            "supported": True,
            "label": "Reasoning" if provider == "codex" else "Reasoning Effort",
            "default_value": reasoning_default or ("medium" if provider == "codex" else ""),
            "options": [
                _option("", "Auto"),
                _option("low", "Low"),
                _option("medium", "Medium"),
                _option("high", "High"),
                _option("xhigh", "xHigh"),
            ],
        }

    return {
        "model": model_controls,
        "thomas": {
            "autonomy_level": {
                "supported": True,
                "label": "Autonomy",
                "default_value": "1",
                "options": [
                    _option("1", "L1 Chat"),
                    _option("2", "L2 Assist"),
                    _option("3", "L3 Auto"),
                    _option("4", "L4 Agent"),
                ],
            },
            "token_economy": {
                "supported": True,
                "label": "Token Economy",
                "default_value": "balanced",
                "options": [
                    _option("cheap", "Cheap"),
                    _option("balanced", "Balanced"),
                    _option("max", "Maximum"),
                ],
            },
        },
    }