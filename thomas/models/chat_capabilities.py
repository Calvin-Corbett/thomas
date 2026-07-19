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
    return raw if raw in {"none", "low", "medium", "high", "xhigh", "max"} else ""


def profile_chat_control_map(cfg: ModelConfig) -> dict[str, Any]:
    """Return chat control metadata for a profile."""
    provider = str(getattr(cfg, "provider", "") or "").strip().lower()
    reasoning_default = _normalize_reasoning_effort(getattr(cfg, "reasoning_effort", ""))
    supports_reasoning_effort = bool(provider in {"openai_codex", "openai-codex"} or reasoning_default)

    model_controls: dict[str, Any] = {}
    if supports_reasoning_effort:
        model_controls["reasoning_effort"] = {
            "supported": True,
            "label": "Reasoning" if provider in {"openai_codex", "openai-codex"} else "Reasoning Effort",
            "default_value": reasoning_default or ("medium" if provider in {"openai_codex", "openai-codex"} else ""),
            "options": [
                _option("none", "None"),
                _option("low", "Low"),
                _option("medium", "Medium"),
                _option("high", "High"),
                _option("xhigh", "xHigh"),
                _option("max", "Max"),
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
                    _option("3", "L3 Agent"),
                    _option("4", "L4 Full Autonomy"),
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
