"""Shared token-economy policy for server, CLI, and agent runtime.

Token economy controls the **number of passes** (iterations) Thomas performs.
Reasoning depth is automatic — determined by the provider/model, not by Thomas.

Levels:
  cheap   — minimal passes (1 pass, single-shot answer)
  optimal — standard passes (default, balanced iteration count)
  max     — extended passes (more iterations for thorough work)
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

from thomas.core.config import AppConfig

TOKEN_ECONOMY_LEVELS = ("cheap", "optimal", "max")
TOKEN_ECONOMY_ALIASES = {
    "balanced": "optimal",
}
RUN_MODES = ("auto", "fast", "thinking")

# Number of passes (iterations) per economy level.
# These multiply against the base max_agent_iterations from config.
_PASS_MULTIPLIERS = {
    "cheap": 0.3,  # ~1-3 passes — single-shot, minimal iteration
    "optimal": 1.0,  # default number of passes from config
    "max": 2.5,  # extended passes for thorough multi-step work
}

_MIN_PASSES = {
    "cheap": 1,
    "optimal": 3,
    "max": 8,
}

_MAX_PASSES = {
    "cheap": 3,
    "optimal": 15,
    "max": 32,
}


@dataclass(frozen=True)
class RuntimeOverheadPolicy:
    """Controls prompt/context extras by token-economy level.

    These settings are about runtime prompt overhead, not repo-integrity hooks.
    Cheap mode should stay lean; optimal keeps the highest-signal extras; max keeps
    the fuller context stack.
    """

    include_purpose_brief: bool
    include_autonomy_profile: bool
    include_editing_policy: bool
    include_project_instructions: bool
    include_best_practice_hint: bool
    include_review_quality_hint: bool
    include_test_visibility_hint: bool
    include_library_context: bool
    include_memory_profile: bool
    runtime_skills_mode: str


_RUNTIME_OVERHEAD_POLICIES: dict[str, RuntimeOverheadPolicy] = {
    "cheap": RuntimeOverheadPolicy(
        include_purpose_brief=False,
        include_autonomy_profile=False,
        include_editing_policy=False,
        include_project_instructions=False,
        include_best_practice_hint=False,
        include_review_quality_hint=False,
        include_test_visibility_hint=False,
        include_library_context=False,
        include_memory_profile=False,
        runtime_skills_mode="off",
    ),
    "optimal": RuntimeOverheadPolicy(
        include_purpose_brief=False,
        include_autonomy_profile=True,
        include_editing_policy=True,
        include_project_instructions=True,
        include_best_practice_hint=True,
        include_review_quality_hint=True,
        include_test_visibility_hint=False,
        include_library_context=True,
        include_memory_profile=False,
        runtime_skills_mode="explicit",
    ),
    "max": RuntimeOverheadPolicy(
        include_purpose_brief=True,
        include_autonomy_profile=True,
        include_editing_policy=True,
        include_project_instructions=True,
        include_best_practice_hint=True,
        include_review_quality_hint=True,
        include_test_visibility_hint=True,
        include_library_context=True,
        include_memory_profile=True,
        runtime_skills_mode="explicit",
    ),
}


def normalize_token_economy_level(raw: Any) -> str:
    level = str(raw or "").strip().lower()
    if level in TOKEN_ECONOMY_ALIASES:
        level = TOKEN_ECONOMY_ALIASES[level]
    if level in TOKEN_ECONOMY_LEVELS:
        return level
    return "optimal"


def normalize_mode(raw: Any, *, default: str = "auto") -> str:
    mode = str(raw or default).strip().lower()
    if mode in RUN_MODES:
        return mode
    return str(default or "auto").strip().lower() or "auto"


def build_token_economy_meta(requested_level: Any, applied_level: str | None = None) -> dict[str, str]:
    requested = str(requested_level or "").strip().lower()
    applied = normalize_token_economy_level(applied_level if applied_level is not None else requested)
    return {
        "requested": requested or "optimal",
        "applied": applied,
    }


def runtime_overhead_policy(level: Any) -> RuntimeOverheadPolicy:
    """Return runtime prompt/context overhead policy for the economy level."""
    applied = normalize_token_economy_level(level)
    return _RUNTIME_OVERHEAD_POLICIES[applied]


def compute_max_passes(level: Any, base_iterations: int) -> int:
    """Compute the max iterations (passes) for a given economy level.

    Args:
        level: Token economy level (cheap/optimal/max).
        base_iterations: The base max_agent_iterations from config.

    Returns:
        Clamped number of passes.
    """
    applied = normalize_token_economy_level(level)
    multiplier = _PASS_MULTIPLIERS[applied]
    raw = int(base_iterations * multiplier)
    return max(_MIN_PASSES[applied], min(_MAX_PASSES[applied], raw))


def apply_token_economy_policy(
    *,
    cfg: AppConfig,
    requested_level: Any,
    requested_mode: Any,
) -> tuple[str, str, AppConfig, int | None]:
    """Return (applied_level, mode, run_cfg, max_iterations_override).

    Token economy controls the number of passes.  Reasoning depth is
    automatic — left to the provider/model.
    """
    level = normalize_token_economy_level(requested_level)
    mode = normalize_mode(requested_mode, default="auto")

    # Compute pass count from economy level.
    max_iterations_override = compute_max_passes(level, cfg.max_agent_iterations)

    # Quality config adjustments are minimal — just disable retries on cheap.
    quality_cfg = cfg.quality
    if level == "cheap":
        quality_cfg = replace(
            quality_cfg,
            max_auto_retries=0,
        )
    elif level == "max":
        quality_cfg = replace(
            quality_cfg,
            max_auto_retries=max(
                2,
                min(3, int(getattr(quality_cfg, "max_auto_retries", 1) or 0)),
            ),
        )

    run_cfg = cfg if quality_cfg is cfg.quality else replace(cfg, quality=quality_cfg)
    return level, mode, run_cfg, max_iterations_override


def loop_context_budgets(level: Any, mode: Any) -> tuple[int, int | None, int]:
    """Return (mode_budget, hard_budget, emergency_budget).

    Budgets scale with pass count — more passes need more token room.
    """
    applied = normalize_token_economy_level(level)
    run_mode = normalize_mode(mode, default="auto")

    base_mode_budget = {
        "fast": 90_000,
        "auto": 180_000,
        "thinking": 320_000,
    }.get(run_mode, 180_000)
    multiplier = {"cheap": 0.6, "optimal": 1.0, "max": 2.0}[applied]
    mode_budget = max(40_000, int(base_mode_budget * multiplier))

    if applied == "cheap":
        hard_budget: int | None = 250_000
    elif applied == "optimal":
        hard_budget = 650_000
    else:
        hard_budget = None

    emergency_budget = 1_800_000
    return mode_budget, hard_budget, emergency_budget


def loop_tool_spec_budgets(level: Any, mode: Any) -> tuple[int, int]:
    """Return (tool_count_cap, tool_spec_token_cap)."""
    applied = normalize_token_economy_level(level)
    run_mode = normalize_mode(mode, default="auto")

    base_tool_count = {"fast": 8, "auto": 16, "thinking": 24}.get(run_mode, 16)
    base_spec_tokens = {"fast": 1800, "auto": 2600, "thinking": 3600}.get(run_mode, 2600)
    multiplier = {"cheap": 0.75, "optimal": 1.0, "max": 1.45}[applied]

    tool_count_cap = max(4, min(40, int(base_tool_count * multiplier)))
    tool_spec_token_cap = max(1200, min(7200, int(base_spec_tokens * multiplier)))
    return tool_count_cap, tool_spec_token_cap


def loop_iteration_prompt_caps(level: Any, mode: Any) -> tuple[int, int | None]:
    """Return (warn_cap, hard_cap) for prompt tokens spent in a single iteration."""
    applied = normalize_token_economy_level(level)
    run_mode = normalize_mode(mode, default="auto")

    base_warn = {"fast": 8_000, "auto": 12_000, "thinking": 18_000}.get(run_mode, 12_000)
    base_hard = {"fast": 16_000, "auto": 24_000, "thinking": 36_000}.get(run_mode, 24_000)
    multiplier = {"cheap": 0.75, "optimal": 1.0, "max": 2.0}[applied]

    warn_cap = max(4_000, int(base_warn * multiplier))
    if applied == "max":
        hard_cap: int | None = None
    else:
        hard_cap = max(warn_cap + 2_000, int(base_hard * multiplier))
    return warn_cap, hard_cap
