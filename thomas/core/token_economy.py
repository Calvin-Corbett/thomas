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
    # Public "Effort" vocabulary (Brisk / Diligent / Exhaustive) maps onto the
    # internal token-economy levels (cheap / optimal / max). The user-facing dial
    # is "Effort"; the internal keys stay for backward-compat across the pipeline.
    "brisk": "cheap",
    "diligent": "optimal",
    "exhaustive": "max",
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
    if not level:
        return "optimal"
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


def coerce_base_iterations(value: Any, *, default: int = 10) -> int:
    """Return a usable max-iteration base for runtime scaling."""
    try:
        base = int(value or default)
    except (TypeError, ValueError):
        base = int(default)
    return max(1, base)


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


def compute_max_passes(level: Any, base_iterations: int | None) -> int:
    """Compute the max iterations (passes) for a given economy level.

    Args:
        level: Token economy level (cheap/optimal/max).
        base_iterations: The base max_agent_iterations from config. Missing,
            zero, or invalid values fall back to the AppConfig default.

    Returns:
        Clamped number of passes.
    """
    applied = normalize_token_economy_level(level)
    multiplier = _PASS_MULTIPLIERS[applied]
    base = coerce_base_iterations(base_iterations)
    raw = int(base * multiplier)
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


# ── Effort dial — public vocabulary + Autonomy coupling + cost ──────────────────
# The user-facing dial is "Effort": Brisk / Diligent / Exhaustive. These are public
# aliases over the internal token-economy levels (cheap / optimal / max), which stay
# for backward-compat. Effort is deliberately NOT orthogonal to Autonomy — see
# effective_effort(). Cost helpers are advisory pre-dispatch estimates for budgeting.

EFFORT_LEVELS = ("brisk", "diligent", "exhaustive")
_EFFORT_TO_INTERNAL = {"brisk": "cheap", "diligent": "optimal", "exhaustive": "max"}
_INTERNAL_TO_EFFORT = {internal: effort for effort, internal in _EFFORT_TO_INTERNAL.items()}

# Rough output-tokens per pass, for advisory pre-dispatch cost estimates only.
_TOKENS_PER_PASS = 3_000


def internal_to_effort(level: Any) -> str:
    """Map an internal token-economy level (or Effort name) to its public Effort name."""
    return _INTERNAL_TO_EFFORT.get(normalize_token_economy_level(level), "diligent")


def effort_display_name(level: Any) -> str:
    """Title-case public Effort label, e.g. 'Exhaustive'."""
    return internal_to_effort(level).title()


def effective_effort(level: Any, autonomy_level: int) -> str:
    """Apply the Effort<->Autonomy coupling; return the internal level to actually run.

    Effort and Autonomy are deliberately NOT orthogonal:
      * L1 (chat-only) caps Effort to Brisk — no deep pipeline at the lowest autonomy.
      * Exhaustive requires L3+ (Agent/Full); below that it steps down to Diligent.
      * L4+ (full agent) auto-promotes Brisk -> Diligent (full autonomy implies real work).
    """
    internal = normalize_token_economy_level(level)
    try:
        a = int(autonomy_level)
    except (TypeError, ValueError):
        a = 3
    if a <= 1:
        return "cheap"
    if internal == "max" and a < 3:
        internal = "optimal"
    if a >= 4 and internal == "cheap":
        internal = "optimal"
    return internal


def _passes_for(internal_level: str) -> tuple[int, int]:
    return _MIN_PASSES[internal_level], _MAX_PASSES[internal_level]


def _cost_for(internal_level: str, team_size: int) -> tuple[int, int]:
    lo, hi = _passes_for(internal_level)
    team = max(1, int(team_size or 1))
    return lo * _TOKENS_PER_PASS * team, hi * _TOKENS_PER_PASS * team


def estimate_passes(level: Any, autonomy_level: int) -> tuple[int, int]:
    """(min, max) passes for an Effort level after the Autonomy coupling."""
    return _passes_for(effective_effort(level, autonomy_level))


def estimate_token_cost(level: Any, autonomy_level: int, *, team_size: int = 1) -> tuple[int, int]:
    """Advisory (min, max) output-token estimate for a run.

    Cost scales with passes x team size. A rough pre-dispatch estimate for budgeting
    and UI, NOT hard accounting — calibrate ``_TOKENS_PER_PASS`` from telemetry.
    """
    return _cost_for(effective_effort(level, autonomy_level), team_size)


def within_budget(level: Any, autonomy_level: int, budget_tokens: int | None, *, team_size: int = 1) -> bool:
    """True if the worst-case estimate fits the spend cap (no cap -> always True)."""
    if not budget_tokens or int(budget_tokens) <= 0:
        return True
    return estimate_token_cost(level, autonomy_level, team_size=team_size)[1] <= int(budget_tokens)


def degrade_to_budget(
    level: Any, autonomy_level: int, budget_tokens: int | None, *, team_size: int = 1
) -> tuple[str, int]:
    """Return (internal_level, team_size) reduced until the worst-case estimate fits.

    Spend cap with graceful degradation: shrink the team first, then step Effort
    down (max -> optimal -> cheap), rather than rejecting the task outright.
    """
    applied = effective_effort(level, autonomy_level)
    team = max(1, int(team_size or 1))
    if not budget_tokens or int(budget_tokens) <= 0:
        return applied, team
    budget = int(budget_tokens)
    while team > 1 and _cost_for(applied, team)[1] > budget:
        team -= 1
    ladder = ["max", "optimal", "cheap"]
    while applied in ladder and ladder.index(applied) < len(ladder) - 1 and _cost_for(applied, team)[1] > budget:
        applied = ladder[ladder.index(applied) + 1]
    return applied, team
